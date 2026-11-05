"""Offline material URL classification and credential redaction.

Shared by acquisition and Pinax provenance, with no dependency on download
orchestration, provider clients or the filestore.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PREPRINT_HOSTS = ("arxiv.org",)

_SECRET_PARAM = re.compile(
    r"token|key|sig|signature|auth|session|secret|password|passwd|credential|"
    r"expires|policy|hmac|jwt|cookie|ticket",
    re.IGNORECASE,
)

_OPAQUE_VALUE = re.compile(r"^[A-Za-z0-9_\-.~+/=%]{32,}$")


def is_preprint_host(url: str | None) -> bool:
    """Return whether *url* is served by a preprint repository (see :data:`PREPRINT_HOSTS`)."""
    if not url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == known or host.endswith(f".{known}") for known in PREPRINT_HOSTS)


def redact_url(url: str | None) -> str | None:
    """Return *url* without userinfo, fragment, or query parameters that look secret."""
    if url is None:
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return None
    netloc = host if ":" not in host else f"[{host}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    kept = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _SECRET_PARAM.search(name) and not _OPAQUE_VALUE.match(value)
    ]
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(kept), ""))
