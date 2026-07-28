"""Elsevier ScienceDirect import through a PII-to-DOI resolution step.

ScienceDirect article URLs carry a Publisher Item Identifier rather than a DOI,
so this client resolves the PII to its DOI through the Crossref
``alternative-id`` index and then imports the work by DOI. The PII is retained
as identifier evidence.
"""

from __future__ import annotations

from collections.abc import Callable

from pynakes._identifiers import normalize_pii
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import crossref
from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.metadata._bibtex_service import bibtex_metadata
from pynakes.providers.records import ReferenceMetadata

RawFetcher = Callable[[str], str]
DOIResolver = Callable[[str], str | None]

PROVIDER_NAME = "Elsevier ScienceDirect"


def normalize_identifier(identifier: str) -> str:
    """Normalize an Elsevier PII to its compact, unpunctuated form."""
    return normalize_pii(identifier)


def record_url(identifier: str) -> str:
    """Return the canonical ScienceDirect article URL for a PII."""
    return f"https://www.sciencedirect.com/science/article/pii/{normalize_identifier(identifier)}"


def resolve_doi(identifier: str, *, resolver: DOIResolver | None = None) -> str:
    """Resolve a PII to its DOI, raising when no registered work matches."""
    normalized = normalize_identifier(identifier)
    resolve = resolver if resolver is not None else crossref.fetch_doi_by_alternative_id
    doi = resolve(normalized)
    if not doi:
        raise ProviderFetchError(
            f"No DOI is registered for Elsevier PII {normalized!r}; "
            "import the article by DOI instead"
        )
    return doi


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
    doi_resolver: DOIResolver | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a ScienceDirect article addressed by PII."""
    del dialect
    normalized = normalize_identifier(identifier)
    doi = resolve_doi(normalized, resolver=doi_resolver)
    text = fetcher(doi) if fetcher is not None else doi_provider.fetch_bibtex(doi)
    return bibtex_metadata(
        text,
        provider=PROVIDER_NAME,
        identifier_kind="pii",
        identifier=normalized,
        doi=doi,
        url=record_url(normalized),
    )
