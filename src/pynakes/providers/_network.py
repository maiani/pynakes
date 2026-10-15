"""Network destination policy shared by metadata and material requests.

The policy — limits, address resolution, and URL validation — needs no HTTP
client, so importing it costs nothing. The httpx transport that enforces it on
every connection lives in :mod:`pynakes.providers._transport`, loaded only
when a request is actually made.
"""

import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit

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
