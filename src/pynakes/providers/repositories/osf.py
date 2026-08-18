"""OSF Preprints metadata client."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.osf.io/v2/preprints"
RawFetcher = Callable[[str], str]


def normalize_identifier(identifier: str) -> str:
    """Normalize an OSF opaque id."""
    value = identifier.strip().lower()
    if re.fullmatch(r"[a-z0-9]+(?:_v\d+)?", value) is None:
        raise ValueError(f"Malformed OSF preprint id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical generic OSF preprint URL."""
    return f"https://osf.io/preprints/{normalize_identifier(identifier)}/"


def parse_contributors(text: str) -> list[str]:
    """Parse ordered bibliographic contributors from an OSF JSON:API response."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError("OSF returned invalid contributor JSON") from exc
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    authors: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        embeds = record.get("embeds")
        users = embeds.get("users") if isinstance(embeds, dict) else None
        user = users.get("data") if isinstance(users, dict) else None
        attrs = user.get("attributes") if isinstance(user, dict) else None
        if isinstance(attrs, dict) and (name := person_name(attrs)):
            authors.append(name)
    return authors


def parse_json(
    text: str,
    identifier: str,
    *,
    dialect: str,
    contributors: list[str] | None = None,
) -> ReferenceMetadata:
    """Parse an OSF JSON:API preprint response."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"OSF returned invalid JSON for {identifier!r}") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ProviderFetchError(f"OSF returned no entry for {identifier!r}")
    attrs = data.get("attributes")
    if not isinstance(attrs, dict):
        attrs = {}
    authors: list[str] = list(contributors or [])
    for author in attrs.get("authors") or []:
        if name := person_name(author):
            authors.append(name)
    links = data.get("links")
    url = ""
    doi = clean_text(attrs.get("doi"))
    if isinstance(links, dict):
        url = clean_text(links.get("html"))
        if not doi:
            doi_url = clean_text(links.get("preprint_doi"))
            if doi_url.startswith("https://doi.org/"):
                doi = doi_url.removeprefix("https://doi.org/")
    return repository_metadata(
        provider="OSF Preprints",
        identifier_kind="osf",
        identifier=identifier,
        dialect=dialect,
        title=clean_text(attrs.get("title")),
        authors=authors,
        published=clean_text(attrs.get("date_published") or attrs.get("date_created")),
        abstract=clean_text(attrs.get("description")),
        url=url or record_url(identifier),
        doi=doi,
        fields={"osf": identifier},
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an OSF preprint."""
    normalized = normalize_identifier(identifier)
    if fetcher is not None:
        return parse_json(fetcher(normalized), normalized, dialect=dialect)
    text = fetch_text(
        f"{API_URL}/{quote(normalized)}/",
        accept="application/vnd.api+json",
        label=f"OSF preprint {normalized}",
    )
    contributor_text = fetch_text(
        f"{API_URL}/{quote(normalized)}/bibliographic_contributors/",
        accept="application/vnd.api+json",
        label=f"OSF preprint {normalized} contributors",
    )
    return parse_json(
        text,
        normalized,
        dialect=dialect,
        contributors=parse_contributors(contributor_text),
    )
