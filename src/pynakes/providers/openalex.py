"""OpenAlex provider helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import arxiv_id_from_text, normalize_doi
from pynakes.providers._http import fetch_json

API_URL = "https://api.openalex.org/works/doi:"


def fetch_work_by_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch an OpenAlex work by DOI, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    url = f"{API_URL}{quote(normalized, safe='')}"
    return fetch_json(
        url,
        namespace="openalex",
        identifier=normalized,
        provider="OpenAlex",
        cache_dir=cache_dir,
        opener=urlopen,
    )


def oa_pdf_url_for_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via OpenAlex, or ``None``."""
    work = fetch_work_by_doi(doi, cache_dir=cache_dir, urlopen=urlopen)
    if work is None:
        return None
    return oa_pdf_url_from_work(work)


def arxiv_id_from_work(work: dict) -> str | None:
    """Return the first arXiv id encoded in an OpenAlex work's locations."""
    for location in _locations(work):
        for value in _iter_strings(location):
            arxiv_id = arxiv_id_from_text(value)
            if arxiv_id:
                return arxiv_id
    return None


def oa_pdf_url_from_work(work: dict) -> str | None:
    """Return OpenAlex's best open-access PDF URL for a work, if any."""
    best_oa = work.get("best_oa_location")
    if not isinstance(best_oa, dict):
        return None

    pdf_url = best_oa.get("pdf_url")
    if not isinstance(pdf_url, str) or not pdf_url.strip():
        return None
    return pdf_url.strip()


def _locations(work: dict) -> list[dict]:
    locations: list[dict] = []
    for field_name in ("primary_location", "best_oa_location"):
        location = work.get(field_name)
        if isinstance(location, dict):
            locations.append(location)
    raw_locations = work.get("locations")
    if isinstance(raw_locations, list):
        locations.extend(location for location in raw_locations if isinstance(location, dict))
    return locations


def _iter_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for nested in value.values():
            strings.extend(_iter_strings(nested))
        return strings
    if isinstance(value, list):
        strings = []
        for nested in value:
            strings.extend(_iter_strings(nested))
        return strings
    return []
