"""arXiv repository client: URL helpers, metadata fetch/parse, and downloads."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote

from pynakes._calendar import MONTH_NUM_TO_ABBR
from pynakes._identifiers import normalize_arxiv
from pynakes.entry_types import eprint_fields, preprint_entry_type
from pynakes.providers._http import (
    DEFAULT_TIMEOUT,
    DownloadProgress,
    ProviderFetchError,
    fetch_bytes,
    fetch_text,
)
from pynakes.providers.records import ReferenceMetadata

BASE_URL = "https://arxiv.org"
EXPORT_API = "https://export.arxiv.org/api/query"

FetchArxivAtom = Callable[[str], str]


def abs_url(identifier: str) -> str:
    """Return the canonical arXiv abstract URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"{BASE_URL}/abs/{quote(normalized, safe='/')}"


def pdf_url(identifier: str) -> str:
    """Return the canonical arXiv PDF URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"{BASE_URL}/pdf/{quote(normalized, safe='/')}"


def source_url(identifier: str) -> str:
    """Return the canonical arXiv source archive URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"{BASE_URL}/e-print/{quote(normalized, safe='/')}"


def atom_url(identifier: str) -> str:
    """Return the arXiv Atom API URL for ``identifier``."""
    return f"{EXPORT_API}?id_list={quote(identifier)}"


def _normalize_or_raise(identifier: str) -> str:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ValueError(f"Malformed arXiv identifier: {identifier!r}")
    return normalized


@dataclass
class ArxivRecord:
    """The subset of arXiv Atom metadata callers turn into a BibTeX entry."""

    arxiv_id: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""  # ISO date, ``YYYY-MM-DD``
    updated: str = ""  # last-updated ISO date, ``YYYY-MM-DD``
    summary: str = ""  # abstract text
    primary_class: str = ""
    doi: str = ""
    journal: str = ""


_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_atom(identifier: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch arXiv Atom XML for ``identifier``. Split out so tests can stub it."""
    return fetch_text(atom_url(identifier), timeout=timeout, label=identifier)


def parse_atom(text: str, identifier: str) -> ArxivRecord:
    """Parse an arXiv Atom feed into an :class:`ArxivRecord`."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderFetchError(f"arXiv returned invalid XML for {identifier}") from exc
    entry = root.find("atom:entry", _ATOM_NS)
    if entry is None:
        raise ProviderFetchError(f"arXiv returned no entry for {identifier}")

    authors = [
        name
        for author in entry.findall("atom:author", _ATOM_NS)
        if (name := _xml_text(author, "atom:name"))
    ]
    primary = entry.find("arxiv:primary_category", _ATOM_NS)
    return ArxivRecord(
        arxiv_id=normalize_arxiv(identifier) or identifier,
        title=_xml_text(entry, "atom:title"),
        authors=authors,
        published=_xml_text(entry, "atom:published")[:10],
        updated=_xml_text(entry, "atom:updated")[:10],
        summary=_xml_text(entry, "atom:summary"),
        primary_class=primary.get("term", "") if primary is not None else "",
        doi=_xml_text(entry, "arxiv:doi"),
        journal=_xml_text(entry, "arxiv:journal_ref"),
    )


def fetch_record(identifier: str, fetcher: FetchArxivAtom | None = None) -> ArxivRecord:
    """Fetch and parse arXiv metadata for ``identifier``."""
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ProviderFetchError(f"Malformed arXiv identifier: {identifier!r}")
    if fetcher is None:
        fetcher = fetch_atom
    return parse_atom(fetcher(normalized), normalized)


def metadata_from_record(
    record: ArxivRecord,
    *,
    dialect: str = "bibtex",
) -> ReferenceMetadata:
    """Normalize an arXiv record for the requested bibliography dialect."""
    biblatex = dialect.lower() == "biblatex"
    fields: dict[str, str] = {}
    if record.authors:
        fields["author"] = " and ".join(record.authors)
    if record.title:
        fields["title"] = record.title
    if record.published:
        if biblatex:
            fields["date"] = record.published
        else:
            year = record.published[:4]
            month = record.published[5:7]
            if year:
                fields["year"] = year
            if month in MONTH_NUM_TO_ABBR:
                fields["month"] = MONTH_NUM_TO_ABBR[month]
    names = eprint_fields(dialect)
    fields[names.eprint] = record.arxiv_id
    fields[names.archive] = names.archive_value
    if record.primary_class:
        fields[names.eprint_class] = record.primary_class
    fields["url"] = abs_url(record.arxiv_id)
    if record.doi:
        fields["doi"] = record.doi
    if record.summary:
        fields["abstract"] = record.summary
    if record.updated:
        fields["updated"] = record.updated

    identifiers = {"arxiv": record.arxiv_id}
    if record.doi:
        identifiers["doi"] = record.doi
    return ReferenceMetadata(
        provider="arXiv",
        entry_type=preprint_entry_type(dialect),
        fields=fields,
        identifiers=identifiers,
    )


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: FetchArxivAtom | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize arXiv metadata."""
    return metadata_from_record(fetch_record(identifier, fetcher=fetcher), dialect=dialect)


def fetch_pdf(
    identifier: str, timeout: float = 30.0, progress: DownloadProgress | None = None
) -> bytes:
    """Fetch arXiv PDF bytes for ``identifier``."""
    arxiv_id = _normalize_or_raise(identifier)
    return fetch_bytes(
        pdf_url(arxiv_id), timeout=timeout, label=f"{arxiv_id} PDF", progress=progress
    )


def fetch_source(
    identifier: str, timeout: float = 30.0, progress: DownloadProgress | None = None
) -> bytes:
    """Fetch arXiv source archive bytes for ``identifier``."""
    arxiv_id = _normalize_or_raise(identifier)
    return fetch_bytes(
        source_url(arxiv_id), timeout=timeout, label=f"{arxiv_id} source", progress=progress
    )


def _xml_text(element: ET.Element, path: str) -> str:
    found = element.find(path, _ATOM_NS)
    return " ".join((found.text or "").split()) if found is not None else ""
