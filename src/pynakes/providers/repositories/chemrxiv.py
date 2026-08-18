"""ChemRxiv metadata import through the Cambridge Open Engage public API."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://www.cambridge.org/engage/coe/public-api/v1/items"
RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize a ChemRxiv Open Engage item id."""
    value = identifier.strip()
    if not value or not value.replace("-", "").isalnum():
        raise ValueError(f"Malformed ChemRxiv record id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical ChemRxiv landing page."""
    normalized = normalize_identifier(identifier)
    return f"https://www.cambridge.org/engage/chemrxiv/article-details/{normalized}"


def parse_json(text: str, identifier: str, *, dialect: str) -> ReferenceMetadata:
    """Parse a Cambridge Open Engage item response."""
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"ChemRxiv returned invalid JSON for {identifier!r}") from exc
    if not isinstance(record, dict):
        raise ProviderFetchError(f"ChemRxiv returned no entry for {identifier!r}")
    authors = [name for author in record.get("authors") or [] if (name := person_name(author))]
    doi = clean_text(record.get("doi"))
    fields = {"chemrxiv": identifier, "archivePrefix": "ChemRxiv"}
    content_type = record.get("contentType")
    if isinstance(content_type, dict):
        if value := clean_text(content_type.get("name")):
            fields["type"] = value
    categories = record.get("categories")
    if isinstance(categories, list):
        names = [
            name
            for category in categories
            if isinstance(category, dict) and (name := clean_text(category.get("name")))
        ]
        if names:
            fields["keywords"] = ", ".join(names)
    return repository_metadata(
        provider="ChemRxiv",
        identifier_kind="chemrxiv",
        identifier=identifier,
        dialect=dialect,
        title=clean_text(record.get("title")),
        authors=authors,
        published=clean_text(record.get("publishedDate") or record.get("statusDate")),
        abstract=clean_text(record.get("abstract")),
        url=record_url(identifier),
        doi=doi,
        fields=fields,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a ChemRxiv record."""
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            f"{API_URL}/{quote(normalized)}",
            accept="application/json",
            label=f"ChemRxiv {normalized}",
        )
    )
    return parse_json(text, normalized, dialect=dialect)
