"""HAL open-archive metadata client."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._common import clean_text, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.archives-ouvertes.fr/search"
RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize a HAL id, dropping a version suffix."""
    value = identifier.strip().lower()
    value = re.sub(r"v\d+$", "", value)
    if not value or not value.startswith(("hal-", "inria-", "tel-", "pastel-")):
        raise ValueError(f"Malformed HAL identifier: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return a canonical HAL landing page."""
    return f"https://hal.science/{normalize_identifier(identifier)}"


def parse_json(text: str, identifier: str, *, dialect: str) -> ReferenceMetadata:
    """Parse a HAL search API response."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"HAL returned invalid JSON for {identifier!r}") from exc
    response = payload.get("response") if isinstance(payload, dict) else None
    docs = response.get("docs") if isinstance(response, dict) else None
    if not isinstance(docs, list) or not docs or not isinstance(docs[0], dict):
        raise ProviderFetchError(f"HAL returned no entry for {identifier!r}")
    record = docs[0]
    authors = record.get("authFullName_s") or record.get("authFullName_t") or []
    if isinstance(authors, str):
        authors = [authors]
    title = record.get("title_s")
    if isinstance(title, list):
        title = title[0] if title else ""
    abstract = record.get("abstract_s")
    if isinstance(abstract, list):
        abstract = abstract[0] if abstract else ""
    doi = clean_text(record.get("doiId_s"))
    fields = {"halid": identifier}
    journal = clean_text(record.get("journalTitle_s"))
    if journal:
        fields["journal"] = journal
    return repository_metadata(
        provider="HAL",
        identifier_kind="hal",
        identifier=identifier,
        dialect=dialect,
        title=clean_text(title),
        authors=[clean_text(author) for author in authors],
        published=clean_text(record.get("producedDate_s") or record.get("submittedDate_s")),
        abstract=clean_text(abstract),
        url=clean_text(record.get("uri_s")) or record_url(identifier),
        doi=doi,
        fields=fields,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a HAL record."""
    normalized = normalize_identifier(identifier)
    fields = ",".join(
        (
            "halId_s",
            "title_s",
            "authFullName_s",
            "producedDate_s",
            "submittedDate_s",
            "abstract_s",
            "doiId_s",
            "journalTitle_s",
            "uri_s",
        )
    )
    url = f"{API_URL}/?q=halId_s:{quote(normalized)}&fl={fields}&wt=json"
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(url, accept="application/json", label=f"HAL {normalized}")
    )
    return parse_json(text, normalized, dialect=dialect)
