"""Network destination policy shared by metadata and material requests."""

import ipaddress
import socket
import time
import warnings
from urllib.parse import urlsplit

import httpx

DEFAULT_DEADLINE = 120.0
MAX_METADATA_BYTES = 8 * 1024 * 1024


def resolve_addresses(host: str, port: int) -> list[str]:
    """Resolve all addresses, so a mixed public/private result is refused."""
    return [str(row[4][0]) for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def validate_url(url: str, error_class: type[Exception], *, resolve: bool = True) -> None:
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
        addresses = (
            resolve_addresses(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            if resolve
            else []
        )
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
        validate_url(str(request.url), error_class)
        if previous == "https" and request.url.scheme == "http":
            warnings.warn("HTTPS request redirected to HTTP", RuntimeWarning, stacklevel=2)
        previous = request.url.scheme

    return guard


class PublicTransport(httpx.HTTPTransport):
    """Connect to a validated IP while retaining the original Host and TLS name.

    Pinning the resolved address prevents a second DNS lookup from rebinding a
    previously public hostname to a private address between validation and I/O.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = resolve_addresses(host, port)
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
