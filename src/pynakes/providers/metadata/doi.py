"""DOI content-negotiation metadata provider."""

from __future__ import annotations

from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

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


def parse_bibtex(text: str, doi: str | None = None) -> ReferenceMetadata:
    """Normalize provider BibTeX into a shared metadata record."""
    try:
        entries = parse_bib(text).entries.values()
    except ParseError as exc:
        raise ProviderFetchError(f"Provider returned invalid BibTeX: {exc.message}") from exc
    if not entries:
        raise ProviderFetchError("Provider returned no BibTeX entries")

    entry = entries[0]
    fields = dict(entry.fields)
    field_expressions = dict(entry.field_expressions)
    identifiers: dict[str, str] = {}
    raw_doi = doi or fields.get("doi")
    if raw_doi:
        try:
            normalized = normalize_doi(raw_doi)
        except ValueError:
            normalized = None
        if normalized is not None:
            if fields.get("doi") != normalized:
                field_expressions["doi"] = f"{{{normalized}}}"
            fields["doi"] = normalized
            identifiers["doi"] = normalized

    return ReferenceMetadata(
        provider="doi.org",
        entry_type=entry.type,
        fields=fields,
        field_expressions=field_expressions,
        identifiers=identifiers,
        provider_key=entry.key,
    )


def fetch_metadata(doi: str, timeout: float = 15.0) -> ReferenceMetadata:
    """Fetch and normalize DOI metadata."""
    normalized = normalize_doi(doi)
    return parse_bibtex(fetch_bibtex(normalized, timeout=timeout), normalized)
