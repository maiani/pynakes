"""Semantic Scholar metadata provider helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import arxiv_id_from_text, normalize_arxiv, normalize_doi
from pynakes.providers._common import clean_text, repository_metadata
from pynakes.providers._http import fetch_json, iter_strings
from pynakes.providers.metadata._json_service import json_metadata
from pynakes.providers.records import ReferenceMetadata

GRAPH_API_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "externalIds,url,title,authors,venue,year,publicationTypes,journal"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "Semantic Scholar"

_ID_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_ENTRY_TYPES = {"journalarticle": "article", "conference": "inproceedings"}


def fetch_paper_by_doi(
    doi: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch Semantic Scholar paper metadata by DOI."""
    normalized = normalize_doi(doi)
    url = f"{GRAPH_API_URL}/paper/DOI:{quote(normalized, safe='')}?fields=externalIds,url"
    return fetch_json(
        url,
        namespace="semantic_scholar",
        identifier=normalized,
        provider="Semantic Scholar",
        cache_file=cache_file,
        opener=urlopen,
    )


def normalize_identifier(identifier: str) -> str:
    """Normalize a bare 40-hex Semantic Scholar paper id."""
    value = identifier.strip()
    if not _ID_RE.match(value):
        raise ValueError(f"Malformed Semantic Scholar paper id: {identifier!r}")
    return value.lower()


def record_url(identifier: str) -> str:
    """Return a canonical Semantic Scholar paper URL."""
    return f"https://www.semanticscholar.org/paper/{normalize_identifier(identifier)}"


def fetch_paper_by_id(
    paper_id: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch Semantic Scholar paper metadata by its native 40-hex paper id.

    The Graph API works unauthenticated at low request volume; an API key
    only raises rate limits, so no key is required or used here.
    """
    normalized = normalize_identifier(paper_id)
    url = f"{GRAPH_API_URL}/paper/{quote(normalized, safe='')}?fields={PAPER_FIELDS}"
    return fetch_json(
        url,
        namespace="semantic-scholar-id",
        identifier=normalized,
        provider=PROVIDER_NAME,
        cache_file=cache_file,
        opener=urlopen,
    )


def _entry_type_from_types(types: object) -> str:
    if isinstance(types, list):
        for candidate in types:
            if isinstance(candidate, str) and candidate.lower() in _ENTRY_TYPES:
                return _ENTRY_TYPES[candidate.lower()]
    return "misc"


def metadata_from_paper(paper: dict, identifier: str, dialect: str) -> ReferenceMetadata:
    """Convert a Semantic Scholar paper record into normalized metadata.

    Semantic Scholar gives authors as one flat display name with no
    given/family split, so each name passes through :func:`clean_text` only —
    a split is not faked.
    """
    authors = [
        name
        for author in paper.get("authors") or []
        if isinstance(author, dict) and (name := clean_text(author.get("name")))
    ]

    venue = clean_text(paper.get("venue"))
    if not venue:
        journal = paper.get("journal")
        if isinstance(journal, dict):
            venue = clean_text(journal.get("name"))
    fields: dict[str, str] = {}
    if venue:
        fields["journal"] = venue

    external_ids = paper.get("externalIds")
    doi = clean_text(external_ids.get("DOI")) if isinstance(external_ids, dict) else ""
    year = paper.get("year")
    published = str(year) if isinstance(year, int) else clean_text(year)
    return repository_metadata(
        provider=PROVIDER_NAME,
        identifier_kind="semantic_scholar",
        identifier=identifier,
        dialect=dialect,
        title=clean_text(paper.get("title")),
        authors=authors,
        published=published,
        url=clean_text(paper.get("url")) or record_url(identifier),
        doi=doi,
        entry_type=_entry_type_from_types(paper.get("publicationTypes")),
        fields=fields,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a Semantic Scholar paper record, addressed by native paper id."""
    normalized = normalize_identifier(identifier)
    return json_metadata(
        normalized,
        provider=PROVIDER_NAME,
        dialect=dialect,
        fetcher=fetcher,
        fetch_record=fetch_paper_by_id,
        convert=metadata_from_paper,
    )


def arxiv_id_from_paper(paper: dict) -> str | None:
    """Return the arXiv id in Semantic Scholar metadata, if any."""
    external_ids = paper.get("externalIds")
    if isinstance(external_ids, dict):
        for name, value in external_ids.items():
            if name.lower() == "arxiv" and isinstance(value, str):
                return normalize_arxiv(value)
    for value in iter_strings(paper):
        arxiv_id = arxiv_id_from_text(value)
        if arxiv_id:
            return arxiv_id
    return None
