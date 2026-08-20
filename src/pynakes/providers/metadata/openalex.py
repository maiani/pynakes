"""OpenAlex metadata provider helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import arxiv_id_from_text, normalize_doi
from pynakes.providers._common import clean_text, repository_metadata
from pynakes.providers._http import fetch_json, iter_strings
from pynakes.providers.metadata._json_service import json_metadata
from pynakes.providers.metadata.crossref import entry_type_from_crossref_type
from pynakes.providers.pdf_overrides import publisher_pdf_url
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.openalex.org/works/doi:"
API_ID_URL = "https://api.openalex.org/works/"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "OpenAlex"

_ID_RE = re.compile(r"^[Ww](\d+)$")


def fetch_work_by_doi(
    doi: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch an OpenAlex work by DOI, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    url = f"{API_URL}{quote(normalized, safe='')}"
    return fetch_json(
        url,
        namespace="openalex",
        identifier=normalized,
        provider="OpenAlex",
        cache_file=cache_file,
        opener=urlopen,
    )


def oa_pdf_url_for_doi(
    doi: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via OpenAlex, or ``None``."""
    work = fetch_work_by_doi(doi, cache_file=cache_file, urlopen=urlopen)
    if work is None:
        return None
    return oa_pdf_url_from_work(work)


def arxiv_id_from_work(work: dict) -> str | None:
    """Return the first arXiv id encoded in an OpenAlex work's locations."""
    for location in _locations(work):
        for value in iter_strings(location):
            arxiv_id = arxiv_id_from_text(value)
            if arxiv_id:
                return arxiv_id
    return None


def _is_publisher_location(location: dict) -> bool:
    """Return True if *location* is hosted by a publisher (not a repository).

    Checks ``host_type`` when present, falling back to ``source.type``.
    """
    host_type = location.get("host_type")
    if host_type is not None:
        return host_type == "publisher"
    src = location.get("source")
    if isinstance(src, dict):
        return src.get("type") == "journal"
    return False


def oa_pdf_url_from_work(work: dict) -> str | None:
    """Return OpenAlex's best publisher-hosted OA PDF URL for a work, if any.

    Only returns URLs from publisher-hosted locations (not from arXiv, PMC,
    or institutional repositories) so that repository mirrors of the same
    paper do not get misidentified as the published version of record.

    When a publisher landing page exists but no direct ``pdf_url`` is
    available (e.g. APS papers served via ``/pdf/`` rather than ``/abstract/``),
    the function falls back to :func:`publisher_pdf_url` which applies
    publisher-specific URL construction rules.
    """
    best_oa = work.get("best_oa_location")
    if not isinstance(best_oa, dict):
        return None
    if not _is_publisher_location(best_oa):
        return None

    pdf_url = best_oa.get("pdf_url")
    if isinstance(pdf_url, str) and pdf_url.strip():
        return pdf_url.strip()

    landing = best_oa.get("landing_page_url")
    raw_doi = work.get("doi")
    doi = _extract_doi(raw_doi)

    if landing and isinstance(landing, str) and landing.strip():
        return publisher_pdf_url(landing.strip(), doi=doi)
    return None


def _extract_doi(raw: object) -> str | None:
    """Extract a bare DOI string from an OpenAlex ``doi`` field (which is a URL)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    for prefix in ("https://doi.org/", "http://doi.org/"):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw.strip()


def normalize_identifier(identifier: str) -> str:
    """Normalize an OpenAlex work id (``W`` followed by digits)."""
    match = _ID_RE.match(identifier.strip())
    if match is None:
        raise ValueError(f"Malformed OpenAlex work id: {identifier!r}")
    return f"W{match.group(1)}"


def record_url(identifier: str) -> str:
    """Return the canonical OpenAlex work landing page."""
    return f"https://openalex.org/{normalize_identifier(identifier)}"


def fetch_work_by_id(
    work_id: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch an OpenAlex work by its native id, using a deterministic cache when provided."""
    normalized = normalize_identifier(work_id)
    url = f"{API_ID_URL}{quote(normalized, safe='')}"
    return fetch_json(
        url,
        namespace="openalex-id",
        identifier=normalized,
        provider=PROVIDER_NAME,
        cache_file=cache_file,
        opener=urlopen,
    )


def metadata_from_work(work: dict, identifier: str, dialect: str) -> ReferenceMetadata:
    """Convert an OpenAlex work record into normalized metadata."""
    title = clean_text(work.get("title") or work.get("display_name"))
    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and (name := clean_text(author.get("display_name"))):
            authors.append(name)

    fields: dict[str, str] = {}
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        source = primary.get("source")
        if isinstance(source, dict) and (venue := clean_text(source.get("display_name"))):
            fields["journal"] = venue

    doi = clean_text(_extract_doi(work.get("doi")))
    year = work.get("publication_year")
    published = str(year) if isinstance(year, int) else clean_text(year)
    return repository_metadata(
        provider=PROVIDER_NAME,
        identifier_kind="openalex",
        identifier=identifier,
        dialect=dialect,
        title=title,
        authors=authors,
        published=published,
        url=record_url(identifier),
        doi=doi,
        entry_type=entry_type_from_crossref_type(work.get("type")),
        fields=fields,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an OpenAlex work record, addressed by native work id."""
    normalized = normalize_identifier(identifier)
    return json_metadata(
        normalized,
        provider=PROVIDER_NAME,
        dialect=dialect,
        fetcher=fetcher,
        fetch_record=fetch_work_by_id,
        convert=metadata_from_work,
    )


def _locations(work: dict) -> list[dict]:
    locations: list[dict] = []
    for field_name in ("primary_location", "best_oa_location"):
        location = work.get(field_name)
        if isinstance(location, dict):
            locations.append(location)
    raw_locations = work.get("locations")
    if isinstance(raw_locations, list):
        locations.extend(location for location in raw_locations if isinstance(location, dict))
    return locations
