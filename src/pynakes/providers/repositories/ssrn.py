"""SSRN working-paper import through its canonical DOI."""

from __future__ import annotations

from collections.abc import Callable

from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.records import ReferenceMetadata

RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize a numeric SSRN abstract id."""
    value = identifier.strip()
    if not value.isdigit():
        raise ValueError(f"Malformed SSRN abstract id: {identifier!r}")
    return value


def record_doi(identifier: str) -> str:
    """Return the DOI assigned to an SSRN abstract id."""
    return f"10.2139/ssrn.{normalize_identifier(identifier)}"


def record_url(identifier: str) -> str:
    """Return the canonical SSRN abstract URL."""
    return f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={normalize_identifier(identifier)}"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an SSRN working paper."""
    del dialect
    normalized = normalize_identifier(identifier)
    doi = record_doi(normalized)
    text = fetcher(normalized) if fetcher is not None else doi_provider.fetch_bibtex(doi)
    metadata = doi_provider.parse_bibtex(text, doi)
    metadata.provider = "SSRN"
    metadata.fields["ssrn"] = normalized
    metadata.fields.setdefault("url", record_url(normalized))
    metadata.identifiers["ssrn"] = normalized
    metadata.identifiers["doi"] = doi
    return metadata
