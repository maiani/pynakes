"""arXiv provider client: URL helpers, metadata fetch/parse, and downloads."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote

from pynakes._identifiers import normalize_arxiv
from pynakes.providers._http import ProviderFetchError, fetch_bytes

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
    primary_class: str = ""
    doi: str = ""
    journal: str = ""


_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_atom(identifier: str, timeout: float = 15.0) -> str:
    """Fetch arXiv Atom XML for ``identifier``. Split out so tests can stub it."""
    data = fetch_bytes(atom_url(identifier), timeout=timeout, label=identifier)
    return data.decode("utf-8", errors="replace")


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


def fetch_pdf(identifier: str, timeout: float = 30.0) -> bytes:
    """Fetch arXiv PDF bytes for ``identifier``."""
    arxiv_id = _normalize_or_raise(identifier)
    return fetch_bytes(pdf_url(arxiv_id), timeout=timeout, label=f"{arxiv_id} PDF")


def fetch_source(identifier: str, timeout: float = 30.0) -> bytes:
    """Fetch arXiv source archive bytes for ``identifier``."""
    arxiv_id = _normalize_or_raise(identifier)
    return fetch_bytes(source_url(arxiv_id), timeout=timeout, label=f"{arxiv_id} source")


def _xml_text(element: ET.Element, path: str) -> str:
    found = element.find(path, _ATOM_NS)
    return " ".join((found.text or "").split()) if found is not None else ""
