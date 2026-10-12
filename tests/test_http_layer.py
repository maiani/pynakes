"""The HTTP layer's deadline, size-cap, and failure contracts, entirely offline.

Socket-level tests talk to a local socket pair standing in for the network, so
nothing here can reach a real host.
"""

import socket
import threading
import time

import httpcore
import httpx
import pytest

from pynakes.provider_cache import open_cache
from pynakes.providers import _http, _network
from pynakes.providers._http import ProviderFetchError, fetch_bytes, fetch_json

# conftest zeroes retry delays; the retry-boundary tests need the real backoff.
REAL_RETRY_DELAY = _http._retry_delay


def mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        _http.httpx, "Client", lambda **kwargs: original(**{**kwargs, "transport": transport})
    )


def lookup(url="https://example.test/work", **kwargs):
    return fetch_json(url, namespace="test", identifier="Newton1687", provider="Invented", **kwargs)


# --- Overall deadline: DNS resolution ---------------------------------------


@pytest.fixture
def stalled_dns(monkeypatch):
    release = threading.Event()

    def stall(host, port):
        release.wait(10)
        return ["93.184.216.34"]

    monkeypatch.setattr(_network, "_getaddrinfo", stall)
    yield
    release.set()


def test_a_stalled_resolver_ends_at_the_deadline(stalled_dns):
    started = time.monotonic()
    with pytest.raises(_network.DeadlineExceeded, match="resolving example.test"):
        _network.resolve_addresses("example.test", 443, time.monotonic() + 0.2)
    assert time.monotonic() - started < 2


def test_a_stalled_resolver_fails_a_download_by_its_deadline(stalled_dns):
    started = time.monotonic()
    with pytest.raises(ProviderFetchError, match="deadline"):
        fetch_bytes("https://example.test/paper.pdf", deadline_seconds=0.3, sleep=lambda _: None)
    assert time.monotonic() - started < 2


def test_resolver_errors_reach_the_caller(monkeypatch):
    def fail(host, port):
        raise socket.gaierror("name not known")

    monkeypatch.setattr(_network, "_getaddrinfo", fail)
    with pytest.raises(socket.gaierror):
        _network.resolve_addresses("example.test", 443, time.monotonic() + 5)
    with pytest.raises(ProviderFetchError, match="name not known"):
        fetch_bytes("https://example.test", sleep=lambda _: None)


def test_an_expired_deadline_skips_resolution(monkeypatch):
    monkeypatch.setattr(_network, "_getaddrinfo", lambda *_: pytest.fail("resolved"))
    with pytest.raises(_network.DeadlineExceeded):
        _network.resolve_addresses("example.test", 443, time.monotonic() - 1)


# --- Overall deadline: socket reads -----------------------------------------


def test_the_deadline_wrapper_is_installed_on_the_transport():
    transport = _network.PublicTransport(deadline=time.monotonic() + 5)
    assert isinstance(transport._pool._network_backend, _network._DeadlineBackend)


class _RecordingStream(httpcore.NetworkStream):
    def __init__(self):
        self.timeouts = []

    def read(self, max_bytes, timeout=None):
        self.timeouts.append(timeout)
        return b"x"


def test_each_socket_read_gets_only_the_time_left():
    inner = _RecordingStream()
    stream = _network._DeadlineStream(inner, time.monotonic() + 1)
    stream.read(10, timeout=30)
    assert 0 < inner.timeouts[0] <= 1
    expired = _network._DeadlineStream(inner, time.monotonic() - 1)
    with pytest.raises(_network.DeadlineExceeded):
        expired.read(10, timeout=30)
    assert len(inner.timeouts) == 1


def test_trickled_headers_cannot_outlast_the_deadline(monkeypatch):
    """Each byte arrives well inside the read timeout; only the deadline ends it."""
    server, client = socket.socketpair()
    stop = threading.Event()

    def trickle():
        server.recv(65536)
        try:
            server.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
            while not stop.wait(0.05):
                server.sendall(b"a")
        except OSError:
            pass

    worker = threading.Thread(target=trickle, daemon=True)
    worker.start()
    monkeypatch.setattr(
        httpcore.SyncBackend,
        "connect_tcp",
        lambda self, *args, **kwargs: httpcore._backends.sync.SyncStream(client),
    )
    started = time.monotonic()
    try:
        with pytest.raises(ProviderFetchError, match="deadline"):
            fetch_bytes(
                "http://example.test/paper.pdf",
                timeout=30.0,
                deadline_seconds=0.5,
                sleep=lambda _: None,
            )
    finally:
        stop.set()
        server.close()
        client.close()
    assert time.monotonic() - started < 3


# --- Injected openers: bounded reads ----------------------------------------


class _Endless:
    """A response that never ends; records how much was requested."""

    def __init__(self, on_read=None):
        self.requested = 0
        self.on_read = on_read

    def read(self, size=-1):
        assert size > 0, "an opener's response must be read in bounded chunks"
        self.requested += size
        if self.on_read:
            self.on_read()
        return b"x" * size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def test_an_opener_response_is_cut_off_just_past_the_cap():
    response = _Endless()
    with pytest.raises(ProviderFetchError, match="size limit"):
        fetch_bytes("https://example.test", opener=lambda *a, **k: response, max_bytes=100_000)
    assert response.requested <= 100_001


def test_an_opener_response_is_stopped_by_the_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])

    def tick():
        now[0] += 0.4

    with pytest.raises(ProviderFetchError, match="deadline"):
        fetch_bytes(
            "https://example.test",
            opener=lambda *a, **k: _Endless(tick),
            deadline_seconds=1.0,
        )


def test_an_opener_socket_error_past_the_deadline_is_not_retried(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        now[0] = 5.0
        raise TimeoutError("timed out")

    with pytest.raises(ProviderFetchError, match="deadline"):
        fetch_bytes("https://example.test", opener=opener, deadline_seconds=1.0)
    assert len(calls) == 1


def test_metadata_opener_is_capped_and_socket_errors_are_provider_errors(monkeypatch):
    monkeypatch.setattr(_http, "MAX_METADATA_BYTES", 1000)
    with pytest.raises(ProviderFetchError, match="size limit"):
        lookup(opener=lambda *a, **k: _Endless())

    def refused(*args, **kwargs):
        raise ConnectionResetError("reset by peer")

    with pytest.raises(ProviderFetchError, match="Invented lookup failed.*reset by peer"):
        lookup(opener=refused)


# --- Metadata over the default transport ------------------------------------


def test_metadata_not_found_is_none_and_not_cached(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda _: httpx.Response(404))
    assert lookup(cache_file=tmp_path / "cache") is None
    assert open_cache(tmp_path / "cache").get("test", "Newton1687", "json") is None


@pytest.mark.parametrize("status", [400, 403, 500, 503])
def test_metadata_http_errors_name_the_provider_and_status(monkeypatch, status):
    mock_http(monkeypatch, lambda _: httpx.Response(status))
    with pytest.raises(ProviderFetchError, match=f"Invented lookup failed.*HTTP {status}"):
        lookup()


def test_a_declared_oversized_metadata_response_is_refused_unread(monkeypatch):
    mock_http(
        monkeypatch,
        lambda _: httpx.Response(200, headers={"content-length": str(64 << 20)}, content=b"{}"),
    )
    with pytest.raises(ProviderFetchError, match="size limit"):
        lookup()


def test_a_broken_metadata_stream_is_a_provider_error(monkeypatch):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"title": '
            raise httpx.RemoteProtocolError("peer closed connection")

    mock_http(monkeypatch, lambda _: httpx.Response(200, stream=Broken()))
    with pytest.raises(ProviderFetchError, match="peer closed connection"):
        lookup()


def test_a_slow_metadata_stream_reports_the_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            now[0] = _network.DEFAULT_DEADLINE + 1
            yield b"{}"

    mock_http(monkeypatch, lambda _: httpx.Response(200, stream=Slow()))
    with pytest.raises(ProviderFetchError, match="deadline"):
        lookup()


def test_unsafe_metadata_urls_never_reach_the_cache_or_network(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda _: pytest.fail("unsafe request was sent"))
    with pytest.raises(ProviderFetchError, match="Unsafe"):
        lookup("file:///etc/passwd", cache_file=tmp_path / "cache")


# --- The deterministic cache ------------------------------------------------


def test_invalid_json_from_the_network_is_an_error_and_not_cached(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda _: httpx.Response(200, content=b"<html>busy</html>"))
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        lookup(cache_file=tmp_path / "cache")
    assert open_cache(tmp_path / "cache").get("test", "Newton1687", "json") is None


def test_corrupt_cached_json_is_an_error_without_a_network_request(monkeypatch, tmp_path):
    open_cache(tmp_path / "cache").put("test", "Newton1687", "json", "{truncated")
    mock_http(monkeypatch, lambda _: pytest.fail("a cached lookup used the network"))
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        lookup(cache_file=tmp_path / "cache")


def test_a_cached_non_object_is_treated_as_no_record(monkeypatch, tmp_path):
    open_cache(tmp_path / "cache").put("test", "Newton1687", "json", "[1, 2]")
    mock_http(monkeypatch, lambda _: pytest.fail("a cached lookup used the network"))
    assert lookup(cache_file=tmp_path / "cache") is None


def test_valid_json_is_cached_and_served_offline(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json={"title": "Principia"}))
    assert lookup(cache_file=tmp_path / "cache") == {"title": "Principia"}
    mock_http(monkeypatch, lambda _: pytest.fail("a cached lookup used the network"))
    assert lookup(cache_file=tmp_path / "cache") == {"title": "Principia"}


# --- Retry boundaries -------------------------------------------------------


def test_no_retry_is_attempted_when_its_wait_would_pass_the_deadline(monkeypatch):
    monkeypatch.setattr(_http, "_retry_delay", REAL_RETRY_DELAY)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, headers={"Retry-After": "20"})

    mock_http(monkeypatch, handler)
    slept = []
    with pytest.raises(ProviderFetchError, match="deadline"):
        fetch_bytes("https://example.test", deadline_seconds=10.0, sleep=slept.append)
    assert len(calls) == 1
    assert slept == []


def test_retries_stop_after_the_attempt_budget(monkeypatch):
    monkeypatch.setattr(_http, "_retry_delay", REAL_RETRY_DELAY)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502)

    mock_http(monkeypatch, handler)
    slept = []
    with pytest.raises(ProviderFetchError, match="HTTP 502"):
        fetch_bytes("https://example.test", sleep=slept.append)
    assert len(calls) == _http.MAX_ATTEMPTS
    assert slept == list(_http.BACKOFF_SECONDS)


def test_a_request_after_the_deadline_is_never_sent(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])
    calls = []

    def handler(request):
        calls.append(1)
        now[0] = 100.0
        raise httpx.ConnectError("refused")

    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderFetchError, match="deadline"):
        fetch_bytes("https://example.test", deadline_seconds=10.0, sleep=lambda _: None)
    assert len(calls) == 1
