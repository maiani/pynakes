"""Shared HTTP and deterministic-cache helpers for provider clients."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as _UrllibRequest

import httpx

from pynakes import __version__
from pynakes.provider_cache import open_cache

USER_AGENT = f"pynakes/{__version__} (+https://github.com/maiani/pynakes)"

DownloadProgress = Callable[[int, int | None], None]


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
    timeout: float = 15.0,
    error_class: type[Exception] = ProviderFetchError,
    label: str | None = None,
    opener: Callable[..., object] | None = None,
    progress: DownloadProgress | None = None,
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
    display = label or url
    if opener is None:
        return _fetch_bytes_httpx(
            url,
            headers=headers,
            timeout=timeout,
            error_class=error_class,
            display=display,
            progress=progress,
        )

    request = _UrllibRequest(url, headers=headers)
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[arg-type]
            data = response.read()
    except HTTPError as exc:
        raise error_class(f"Server returned HTTP {exc.code} for {display}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise error_class(f"Network error fetching {display}: {reason}") from exc
    except OSError as exc:
        raise error_class(f"Network error fetching {display}: {exc}") from exc
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
                    raise error_class(
                        f"Server returned HTTP {exc.response.status_code} for {display}"
                    ) from exc
                total = _content_length(response)
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    if progress is not None:
                        progress(len(chunk), total)
                return b"".join(chunks)
    except httpx.HTTPStatusError:
        raise
    except httpx.HTTPError as exc:
        raise error_class(f"Network error fetching {display}: {exc}") from exc


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
    timeout: float = 15.0,
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
    timeout: float = 15.0,
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
