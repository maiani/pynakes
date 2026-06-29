"""Shared HTTP and deterministic-cache helpers for provider clients."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.request import urlopen as _default_urlopen

from pynakes import __version__

USER_AGENT = f"pynakes/{__version__} (mailto:unknown@example.invalid)"


class ProviderFetchError(Exception):
    """Raised when an external provider response cannot be fetched or parsed."""


def cache_path(
    cache_dir: str | Path | None,
    namespace: str,
    identifier: str,
    suffix: str = ".json",
) -> Path | None:
    """Return a deterministic provider cache path, or ``None`` when caching is disabled."""
    if cache_dir is None:
        return None
    digest = hashlib.sha256(identifier.lower().encode("utf-8")).hexdigest()
    return Path(cache_dir) / namespace / f"{digest}{suffix}"


def fetch_bytes(
    url: str,
    *,
    accept: str | None = None,
    timeout: float = 15.0,
    error_class: type[Exception] = ProviderFetchError,
    label: str | None = None,
    opener: Callable[..., object] | None = None,
) -> bytes:
    """Fetch ``url`` and return raw response bytes.

    Low-level byte transport shared by provider clients that retrieve non-JSON
    payloads (BibTeX, Atom XML, PDFs, source archives). ``accept`` sets the
    ``Accept`` header when provided. ``label`` replaces the URL in error messages
    (useful for human-readable identifiers like DOIs). Raises ``error_class`` for
    HTTP and network errors so callers get domain-specific exceptions.
    """
    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if accept is not None:
        headers["Accept"] = accept
    request = Request(url, headers=headers)
    display = label or url
    open_url = opener or _default_urlopen
    try:
        with open_url(request, timeout=timeout) as response:  # type: ignore[arg-type]
            return response.read()
    except HTTPError as exc:
        raise error_class(f"Server returned HTTP {exc.code} for {display}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise error_class(f"Network error fetching {display}: {reason}") from exc


def fetch_json(
    url: str,
    *,
    namespace: str,
    identifier: str,
    provider: str,
    cache_dir: str | Path | None = None,
    opener: Callable[..., object] | None = None,
    timeout: float = 15.0,
) -> dict | None:
    """Fetch a provider JSON object with deterministic cache support."""
    path = cache_path(cache_dir, namespace, identifier, ".json")
    if path is not None and path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = _fetch_text(
            url, provider=provider, identifier=identifier, opener=opener, timeout=timeout
        )
        if text is None:
            return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(
            f"{provider} returned invalid JSON for DOI {identifier!r}: {exc}"
        ) from exc
    if path is not None and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return data if isinstance(data, dict) else None


def _fetch_text(
    url: str,
    *,
    provider: str,
    identifier: str,
    opener: Callable[..., object] | None,
    timeout: float,
) -> str | None:
    open_url = opener or _default_urlopen
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with open_url(request, timeout=timeout) as response:  # type: ignore[arg-type]
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise ProviderFetchError(
            f"{provider} lookup failed for DOI {identifier!r}: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderFetchError(
            f"{provider} lookup failed for DOI {identifier!r}: {reason}"
        ) from exc
