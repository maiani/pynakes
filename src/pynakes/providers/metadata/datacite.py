"""DataCite metadata provider helpers.

DataCite mints DOIs on behalf of member organizations that publish research
data, software, and other non-article outputs — Dryad, Figshare, and
Dataverse among them. Zenodo is also a DataCite member but already has its
own record-oriented client (:mod:`pynakes.providers.repositories.zenodo`), so
this module is aimed at the many other members whose content-negotiated
BibTeX from ``doi.org`` is often thin, generic, or missing creator and
resource-type detail that DataCite's own JSON:API record carries directly.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import fetch_json
from pynakes.providers.metadata._json_service import json_metadata
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.datacite.org/dois"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "DataCite"


def normalize_identifier(identifier: str) -> str:
    """Normalize the DOI a DataCite import is addressed by."""
    return normalize_doi(identifier)


def request_url(identifier: str) -> str:
    """Return the DataCite REST API URL that answers with the DOI's JSON:API record."""
    return f"{API_URL}/{quote(normalize_identifier(identifier), safe='/')}"


def _attributes(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    attributes = data.get("attributes")
    return attributes if isinstance(attributes, dict) else None


def fetch_doi_record(doi: str) -> dict | None:
    """Fetch a DataCite DOI's raw JSON:API payload, public and unauthenticated."""
    normalized = normalize_identifier(doi)
    return fetch_json(
        request_url(normalized),
        namespace="datacite",
        identifier=normalized,
        provider=PROVIDER_NAME,
    )


def _fetch_attributes(doi: str) -> dict | None:
    return _attributes(fetch_doi_record(doi))


def metadata_from_record(attributes: dict, identifier: str, dialect: str) -> ReferenceMetadata:
    """Convert a DataCite ``data.attributes`` record into normalized metadata."""
    titles = attributes.get("titles")
    title = ""
    if isinstance(titles, list) and titles and isinstance(titles[0], dict):
        title = clean_text(titles[0].get("title"))
    authors = [
        name for creator in attributes.get("creators") or [] if (name := person_name(creator))
    ]

    fields: dict[str, str] = {}
    if publisher := clean_text(attributes.get("publisher")):
        fields["publisher"] = publisher
    types = attributes.get("types")
    if isinstance(types, dict) and (resource_type := clean_text(types.get("resourceTypeGeneral"))):
        fields["type"] = resource_type

    year = attributes.get("publicationYear")
    published = str(year) if isinstance(year, int) else clean_text(year)
    doi = clean_text(attributes.get("doi")) or identifier
    return repository_metadata(
        provider=PROVIDER_NAME,
        identifier_kind="datacite",
        identifier=identifier,
        dialect=dialect,
        title=title,
        authors=authors,
        published=published,
        url=clean_text(attributes.get("url")),
        doi=doi,
        fields=fields,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a DataCite DOI record."""
    normalized = normalize_identifier(identifier)
    return json_metadata(
        normalized,
        provider=PROVIDER_NAME,
        dialect=dialect,
        fetcher=fetcher,
        fetch_record=_fetch_attributes,
        envelope=_attributes,
        convert=metadata_from_record,
    )
