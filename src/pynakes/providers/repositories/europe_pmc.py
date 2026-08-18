"""Europe PMC article metadata client."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._common import person_name, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/article"
RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize ``SOURCE:ID`` Europe PMC identifiers."""
    value = identifier.strip()
    if ":" not in value:
        raise ValueError(f"Malformed Europe PMC identifier: {identifier!r}")
    source, record_id = value.split(":", 1)
    source = source.upper()
    record_id = record_id.strip()
    if not source or not record_id:
        raise ValueError(f"Malformed Europe PMC identifier: {identifier!r}")
    return f"{source}:{record_id}"


def article_url(identifier: str) -> str:
    """Return the Europe PMC landing page."""
    source, record_id = normalize_identifier(identifier).split(":", 1)
    return f"https://europepmc.org/article/{quote(source)}/{quote(record_id)}"


def parse_json(text: str, identifier: str, *, dialect: str) -> ReferenceMetadata:
    """Parse a Europe PMC core JSON response."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"Europe PMC returned invalid JSON for {identifier!r}") from exc
    record = data
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        record = data["result"]
    if isinstance(data, dict) and isinstance(data.get("resultList"), dict):
        results = data["resultList"].get("result") or []
        record = results[0] if results else {}
    if not isinstance(record, dict):
        raise ProviderFetchError(f"Europe PMC returned no entry for {identifier!r}")
    authors: list[str] = []
    author_list = record.get("authorList")
    if isinstance(author_list, dict):
        for author in author_list.get("author") or []:
            if name := person_name(author):
                authors.append(name)
    source, record_id = normalize_identifier(identifier).split(":", 1)
    fields: dict[str, str] = {"europepmc": identifier}
    identifiers = {"europe_pmc": identifier}
    for kind, field in (("pmid", "pmid"), ("pmcid", "pmcid")):
        value = record.get(field)
        if isinstance(value, str) and value:
            fields[kind] = value
            identifiers[kind] = value
    journal_info = record.get("journalInfo")
    if not isinstance(journal_info, dict):
        journal_info = {}
    journal_record = journal_info.get("journal")
    if not isinstance(journal_record, dict):
        journal_record = {}
    journal = record.get("journalTitle") or journal_record.get("title")
    if isinstance(journal, str) and journal:
        fields["journal"] = journal
    for target, value in (
        ("volume", record.get("journalVolume") or journal_info.get("volume")),
        ("number", record.get("issue") or journal_info.get("issue")),
        ("pages", record.get("pageInfo")),
    ):
        if isinstance(value, str) and value:
            fields[target] = value
    doi = record.get("doi") if isinstance(record.get("doi"), str) else ""
    return repository_metadata(
        provider="Europe PMC",
        identifier_kind="europe_pmc",
        identifier=f"{source}:{record_id}",
        dialect=dialect,
        title=str(record.get("title") or ""),
        authors=authors,
        published=str(record.get("firstPublicationDate") or record.get("dateOfCreation") or ""),
        abstract=str(record.get("abstractText") or ""),
        url=article_url(identifier),
        doi=doi,
        entry_type="article",
        fields=fields,
        identifiers=identifiers,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a Europe PMC record."""
    normalized = normalize_identifier(identifier)
    source, record_id = normalized.split(":", 1)
    url = f"{API_URL}/{quote(source)}/{quote(record_id)}?resultType=core&format=json"
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(url, accept="application/json", label=f"Europe PMC {normalized}")
    )
    return parse_json(text, normalized, dialect=dialect)
