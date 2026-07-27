"""Crossref metadata provider helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._http import fetch_json

API_URL = "https://api.crossref.org/works/"


def fetch_work_by_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch a CrossRef work record by DOI, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    url = f"{API_URL}{quote(normalized, safe='')}"
    data = fetch_json(
        url,
        namespace="crossref",
        identifier=normalized,
        provider="CrossRef",
        cache_dir=cache_dir,
        opener=urlopen,
    )
    if data is None:
        return None
    return data.get("message")


def oa_pdf_url_from_work(work: dict) -> str | None:
    """Return the best PDF URL from a CrossRef work, or ``None``.

    Prefers links with ``content-type: application/pdf``.  Falls back to
    similarity-checking links (e.g. APS harvest URLs) that serve PDF even
    when the content-type is unspecified.
    """
    links: list[dict] = work.get("link") or []
    if not links:
        return None

    best: str | None = None
    for link in links:
        url = _clean_url(link.get("URL"))
        if url is None:
            continue
        ct = link.get("content-type", "").lower()
        if ct == "application/pdf":
            return url
        app = link.get("intended-application", "").lower()
        if app == "similarity-checking" and best is None:
            best = url
    return best


def _clean_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def oa_pdf_url_for_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via CrossRef, or ``None``."""
    work = fetch_work_by_doi(doi, cache_dir=cache_dir, urlopen=urlopen)
    if work is None:
        return None
    return oa_pdf_url_from_work(work)
