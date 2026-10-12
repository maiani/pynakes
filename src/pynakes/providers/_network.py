"""Network destination policy shared by metadata and material requests."""

import ipaddress
import socket
import threading
import time
import warnings
from urllib.parse import urlsplit

import httpcore
import httpx

DEFAULT_DEADLINE = 120.0
MAX_METADATA_BYTES = 8 * 1024 * 1024


class DeadlineExceeded(TimeoutError):
    """The overall network deadline passed while a request was in progress."""


def _getaddrinfo(host: str, port: int) -> list[str]:
    return [str(row[4][0]) for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def resolve_addresses(host: str, port: int, deadline: float | None = None) -> list[str]:
    """Resolve all addresses, so a mixed public/private result is refused.

    ``getaddrinfo`` takes no timeout, and a stalled resolver can block for far
    longer than any socket timeout. With a ``deadline`` (a ``time.monotonic``
    instant), the lookup runs on a daemon thread and :class:`DeadlineExceeded`
    is raised once the deadline passes; the abandoned lookup cannot delay exit.
    """
    if deadline is None:
        return _getaddrinfo(host, port)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded(f"Network deadline exceeded before resolving {host}")
    found: list[list[str]] = []
    errors: list[BaseException] = []

    def lookup() -> None:
        try:
            found.append(_getaddrinfo(host, port))
        except BaseException as exc:  # handed back to the caller's thread
            errors.append(exc)

    worker = threading.Thread(target=lookup, name="pynakes-dns", daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        raise DeadlineExceeded(f"Network deadline exceeded while resolving {host}")
    if errors:
        raise errors[0]
    return found[0]


def validate_url(
    url: str,
    error_class: type[Exception],
    *,
    resolve: bool = True,
    deadline: float | None = None,
) -> None:
    """Refuse non-web schemes, credentials, and non-public destinations."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise error_class(f"Unsafe network URL: {url}")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = resolve_addresses(host, port, deadline) if resolve else []
        except DeadlineExceeded as exc:
            raise error_class(str(exc)) from exc
    else:
        addresses = [str(literal)]
    if host.lower().rstrip(".") == "localhost" or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise error_class(f"Refusing non-public network address: {host}")
    if resolve and not addresses:
        raise error_class(f"No network address for {host}")


def request_guard(error_class: type[Exception], deadline: float):
    """Validate every request, including redirects, before sending it."""
    previous: str | None = None

    def guard(request: httpx.Request) -> None:
        nonlocal previous
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise error_class("Network deadline exceeded")
        timeouts = request.extensions.get("timeout", {})
        for operation in ("connect", "read", "write", "pool"):
            timeout = timeouts.get(operation)
            timeouts[operation] = remaining if timeout is None else min(timeout, remaining)
        request.extensions["timeout"] = timeouts
        validate_url(str(request.url), error_class, deadline=deadline)
        if previous == "https" and request.url.scheme == "http":
            warnings.warn("HTTPS request redirected to HTTP", RuntimeWarning, stacklevel=2)
        previous = request.url.scheme

    return guard


def _remaining(deadline: float, timeout: float | None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded("Network deadline exceeded")
    return remaining if timeout is None else min(timeout, remaining)


class _DeadlineStream(httpcore.NetworkStream):
    """A socket stream whose every read and write ends by the overall deadline.

    httpcore reads its read timeout once per response, so a server trickling
    bytes just inside that timeout could otherwise stretch one response far
    past the deadline. Here each blocking call gets only the time that is left.
    """

    def __init__(self, stream: httpcore.NetworkStream, deadline: float) -> None:
        self._stream = stream
        self._deadline = deadline

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._stream.read(max_bytes, _remaining(self._deadline, timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._stream.write(buffer, _remaining(self._deadline, timeout))

    def close(self) -> None:
        self._stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None) -> httpcore.NetworkStream:
        upgraded = self._stream.start_tls(
            ssl_context, server_hostname, _remaining(self._deadline, timeout)
        )
        return _DeadlineStream(upgraded, self._deadline)

    def get_extra_info(self, info: str):
        return self._stream.get_extra_info(info)


class _DeadlineBackend(httpcore.NetworkBackend):
    """Hand out :class:`_DeadlineStream` connections bounded by one deadline."""

    def __init__(self, backend: httpcore.NetworkBackend, deadline: float) -> None:
        self._backend = backend
        self._deadline = deadline

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        stream = self._backend.connect_tcp(
            host, port, _remaining(self._deadline, timeout), local_address, socket_options
        )
        return _DeadlineStream(stream, self._deadline)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):  # pragma: no cover
        raise ValueError("Refusing a Unix-socket network connection")

    def sleep(self, seconds: float) -> None:  # pragma: no cover - httpcore retries only
        self._backend.sleep(seconds)


class PublicTransport(httpx.HTTPTransport):
    """Connect to a validated IP while retaining the original Host and TLS name.

    Pinning the resolved address prevents a second DNS lookup from rebinding a
    previously public hostname to a private address between validation and I/O.
    With a ``deadline``, DNS resolution and every socket operation also end by
    that ``time.monotonic`` instant, not merely each request or chunk boundary.
    """

    def __init__(self, *args, deadline: float | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._deadline = deadline
        if deadline is not None:
            # httpx builds its httpcore pool without a backend argument; wrap the
            # backend it chose. tests/test_hardening.py pins this assumption.
            pool = self._pool
            assert isinstance(pool, httpcore.ConnectionPool)  # no proxy: trust_env is off
            pool._network_backend = _DeadlineBackend(pool._network_backend, deadline)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = resolve_addresses(host, port, self._deadline)
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise ValueError(f"Refusing non-public network address: {host}")
        extensions = {**request.extensions, "sni_hostname": host}
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return super().handle_request(pinned)
