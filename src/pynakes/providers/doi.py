"""DOI provider URL helpers."""

from __future__ import annotations

from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._http import fetch_text

BASE_URL = "https://doi.org"


def content_url(doi: str) -> str:
    """Return the DOI content-negotiation URL for ``doi``."""
    normalized = normalize_doi(doi)
    return f"{BASE_URL}/{quote(normalized, safe='/')}"


def fetch_bibtex(doi: str, timeout: float = 15.0) -> str:
    """Fetch BibTeX metadata for ``doi`` via DOI content negotiation.

    Raises :class:`~pynakes.providers._http.ProviderFetchError` on HTTP or
    network failure.
    """
    normalized = normalize_doi(doi)
    return fetch_text(
        content_url(normalized),
        accept="application/x-bibtex",
        timeout=timeout,
        label=normalized,
    )
