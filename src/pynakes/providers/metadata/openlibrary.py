"""Open Library book metadata client for ISBN import.

Books are addressed by ISBN-10 or ISBN-13 and resolved through the Open Library
Books API, which returns resolved contributor names, publisher, and edition
data. Responses are normalized into a ``@book`` record.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

from pynakes._identifiers import normalize_isbn
from pynakes.providers._common import add_date_fields, clean_text
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://openlibrary.org/api/books"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "Open Library"


def normalize_identifier(identifier: str) -> str:
    """Normalize an ISBN-10 or ISBN-13 to its compact form."""
    return normalize_isbn(identifier)


def record_url(identifier: str) -> str:
    """Return the canonical Open Library ISBN URL."""
    return f"https://openlibrary.org/isbn/{normalize_identifier(identifier)}"


def request_url(identifier: str) -> str:
    """Return the Open Library Books API URL for one ISBN."""
    bibkey = f"ISBN:{normalize_identifier(identifier)}"
    return f"{API_URL}?bibkeys={quote(bibkey, safe='')}&format=json&jscmd=data"


def parse_json(text: str, identifier: str, *, dialect: str) -> ReferenceMetadata:
    """Parse an Open Library Books API response for one ISBN."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(
            f"Open Library returned invalid JSON for ISBN {identifier!r}"
        ) from exc
    record = data.get(f"ISBN:{identifier}") if isinstance(data, dict) else None
    if not isinstance(record, dict) or not record:
        raise ProviderFetchError(f"Open Library has no record for ISBN {identifier!r}")

    biblatex = dialect.lower() == "biblatex"
    title = clean_text(record.get("title"))
    if not title:
        raise ProviderFetchError(f"Open Library returned no title for ISBN {identifier!r}")
    subtitle = clean_text(record.get("subtitle"))
    fields: dict[str, str] = {}
    if subtitle and biblatex:
        fields["title"] = title
        fields["subtitle"] = subtitle
    elif subtitle:
        fields["title"] = f"{title}: {subtitle}"
    else:
        fields["title"] = title

    if authors := _names(record.get("authors")):
        fields["author"] = " and ".join(authors)
    if publishers := _names(record.get("publishers")):
        fields["publisher"] = " and ".join(publishers)
    if places := _names(record.get("publish_places")):
        fields["location" if biblatex else "address"] = places[0]
    add_date_fields(fields, clean_text(record.get("publish_date")), dialect)
    if series := _names(record.get("series")):
        fields["series"] = series[0]
    if edition := clean_text(record.get("edition_name")):
        fields["edition"] = edition
    pages = record.get("number_of_pages")
    if biblatex and isinstance(pages, int) and pages > 0:
        fields["pagetotal"] = str(pages)
    fields["isbn"] = identifier
    fields["url"] = record_url(identifier)

    identifiers = {"isbn": identifier}
    return ReferenceMetadata(
        provider=PROVIDER_NAME,
        entry_type="book",
        fields=fields,
        identifiers=identifiers,
    )


def _names(value: object) -> list[str]:
    """Return display names from Open Library's string or ``{"name": ...}`` lists."""
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, str):
            name = clean_text(item)
        elif isinstance(item, dict):
            name = clean_text(item.get("name"))
        else:
            name = ""
        if name:
            names.append(name)
    return names


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an Open Library book record."""
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            request_url(normalized),
            accept="application/json",
            label=f"Open Library ISBN {normalized}",
        )
    )
    return parse_json(text, normalized, dialect=dialect)
