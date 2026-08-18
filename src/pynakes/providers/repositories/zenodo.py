"""Zenodo record metadata client."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://zenodo.org/api/records"
RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize a numeric Zenodo record id."""
    value = identifier.strip()
    if not value.isdigit():
        raise ValueError(f"Malformed Zenodo record id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return a canonical Zenodo record URL."""
    return f"https://zenodo.org/records/{normalize_identifier(identifier)}"


def parse_json(text: str, identifier: str, *, dialect: str) -> ReferenceMetadata:
    """Parse a Zenodo record response."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"Zenodo returned invalid JSON for {identifier!r}") from exc
    if not isinstance(data, dict):
        raise ProviderFetchError(f"Zenodo returned no entry for {identifier!r}")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    creators = metadata.get("creators") or data.get("creators") or []
    authors = [name for creator in creators if (name := person_name(creator))]
    doi = clean_text(metadata.get("doi") or data.get("doi"))
    fields = {"zenodo": identifier}
    resource_type = metadata.get("resource_type")
    if isinstance(resource_type, dict):
        resource_type = resource_type.get("title") or resource_type.get("type")
    if value := clean_text(resource_type):
        fields["type"] = value
    return repository_metadata(
        provider="Zenodo",
        identifier_kind="zenodo",
        identifier=identifier,
        dialect=dialect,
        title=clean_text(metadata.get("title") or data.get("title")),
        authors=authors,
        published=clean_text(metadata.get("publication_date") or data.get("created")),
        abstract=clean_text(metadata.get("description")),
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
    """Fetch and normalize a Zenodo record."""
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            f"{API_URL}/{quote(normalized)}",
            accept="application/json",
            label=f"Zenodo {normalized}",
        )
    )
    return parse_json(text, normalized, dialect=dialect)
