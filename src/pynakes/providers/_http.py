"""Shared HTTP and deterministic-cache helpers for provider clients."""

from __future__ import annotations

import email.utils
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as _UrllibRequest

import httpx

from pynakes import __version__
from pynakes.provider_cache import open_cache

USER_AGENT = f"pynakes/{__version__} (+https://github.com/maiani/pynakes)"

DownloadProgress = Callable[[int, int | None], None]

# Default read timeout. Generous rather than snappy: a provider under load
# (arXiv's Atom API is the usual one) answers slowly long before it answers not
# at all, and a timeout here costs the user a whole import.
DEFAULT_TIMEOUT = 30.0

# Statuses worth trying again. 429 is the interesting one — it is a request to
# slow down, not a refusal, and providers pair it with ``Retry-After``.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Total attempts per request, and the deterministic backoff between them.
# No jitter: core behavior stays reproducible, and a single client spacing its
# own retries has no thundering herd to spread out.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 4.0)
MAX_RETRY_AFTER = 30.0


class _Transient(Exception):
    """Internal signal: this attempt failed in a way worth repeating."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value: str | None) -> float | None:
    """Interpret a ``Retry-After`` header as a delay in seconds.

    Accepts both documented forms — a delay in seconds, and an HTTP-date — and
    returns ``None`` for anything unparseable so the caller falls back to its
    own backoff. Clamped to :data:`MAX_RETRY_AFTER`: a provider asking for an
    hour is telling us to give up, not to block the run for an hour.
    """
    if not value:
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        seconds = parsed.timestamp() - time.time()
    if seconds <= 0:
        return 0.0
    return min(seconds, MAX_RETRY_AFTER)


def _retry_delay(attempt: int, retry_after: float | None) -> float:
    """Seconds to wait before attempt ``attempt`` + 1, honoring ``Retry-After``."""
    if retry_after is not None:
        return retry_after
    index = min(attempt, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def _with_retry(
    attempt_once: Callable[[], bytes],
    *,
    error_class: type[Exception],
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Run ``attempt_once``, repeating it while it raises :class:`_Transient`.

    A throttle or a read timeout is a temporary condition, so surfacing the
    first one as a hard error turns a provider's "slow down" into what looks to
    the user like a permanent failure. After :data:`MAX_ATTEMPTS` the last
    message is raised as ``error_class``, unchanged, so the final error still
    says what actually went wrong.
    """
    last: _Transient | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return attempt_once()
        except _Transient as exc:
            last = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
            sleep(_retry_delay(attempt, exc.retry_after))
    raise error_class(str(last))


class ProviderFetchError(Exception):
    """Raised when an external provider response cannot be fetched or parsed."""


def iter_strings(value: object) -> list[str]:
    """Walk a JSON-like structure and return every string leaf.

    Handles nested dicts and lists recursively; used to search provider
    responses for arXiv identifiers and other embedded references.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for nested in value.values():
            strings.extend(iter_strings(nested))
        return strings
    if isinstance(value, list):
        strings = []
        for nested in value:
            strings.extend(iter_strings(nested))
        return strings
    return []


def fetch_bytes(
    url: str,
    *,
    accept: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    error_class: type[Exception] = ProviderFetchError,
    label: str | None = None,
    opener: Callable[..., object] | None = None,
    progress: DownloadProgress | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Fetch ``url`` and return raw response bytes.

    Low-level byte transport shared by provider clients that retrieve non-JSON
    payloads (BibTeX, Atom XML, PDFs, source archives). ``accept`` sets the
    ``Accept`` header when provided. ``label`` replaces the URL in error messages
    (useful for human-readable identifiers like DOIs). Raises ``error_class`` for
    HTTP and network errors so callers get domain-specific exceptions.

    Throttles (HTTP 429), transient server errors, and read timeouts are retried
    with backoff before the error is raised; ``sleep`` is the test seam for
    that wait.
    """
    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if accept is not None:
        headers["Accept"] = accept
    display = label or url

    if opener is None:

        def attempt() -> bytes:
            return _fetch_bytes_httpx(
                url,
                headers=headers,
                timeout=timeout,
                error_class=error_class,
                display=display,
                progress=progress,
            )
    else:

        def attempt() -> bytes:
            return _fetch_bytes_urllib(
                url,
                headers=headers,
                timeout=timeout,
                error_class=error_class,
                display=display,
                opener=opener,
                progress=progress,
            )

    return _with_retry(attempt, error_class=error_class, sleep=sleep)


def _fetch_bytes_urllib(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    error_class: type[Exception],
    display: str,
    opener: Callable[..., object],
    progress: DownloadProgress | None,
) -> bytes:
    request = _UrllibRequest(url, headers=headers)
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[arg-type]
            data = response.read()
    except HTTPError as exc:
        message = f"Server returned HTTP {exc.code} for {display}"
        if exc.code in RETRY_STATUSES:
            retry_after = _parse_retry_after((exc.headers or {}).get("Retry-After"))
            raise _Transient(message, retry_after) from exc
        raise error_class(message) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise _Transient(f"Network error fetching {display}: {reason}") from exc
    except OSError as exc:
        raise _Transient(f"Network error fetching {display}: {exc}") from exc
    if progress is not None:
        progress(len(data), len(data))
    return data


def _fetch_bytes_httpx(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    error_class: type[Exception],
    display: str,
    progress: DownloadProgress | None,
) -> bytes:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            with client.stream("GET", url) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    message = f"Server returned HTTP {status} for {display}"
                    if status in RETRY_STATUSES:
                        retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
                        raise _Transient(message, retry_after) from exc
                    raise error_class(message) from exc
                total = _content_length(response)
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    if progress is not None:
                        progress(len(chunk), total)
                return b"".join(chunks)
    except _Transient:
        raise
    except httpx.HTTPError as exc:
        raise _Transient(f"Network error fetching {display}: {exc}") from exc


def _content_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def fetch_text(
    url: str,
    *,
    accept: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    error_class: type[Exception] = ProviderFetchError,
    label: str | None = None,
    opener: Callable[..., object] | None = None,
) -> str:
    """Fetch ``url`` and return the response decoded as UTF-8 text.

    Thin wrapper around :func:`fetch_bytes` for providers that retrieve
    XML, BibTeX, or other text payloads.
    """
    data = fetch_bytes(
        url, accept=accept, timeout=timeout, error_class=error_class, label=label, opener=opener
    )
    return data.decode("utf-8", errors="replace")


def fetch_json(
    url: str,
    *,
    namespace: str,
    identifier: str,
    provider: str,
    cache_file: str | Path | None = None,
    opener: Callable[..., object] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    headers: Mapping[str, str] | None = None,
) -> dict | None:
    """Fetch a provider JSON object with deterministic cache support."""
    cache = open_cache(cache_file)
    cached = cache.get(namespace, identifier, "json")
    text = cached
    if text is None:
        text = _fetch_text(
            url,
            provider=provider,
            identifier=identifier,
            opener=opener,
            timeout=timeout,
            headers=headers,
        )
        if text is None:
            return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(
            f"{provider} returned invalid JSON for DOI {identifier!r}: {exc}"
        ) from exc
    if cached is None:
        cache.put(namespace, identifier, "json", text)
    return data if isinstance(data, dict) else None


def _fetch_text(
    url: str,
    *,
    provider: str,
    identifier: str,
    opener: Callable[..., object] | None,
    timeout: float,
    headers: Mapping[str, str] | None,
) -> str | None:
    if opener is None:
        return _fetch_text_httpx(
            url, provider=provider, identifier=identifier, timeout=timeout, headers=headers
        )
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = _UrllibRequest(url, headers=request_headers)
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[arg-type]
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise ProviderFetchError(
            f"{provider} lookup failed for {identifier!r}: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderFetchError(f"{provider} lookup failed for {identifier!r}: {reason}") from exc


def _fetch_text_httpx(
    url: str,
    *,
    provider: str,
    identifier: str,
    timeout: float,
    headers: Mapping[str, str] | None,
) -> str | None:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers=request_headers
        ) as client:
            response = client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise ProviderFetchError(
            f"{provider} lookup failed for {identifier!r}: HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderFetchError(f"{provider} lookup failed for {identifier!r}: {exc}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderFetchError(
            f"{provider} lookup failed for DOI {identifier!r}: {reason}"
        ) from exc
