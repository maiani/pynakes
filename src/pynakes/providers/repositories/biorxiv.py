"""bioRxiv and medRxiv metadata client."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories._common import repository_metadata

API_URL = "https://api.biorxiv.org/details"
RawFetcher = Callable[[str], str]


def content_url(identifier: str, *, server: str) -> str:
    """Return a canonical preprint landing page."""
    return f"https://www.{server}.org/content/{quote(identifier, safe='/')}"


def parse_json(
    text: str,
    identifier: str,
    *,
    server: str,
    dialect: str,
) -> ReferenceMetadata:
    """Parse a bioRxiv API response."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"{server} returned invalid JSON for {identifier!r}") from exc
    records = data.get("collection") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records or not isinstance(records[-1], dict):
        raise ProviderFetchError(f"{server} returned no entry for {identifier!r}")
    record = records[-1]
    doi = normalize_doi(str(record.get("doi") or identifier))
    fields = {
        "eprint": doi,
        "archivePrefix": server,
    }
    if dialect.lower() == "biblatex":
        fields = {"eprint": doi, "eprinttype": server}
    category = record.get("category")
    if isinstance(category, str) and category:
        fields["eprintclass"] = category
    published_doi = record.get("published")
    identifiers = {server: doi}
    if isinstance(published_doi, str) and published_doi.startswith("10."):
        identifiers["published_doi"] = published_doi
    return repository_metadata(
        provider=server,
        identifier_kind=server,
        identifier=doi,
        dialect=dialect,
        title=str(record.get("title") or ""),
        authors=[part.strip() for part in str(record.get("authors") or "").split(";")],
        published=str(record.get("date") or ""),
        abstract=str(record.get("abstract") or ""),
        url=content_url(doi, server=server),
        doi=doi,
        fields=fields,
        identifiers=identifiers,
    )


def fetch_metadata(
    identifier: str,
    *,
    server: str,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a bioRxiv or medRxiv manuscript."""
    normalized = normalize_doi(identifier)
    url = f"{API_URL}/{server}/{quote(normalized, safe='/')}"
    if fetcher is not None:
        return parse_json(fetcher(normalized), normalized, server=server, dialect=dialect)
    try:
        text = fetch_text(url, accept="application/json", label=f"{server} {normalized}")
        return parse_json(text, normalized, server=server, dialect=dialect)
    except ProviderFetchError:
        metadata = doi_provider.fetch_metadata(normalized)
        metadata.provider = server
        metadata.fields["eprint"] = normalized
        archive_field = "eprinttype" if dialect.lower() == "biblatex" else "archivePrefix"
        metadata.fields[archive_field] = server
        metadata.fields.setdefault("url", content_url(normalized, server=server))
        metadata.identifiers[server] = normalized
        return metadata
