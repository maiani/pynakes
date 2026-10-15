"""Tests for provider HTTP retry, backoff, and Retry-After handling."""

import email.utils
import time
from urllib.error import HTTPError, URLError

import httpx
import pytest

from pynakes.providers import _http
from pynakes.providers._http import ProviderFetchError, fetch_bytes


class _Response:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, size: int = -1) -> bytes:
        size = len(self._data) if size < 0 else size
        data, self._data = self._data[:size], self._data[size:]
        return data

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _opener_raising(*failures: Exception, then: bytes = b"ok"):
    """Return an opener that raises each failure in turn, then succeeds."""
    queue = list(failures)
    calls: list[float] = []

    def opener(request: object, timeout: float) -> _Response:
        calls.append(timeout)
        if queue:
            raise queue.pop(0)
        return _Response(then)

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def _http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
    return HTTPError("https://example.test", code, "boom", headers or {}, None)  # type: ignore[arg-type]


def test_a_throttle_is_retried_rather_than_surfaced_immediately() -> None:
    # A 429 is a request to slow down, not a refusal. Surfacing the first one
    # turned a transient throttle into a permanent-looking import failure.
    opener = _opener_raising(_http_error(429))
    slept: list[float] = []

    data = fetch_bytes("https://example.test", opener=opener, sleep=slept.append, timeout=5.0)

    assert data == b"ok"
    assert len(opener.calls) == 2
    assert slept == [_http.BACKOFF_SECONDS[0]]


def test_a_read_timeout_is_retried() -> None:
    opener = _opener_raising(URLError(TimeoutError("The read operation timed out")))
    slept: list[float] = []

    assert fetch_bytes("https://example.test", opener=opener, sleep=slept.append) == b"ok"
    assert len(opener.calls) == 2


def test_transient_server_errors_are_retried() -> None:
    opener = _opener_raising(_http_error(503), _http_error(502))

    assert fetch_bytes("https://example.test", opener=opener, sleep=lambda _: None) == b"ok"
    assert len(opener.calls) == 3


def test_retry_after_seconds_overrides_the_default_backoff() -> None:
    opener = _opener_raising(_http_error(429, {"Retry-After": "7"}))
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept == [7.0]


def test_retry_after_accepts_an_http_date() -> None:
    when = email.utils.formatdate(time.time() + 5, usegmt=True)
    opener = _opener_raising(_http_error(429, {"Retry-After": when}))
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept and 0 < slept[0] <= 6


def test_an_absurd_retry_after_is_clamped() -> None:
    opener = _opener_raising(_http_error(429, {"Retry-After": "86400"}))
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept == [_http.MAX_RETRY_AFTER]


def test_an_unparseable_retry_after_falls_back_to_the_default_backoff() -> None:
    opener = _opener_raising(_http_error(429, {"Retry-After": "soon"}))
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept == [_http.BACKOFF_SECONDS[0]]


def test_giving_up_reports_the_last_failure_verbatim() -> None:
    opener = _opener_raising(*[_http_error(429) for _ in range(_http.MAX_ATTEMPTS)])

    with pytest.raises(ProviderFetchError, match="HTTP 429"):
        fetch_bytes("https://example.test", opener=opener, sleep=lambda _: None)

    assert len(opener.calls) == _http.MAX_ATTEMPTS


def test_a_permanent_error_is_not_retried() -> None:
    # 404 means the record is not there; asking twice cannot change that.
    opener = _opener_raising(_http_error(404))

    with pytest.raises(ProviderFetchError, match="HTTP 404"):
        fetch_bytes("https://example.test", opener=opener, sleep=lambda _: None)

    assert len(opener.calls) == 1


def test_a_domain_error_class_survives_the_retry_loop() -> None:
    class ArchiveError(Exception):
        pass

    opener = _opener_raising(*[_http_error(429) for _ in range(_http.MAX_ATTEMPTS)])

    with pytest.raises(ArchiveError):
        fetch_bytes(
            "https://example.test",
            opener=opener,
            error_class=ArchiveError,
            sleep=lambda _: None,
        )


def test_a_successful_first_attempt_never_sleeps() -> None:
    opener = _opener_raising()
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept == []
    assert len(opener.calls) == 1


# --- the default transport (httpx), which is what production actually uses ---


def _mock_httpx_client(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", MockClient)


def test_httpx_transport_retries_a_throttle(monkeypatch) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, text="slow down")
        return httpx.Response(200, content=b"ok")

    _mock_httpx_client(monkeypatch, handler)
    slept: list[float] = []

    assert fetch_bytes("https://example.test", sleep=slept.append) == b"ok"
    assert len(seen) == 2
    assert slept == [3.0]


def test_httpx_transport_does_not_retry_a_permanent_error(monkeypatch) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(404, text="nope")

    _mock_httpx_client(monkeypatch, handler)

    with pytest.raises(ProviderFetchError, match="HTTP 404"):
        fetch_bytes("https://example.test", sleep=lambda _: None)

    assert len(seen) == 1


def test_httpx_transport_retries_a_transport_failure(monkeypatch) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return httpx.Response(200, content=b"ok")

    _mock_httpx_client(monkeypatch, handler)

    assert fetch_bytes("https://example.test", sleep=lambda _: None) == b"ok"
    assert len(seen) == 2


def test_a_retry_after_already_in_the_past_does_not_wait(monkeypatch) -> None:
    when = email.utils.formatdate(time.time() - 60, usegmt=True)
    opener = _opener_raising(_http_error(429, {"Retry-After": when}))
    slept: list[float] = []

    fetch_bytes("https://example.test", opener=opener, sleep=slept.append)

    assert slept == [0.0]


def test_httpx_transport_refuses_a_declared_oversized_download(monkeypatch) -> None:
    monkeypatch.setattr("pynakes.providers._http.MAX_DOWNLOAD_BYTES", 1024)
    _mock_httpx_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"Content-Length": "4096"}, content=b"x" * 4096
        ),
    )

    with pytest.raises(ProviderFetchError, match="download limit"):
        fetch_bytes("https://example.test/paper.pdf", sleep=lambda _s: None)


def test_httpx_transport_stops_an_undeclared_oversized_download(monkeypatch) -> None:
    monkeypatch.setattr("pynakes.providers._http.MAX_DOWNLOAD_BYTES", 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=iter([b"x" * 600, b"x" * 600, b"x" * 600]))

    _mock_httpx_client(monkeypatch, handler)

    with pytest.raises(ProviderFetchError, match="download limit"):
        fetch_bytes("https://example.test/paper.pdf", sleep=lambda _s: None)


def test_a_throttle_that_outlasts_every_retry_is_reported_as_rate_limiting() -> None:
    opener = _opener_raising(*[_http_error(429) for _ in range(_http.MAX_ATTEMPTS)])

    with pytest.raises(_http.ProviderRateLimitedError, match="HTTP 429"):
        fetch_bytes("https://example.test", opener=opener, sleep=lambda _: None)


def test_a_server_error_that_outlasts_every_retry_is_not_rate_limiting() -> None:
    opener = _opener_raising(*[_http_error(503) for _ in range(_http.MAX_ATTEMPTS)])

    with pytest.raises(ProviderFetchError) as caught:
        fetch_bytes("https://example.test", opener=opener, sleep=lambda _: None)
    assert not isinstance(caught.value, _http.ProviderRateLimitedError)


# --- metadata lookups (fetch_json) -------------------------------------------


def _lookup(opener, monkeypatch) -> tuple[dict | None, list[float]]:
    slept: list[float] = []
    monkeypatch.setattr(_http, "_sleep", slept.append)
    data = _http.fetch_json(
        "https://example.test/works/1",
        namespace="test",
        identifier="10.5555/one",
        provider="Example",
        opener=opener,
    )
    return data, slept


def test_a_throttled_metadata_lookup_is_retried(monkeypatch) -> None:
    # A JSON lookup used to fail on the first 429, so a busy provider turned a
    # bulk enrichment into a list of "unresolved" entries nobody had checked.
    opener = _opener_raising(_http_error(429, {"Retry-After": "2"}), then=b'{"ok": 1}')

    data, slept = _lookup(opener, monkeypatch)

    assert data == {"ok": 1}
    assert slept == [2.0]


def test_a_lookup_throttled_through_every_retry_is_reported_as_rate_limited(monkeypatch) -> None:
    opener = _opener_raising(*[_http_error(429)] * _http.MAX_ATTEMPTS)

    with pytest.raises(_http.ProviderRateLimitedError, match="HTTP 429"):
        _lookup(opener, monkeypatch)
    assert len(opener.calls) == _http.MAX_ATTEMPTS


def test_a_missing_record_is_an_answer_and_is_not_retried(monkeypatch) -> None:
    opener = _opener_raising(_http_error(404))

    data, slept = _lookup(opener, monkeypatch)

    assert data is None
    assert slept == []
    assert len(opener.calls) == 1


def test_a_refusal_is_not_retried(monkeypatch) -> None:
    opener = _opener_raising(_http_error(403))

    with pytest.raises(ProviderFetchError, match="HTTP 403") as caught:
        _lookup(opener, monkeypatch)
    assert not isinstance(caught.value, _http.ProviderRateLimitedError)
    assert len(opener.calls) == 1


def test_the_retry_listener_hears_each_wait() -> None:
    heard: list[tuple[str, float, int]] = []
    token = _http.RETRY_LISTENER.set(
        lambda message, delay, attempt: heard.append((message, delay, attempt))
    )
    try:
        fetch_bytes(
            "https://example.test",
            opener=_opener_raising(_http_error(503)),
            sleep=lambda delay: None,
            timeout=5.0,
        )
    finally:
        _http.RETRY_LISTENER.reset(token)

    assert [(delay, attempt) for _, delay, attempt in heard] == [(1.0, 2)]
    assert "HTTP 503" in heard[0][0]


def test_pacing_spaces_requests_to_one_provider_host(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(_http, "PROVIDER_MIN_INTERVAL", {"api.example.test": 0.5})
    monkeypatch.setattr(_http, "_next_slot", {})
    waits: list[float] = []

    for _ in range(3):
        _http.pace("https://api.example.test/works/1", sleep=waits.append)
    _http.pace("https://other.example.test/", sleep=waits.append)

    # Three back-to-back requests reserve consecutive slots; another host waits for none.
    assert waits == [0.5, 1.0]
