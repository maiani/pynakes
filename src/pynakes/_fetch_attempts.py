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

_APS_DOI = re.compile(r"^10\.1103/([A-Za-z]+)\.", re.IGNORECASE)

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
    match = _APS_DOI.match(doi.strip())
    if match is None:
        return None
    code = APS_JOURNAL_CODES.get(match.group(1).lower())
    if code is None:
        return None
    return f"https://journals.aps.org/{code}/pdf/{quote(doi.strip(), safe='/')}"


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


def attempt_record(url: str, info: dict | None, outcome: str) -> dict:
    """Return the redacted record of one request: what was asked for, and what came back.

    *info* is what the transport observed (``final_url``, ``status``,
    ``content_type``); any of them is ``None`` when the request never got that
    far, or when an injected fetcher reported none.
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
    }


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
