"""zbMATH Open metadata provider helpers.

zbMATH Open publishes a public, key-free JSON API (``api.zbmath.org/v1``) for
its mathematics reviews database. A record is addressed either by its Zbl
number (the ``NNNN.NNNNN`` accession number, e.g. ``1350.53082``) — the
identifier the mathematics community actually cites — or by its internal DE
(document) number, a bare integer. Both forms resolve to the same record, so
this client accepts either one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._common import clean_text, repository_metadata
from pynakes.providers._http import fetch_json
from pynakes.providers.metadata._json_service import json_metadata
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.zbmath.org/v1"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "zbMATH Open"

_ZBL_RE = re.compile(r"^\d{4}\.\d{5}$")
_DE_RE = re.compile(r"^\d+$")

# Only document types spelled the same way in BibTeX and BibLaTeX are mapped;
# anything else falls back to "misc" rather than guessing per dialect.
_ENTRY_TYPES = {
    "j": "article",
    "b": "book",
}


def is_zbl_number(identifier: str) -> bool:
    """Return whether ``identifier`` is a Zbl accession number (``NNNN.NNNNN``)."""
    return bool(_ZBL_RE.match(identifier.strip()))


def normalize_identifier(identifier: str) -> str:
    """Normalize a Zbl number or a bare internal DE (document) number."""
    value = identifier.strip()
    if _ZBL_RE.match(value) or _DE_RE.match(value):
        return value
    raise ValueError(f"Malformed zbMATH Zbl or DE number: {identifier!r}")


def record_url(identifier: str) -> str:
    """Return the canonical zbMATH record page for a Zbl or DE number."""
    return f"https://zbmath.org/{normalize_identifier(identifier)}"


def request_url(identifier: str) -> str:
    """Return the zbMATH Open API URL that answers with the record's JSON."""
    normalized = normalize_identifier(identifier)
    if is_zbl_number(normalized):
        query = quote(f"an:{normalized}", safe="")
        return f"{API_URL}/document/_search?search_string={query}"
    return f"{API_URL}/document/{normalized}"


def _envelope(payload: object) -> dict | None:
    """Unwrap zbMATH's ``result`` field, which is a list for a search and an object for a lookup."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if isinstance(result, list):
        return result[0] if result and isinstance(result[0], dict) else None
    return result if isinstance(result, dict) else None


def fetch_document_record(
    identifier: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch a zbMATH document record, public and unauthenticated."""
    normalized = normalize_identifier(identifier)
    data = fetch_json(
        request_url(normalized),
        namespace="zbmath",
        identifier=normalized,
        provider=PROVIDER_NAME,
        cache_file=cache_file,
        opener=urlopen,
    )
    return _envelope(data)


def _journal_fields(record: dict) -> dict[str, str]:
    fields: dict[str, str] = {}
    source = record.get("source")
    if not isinstance(source, dict):
        return fields
    series = source.get("series")
    if isinstance(series, list) and series and isinstance(series[0], dict):
        entry = series[0]
        if journal := clean_text(entry.get("title")):
            fields["journal"] = journal
        if volume := clean_text(entry.get("volume")):
            fields["volume"] = volume
        if issue := clean_text(entry.get("issue")):
            fields["number"] = issue
    if pages := clean_text(source.get("pages")):
        fields["pages"] = pages
    return fields


def _doi_from_links(record: dict) -> str:
    for link in record.get("links") or []:
        if isinstance(link, dict) and link.get("type") == "doi":
            candidate = clean_text(link.get("identifier"))
            if candidate:
                try:
                    return normalize_doi(candidate)
                except ValueError:
                    continue
    return ""


def entry_type_from_document_type(value: object) -> str:
    """Map a zbMATH ``document_type.code`` to a BibTeX entry type."""
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str):
            return _ENTRY_TYPES.get(code.lower(), "misc")
    return "misc"


def metadata_from_record(record: dict, identifier: str, dialect: str) -> ReferenceMetadata:
    """Convert a zbMATH document record into normalized metadata."""
    title_field = record.get("title")
    title = clean_text(title_field.get("title")) if isinstance(title_field, dict) else ""

    authors: list[str] = []
    contributors = record.get("contributors")
    if isinstance(contributors, dict):
        for author in contributors.get("authors") or []:
            if isinstance(author, dict) and (name := clean_text(author.get("name"))):
                authors.append(name)

    published = clean_text(record.get("year"))
    return repository_metadata(
        provider=PROVIDER_NAME,
        identifier_kind="zbmath",
        identifier=identifier,
        dialect=dialect,
        title=title,
        authors=authors,
        published=published,
        url=clean_text(record.get("zbmath_url")) or record_url(identifier),
        doi=_doi_from_links(record),
        entry_type=entry_type_from_document_type(record.get("document_type")),
        fields=_journal_fields(record),
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a zbMATH Open document record."""
    normalized = normalize_identifier(identifier)
    return json_metadata(
        normalized,
        provider=PROVIDER_NAME,
        dialect=dialect,
        fetcher=fetcher,
        fetch_record=fetch_document_record,
        envelope=_envelope,
        convert=metadata_from_record,
    )
