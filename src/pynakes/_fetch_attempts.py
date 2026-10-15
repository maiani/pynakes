"""Download attempts behind ``asset fetch``: candidate URLs and their diagnostics.

Not public API. :mod:`pynakes.fetch` uses this module to decide which URLs to
request for one published PDF, in which order, and to describe each request it
made — the URL asked for, where redirects ended, the HTTP status, and the
content type — so a skip or a failure can say what actually happened.

A recorded attempt never carries credentials: userinfo, query parameters that
look like tokens or keys, and fragments are removed from every URL, and no
header, cookie, or response body is kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

#: An attempt's outcome: the bytes were a PDF, a response that was not one, an
#: HTTP error status, or a failure before any status (DNS, TLS, timeout, policy).
ATTEMPT_OUTCOMES = ("pdf", "not_pdf", "http_error", "network_error")

#: The step an attempt belongs to: finding a PDF link, or downloading the PDF.
ATTEMPT_STAGES = ("resolve", "download")

# APS article DOIs read ``10.1103/<JournalPrefix>.<volume>.<article>``. The
# canonical PDF lives under the journal's short code on journals.aps.org; the
# legacy ``link.aps.org`` redirector and plain-HTTP links to it are refused or
# answered with HTML by the publisher's edge often enough to matter.
APS_JOURNAL_CODES: dict[str, str] = {
    "physrev": "pr",
    "physrevlett": "prl",
    "physrevx": "prx",
    "physreva": "pra",
    "physrevb": "prb",
    "physrevc": "prc",
    "physrevd": "prd",
    "physreve": "pre",
    "physrevresearch": "prresearch",
    "physrevapplied": "prapplied",
    "physrevmaterials": "prmaterials",
    "physrevfluids": "prfluids",
    "physrevaccelbeams": "prab",
    "physrevstab": "prab",
    "physrevphyseducres": "prper",
    "physrevstper": "prper",
    "physrevseriesi": "pri",
    "revmodphys": "rmp",
    "prxquantum": "prxquantum",
    "prxenergy": "prxenergy",
    "prxlife": "prxlife",
    "physicsphysiquefizika": "ppf",
}

# DOI identity is case-insensitive, but the journals.aps.org PDF path is not:
# ``/prb/pdf/10.1103/physrevb.1.1`` is a 404 where ``.../PhysRevB.1.1`` serves
# the article. The canonical spelling of each journal prefix, by its lowercase.
APS_CANONICAL_PREFIXES: dict[str, str] = {
    name.lower(): name
    for name in (
        "PhysRev",
        "PhysRevLett",
        "PhysRevX",
        "PhysRevA",
        "PhysRevB",
        "PhysRevC",
        "PhysRevD",
        "PhysRevE",
        "PhysRevResearch",
        "PhysRevApplied",
        "PhysRevMaterials",
        "PhysRevFluids",
        "PhysRevAccelBeams",
        "PhysRevSTAB",
        "PhysRevPhysEducRes",
        "PhysRevSTPER",
        "PhysRevSeriesI",
        "RevModPhys",
        "PRXQuantum",
        "PRXEnergy",
        "PRXLife",
        "PhysicsPhysiqueFizika",
    )
}

_APS_DOI = re.compile(r"^10\.1103/([A-Za-z]+)(\..+)$", re.IGNORECASE)

# Hosts that serve preprints, never a version of record: a PDF fetched from one
# of these is a preprint whatever identifier led to it.
PREPRINT_HOSTS = ("arxiv.org",)

# Statuses for which trying the same request later can succeed.
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

# Query parameter names that carry secrets in publisher and CDN links.
_SECRET_PARAM = re.compile(
    r"token|key|sig|signature|auth|session|secret|password|passwd|credential|"
    r"expires|policy|hmac|jwt|cookie|ticket",
    re.IGNORECASE,
)
# An opaque value long enough to be a bearer token, whatever its name.
_OPAQUE_VALUE = re.compile(r"^[A-Za-z0-9_\-.~+/=%]{32,}$")
_HTTP_STATUS = re.compile(r"\bHTTP (\d{3})\b")


class DiagnosedFetchError(Exception):
    """A material download failure that records the requests behind it.

    ``attempts`` holds one redacted record per request made (see
    :func:`attempt_record`); ``artifact`` names the material that failed when
    the raiser knows it.
    """

    def __init__(
        self,
        message: str = "",
        *,
        attempts: Iterable[dict] = (),
        artifact: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts: tuple[dict, ...] = tuple(attempts)
        self.artifact = artifact


def aps_pdf_url(doi: str) -> str | None:
    """Return the canonical ``https://journals.aps.org/<code>/pdf/<doi>`` URL, or ``None``.

    ``None`` when *doi* is not an APS article DOI whose journal prefix is
    known — including APS's newer opaque DOIs, which name no journal.
    """
    canonical = canonical_aps_doi(doi)
    if canonical is None:
        return None
    match = _APS_DOI.match(canonical)
    assert match is not None
    code = APS_JOURNAL_CODES[match.group(1).lower()]
    return f"https://journals.aps.org/{code}/pdf/{quote(canonical, safe='/')}"


def canonical_aps_doi(doi: str) -> str | None:
    """Return an APS article DOI with its journal prefix in APS's own spelling.

    ``10.1103/physrevb.1.1`` becomes ``10.1103/PhysRevB.1.1``. ``None`` when
    *doi* is not an APS DOI whose journal prefix is known.
    """
    match = _APS_DOI.match(doi.strip())
    if match is None:
        return None
    prefix = APS_CANONICAL_PREFIXES.get(match.group(1).lower())
    if prefix is None or match.group(1).lower() not in APS_JOURNAL_CODES:
        return None
    return f"10.1103/{prefix}{match.group(2)}"


def is_preprint_host(url: str | None) -> bool:
    """Return whether *url* is served by a preprint repository (see :data:`PREPRINT_HOSTS`)."""
    if not url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == known or host.endswith(f".{known}") for known in PREPRINT_HOSTS)


def _is_aps_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host == "aps.org" or host.endswith(".aps.org")


def candidate_urls(url: str, doi: str | None) -> list[str]:
    """Return the URLs to try, in order, for one resolved published-PDF URL.

    An APS-hosted URL for an APS article is preceded by the article's canonical
    HTTPS PDF URL. A plain-HTTP URL is preceded by its HTTPS form; the original
    stays last, so a host that does not serve HTTPS is still reached. Any other
    URL is returned unchanged, alone.
    """
    urls: list[str] = []
    if doi is not None and _is_aps_host(url):
        canonical = aps_pdf_url(doi)
        if canonical is not None:
            urls.append(canonical)
    if urlsplit(url).scheme.lower() == "http":
        urls.append("https" + url[len("http") :])
    urls.append(url)
    return list(dict.fromkeys(urls))


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


def attempt_record(url: str, info: dict | None, outcome: str, *, stage: str = "download") -> dict:
    """Return the redacted record of one request: what was asked for, and what came back.

    *info* is what the transport observed (``final_url``, ``status``,
    ``content_type``); any of them is ``None`` when the request never got that
    far, or when an injected fetcher reported none. *stage* is one of
    :data:`ATTEMPT_STAGES`: ``resolve`` for a request that looked for a PDF
    link (a DOI landing page, an open-access index), ``download`` for one that
    asked for the PDF itself. ``retryable`` says whether the same request may
    succeed later (a throttle, a server error, a network failure) as opposed to
    an answer that will not change by waiting (401, 403, 404, not a PDF).
    """
    info = info or {}
    content_type = info.get("content_type")
    if isinstance(content_type, str):
        content_type = content_type.split(";", 1)[0].strip().lower() or None
    else:
        content_type = None
    status = info.get("status")
    return {
        "url": redact_url(url),
        "final_url": redact_url(info.get("final_url")),
        "status": status if isinstance(status, int) else None,
        "content_type": content_type,
        "outcome": outcome,
        "stage": stage,
        "retryable": _retryable(outcome, status if isinstance(status, int) else None),
    }


def _retryable(outcome: str, status: int | None) -> bool:
    if outcome == "network_error":
        return True
    if outcome == "http_error":
        return status in _RETRYABLE_STATUSES
    return False


def status_from_message(message: str) -> int | None:
    """Return the HTTP status a transport error message names, if any."""
    match = _HTTP_STATUS.search(message)
    return int(match.group(1)) if match else None


def describe_attempts(attempts: Iterable[dict]) -> str:
    """Return a short human summary of *attempts*: host, status, and content type each."""
    parts: list[str] = []
    for attempt in attempts:
        url = attempt.get("final_url") or attempt.get("url") or ""
        host = urlsplit(url).hostname or url
        detail = [f"HTTP {attempt['status']}"] if attempt.get("status") else []
        if attempt.get("content_type"):
            detail.append(str(attempt["content_type"]))
        if not detail:
            detail.append(str(attempt.get("outcome") or "no response").replace("_", " "))
        parts.append(f"{host} ({', '.join(detail)})")
    return "; ".join(parts)


def describe_content(data: bytes) -> str:
    """Return a short description of ``data`` for error messages."""
    if not data:
        return "empty response"
    if data.startswith(b"<") or data.startswith(b"<!") or data.startswith(b"<?"):
        return f"HTML ({len(data)} bytes)"
    return f"{len(data)} bytes"


def non_pdf_reason(data: bytes, access: str = "institutional") -> str:
    description = describe_content(data)
    if data.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        if access == "open":
            return f"publisher URL served an HTML page ({len(data)} bytes), not a PDF"
        return f"authentication required or publisher returned HTML ({len(data)} bytes)"
    return f"publisher URL returned {description}, not a PDF"


def access_error_reason(exc: Exception) -> str | None:
    message = str(exc)
    if "HTTP 401" in message:
        return "authentication required for publisher PDF"
    if "HTTP 403" in message:
        return "institutional access was not accepted by the publisher"
    return None


def error_outcome(exc: Exception, info: dict) -> str:
    """Classify a failed request: an HTTP error status, or no usable response at all."""
    status = info.get("status") or status_from_message(str(exc))
    return "http_error" if isinstance(status, int) and status >= 400 else "network_error"
