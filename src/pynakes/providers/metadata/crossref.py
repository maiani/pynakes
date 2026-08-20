"""Crossref metadata provider helpers.

A Crossref record is addressed by DOI, the same identifier that resolves
through plain DOI content negotiation. The ``Crossref:<DOI>`` import prefix
and the bare API URL exist to force Crossref's own JSON record instead —
useful when a publisher's content-negotiated BibTeX is thin or malformed but
Crossref's structured metadata (container title, volume/issue/page, member
type) is not.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import normalize_doi
from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import fetch_json
from pynakes.providers.metadata._json_service import RawFetcher, json_metadata
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://api.crossref.org/works/"
WORKS_QUERY_URL = "https://api.crossref.org/works"

PROVIDER_NAME = "CrossRef"

# Only mappings whose target type is spelled the same in BibTeX and BibLaTeX are
# listed; anything else falls back to "misc" rather than guessing per dialect.
_ENTRY_TYPES = {
    "journal-article": "article",
    "article": "article",
    "book-chapter": "inbook",
    "book-part": "inbook",
    "book-section": "inbook",
    "proceedings-article": "inproceedings",
    "proceedings": "proceedings",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
}


def fetch_doi_by_alternative_id(
    alternative_id: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> str | None:
    """Resolve a publisher-assigned alternative id to its DOI, or ``None``.

    Elsevier and other publishers deposit their internal article identifier
    (for Elsevier, the PII) as a Crossref ``alternative-id``, which makes this
    the resolution path for publisher URLs that carry no DOI.
    """
    value = alternative_id.strip()
    if not value:
        return None
    url = (
        f"{WORKS_QUERY_URL}?filter=alternative-id:{quote(value, safe='')}"
        "&rows=1&select=DOI,alternative-id"
    )
    data = fetch_json(
        url,
        namespace="crossref-alternative-id",
        identifier=value,
        provider="CrossRef",
        cache_file=cache_file,
        opener=urlopen,
    )
    if data is None:
        return None
    message = data.get("message")
    items = message.get("items") if isinstance(message, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("DOI")
        if not isinstance(raw, str):
            continue
        try:
            return normalize_doi(raw)
        except ValueError:
            continue
    return None


def fetch_work_by_doi(
    doi: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch a CrossRef work record by DOI, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    url = f"{API_URL}{quote(normalized, safe='')}"
    data = fetch_json(
        url,
        namespace="crossref",
        identifier=normalized,
        provider="CrossRef",
        cache_file=cache_file,
        opener=urlopen,
    )
    if data is None:
        return None
    return data.get("message")


def oa_pdf_url_from_work(work: dict) -> str | None:
    """Return the best PDF URL from a CrossRef work, or ``None``.

    Prefers links with ``content-type: application/pdf``.  Falls back to
    similarity-checking links (e.g. APS harvest URLs) that serve PDF even
    when the content-type is unspecified.
    """
    links: list[dict] = work.get("link") or []
    if not links:
        return None

    best: str | None = None
    for link in links:
        url = _clean_url(link.get("URL"))
        if url is None:
            continue
        ct = link.get("content-type", "").lower()
        if ct == "application/pdf":
            return url
        app = link.get("intended-application", "").lower()
        if app == "similarity-checking" and best is None:
            best = url
    return best


def _clean_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def oa_pdf_url_for_doi(
    doi: str,
    *,
    cache_file: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via CrossRef, or ``None``."""
    work = fetch_work_by_doi(doi, cache_file=cache_file, urlopen=urlopen)
    if work is None:
        return None
    return oa_pdf_url_from_work(work)


def entry_type_from_crossref_type(value: object) -> str:
    """Map a Crossref (or Crossref-derived, e.g. OpenAlex) work ``type`` to a BibTeX type."""
    if isinstance(value, str):
        return _ENTRY_TYPES.get(value.lower(), "misc")
    return "misc"


def normalize_identifier(identifier: str) -> str:
    """Normalize the DOI a Crossref import is addressed by."""
    return normalize_doi(identifier)


def _date_from_work(work: dict) -> str:
    for key in ("published", "published-print", "published-online"):
        value = work.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return "-".join(str(part) for part in parts[0] if part is not None)
    return ""


def metadata_from_work(work: dict, identifier: str, dialect: str) -> ReferenceMetadata:
    """Convert a Crossref work record into normalized metadata."""
    titles = work.get("title")
    title = clean_text(titles[0]) if isinstance(titles, list) and titles else ""
    authors = [name for author in work.get("author") or [] if (name := person_name(author))]

    fields: dict[str, str] = {}
    containers = work.get("container-title")
    if isinstance(containers, list) and containers and (journal := clean_text(containers[0])):
        fields["journal"] = journal
    if volume := clean_text(work.get("volume")):
        fields["volume"] = volume
    if issue := clean_text(work.get("issue")):
        fields["number"] = issue
    if pages := clean_text(work.get("page")):
        fields["pages"] = pages

    doi = clean_text(work.get("DOI")) or identifier
    return repository_metadata(
        provider=PROVIDER_NAME,
        identifier_kind="crossref",
        identifier=identifier,
        dialect=dialect,
        title=title,
        authors=authors,
        published=_date_from_work(work),
        url=f"https://doi.org/{doi}",
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
    """Fetch and normalize a Crossref work record, forcing the Crossref JSON path."""
    normalized = normalize_identifier(identifier)
    return json_metadata(
        normalized,
        provider=PROVIDER_NAME,
        dialect=dialect,
        fetcher=fetcher,
        fetch_record=fetch_work_by_doi,
        envelope=lambda raw: raw.get("message"),
        convert=metadata_from_work,
    )
