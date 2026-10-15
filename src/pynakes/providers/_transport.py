"""The httpx transport that enforces the network policy on every connection.

Separate from :mod:`pynakes.providers._network` so that only a command that
actually makes a request pays for importing httpx.
"""

import ipaddress
import time
import warnings

import httpcore
import httpx

from pynakes.providers import _network
from pynakes.providers._network import DeadlineExceeded, validate_url

__all__ = ["PublicTransport", "request_guard"]


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
        addresses = _network.resolve_addresses(host, port, self._deadline)
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
