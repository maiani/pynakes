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

    def read(self) -> bytes:
        return self._data

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

    monkeypatch.setattr("pynakes.providers._http.httpx.Client", MockClient)


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
