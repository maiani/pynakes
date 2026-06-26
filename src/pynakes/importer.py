"""Import BibTeX entries from external identifiers.

Resolves a user-supplied identifier (DOI, DOI URL, arXiv id, arXiv URL) to its
type, fetches authoritative metadata, and prepares a ready-to-append
:class:`~pynakes.model.BibEntry`. The library is never mutated here; callers
(see :class:`~pynakes.engine.Collection`) stage the returned entry.

DOI metadata comes from DOI content negotiation; arXiv metadata comes from the
arXiv Atom API. Neither path downloads PDFs or linked files — only metadata.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.keys import UnsupportedCitationKeyPatternError, generate_key, unique_key
from pynakes.model import BibEntry, BibFile

_USER_AGENT = "pynakes/0.3.0 reference import (mailto:unknown@example.invalid)"

_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

# Table of known journal URL patterns that encode the DOI directly.
# Each entry is (compiled pattern, extractor callable).  The extractor
# receives the re.Match and returns the bare DOI string.
# Extend here to support additional publishers without touching the resolver.
_JOURNAL_URL_RESOLVERS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    (
        # nature.com article URLs: slug IS the DOI suffix under prefix 10.1038
        # e.g. https://www.nature.com/articles/s41535-025-00801-3
        #   → DOI 10.1038/s41535-025-00801-3
        re.compile(r"^https?://(?:www\.)?nature\.com/articles/([^/?#\s]+)", re.IGNORECASE),
        lambda m: f"10.1038/{m.group(1)}",
    ),
    (
        # APS (American Physical Society) article and PDF URLs: DOI embedded in path
        # e.g. https://journals.aps.org/rmp/abstract/10.1103/k13g-z9s8
        #      https://journals.aps.org/rmp/pdf/10.1103/k13g-z9s8
        #   → DOI 10.1103/k13g-z9s8
        re.compile(
            r"^https?://journals\.aps\.org/\w+/(?:abstract|pdf)/(10\.\d{4,9}/\S+?)(?:[/?#]|$)",
            re.IGNORECASE,
        ),
        lambda m: m.group(1),
    ),
]

# arXiv identifiers come in the post-2007 ``YYMM.NNNNN`` form and the legacy
# ``archive/YYMMNNN`` form (e.g. ``hep-th/9901001``), each optionally suffixed
# with a version (``v2``). URLs and an ``arXiv:`` prefix are also accepted.
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#\s]+)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_ARXIV_NEW_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)
_ARXIV_OLD_RE = re.compile(r"^[a-z][a-z-]+(\.[a-z]{2})?/\d{7}(v\d+)?$", re.IGNORECASE)

KEY_SOURCES = {"generated", "provider"}

# Identifier types ``resolve_identifier`` can return. ``journal_url`` is reserved
# for a future resolver and currently raises ``UnsupportedIdentifierError``.
DOI = "doi"
ARXIV = "arxiv"


# --- errors ----------------------------------------------------------------


class ReferenceImportError(Exception):
    """Base error for any failure to resolve an identifier into an entry."""


class DOIImportError(ReferenceImportError):
    """Raised when a DOI cannot be resolved into a BibTeX entry."""


class ArxivImportError(ReferenceImportError):
    """Raised when an arXiv identifier cannot be resolved into an entry."""


class UnsupportedIdentifierError(ReferenceImportError):
    """Raised when an identifier is not recognized as a DOI or arXiv id."""


class DuplicateReferenceError(ReferenceImportError):
    """Base error for an identifier that already exists in the library."""

    def __init__(self, kind: str, identifier: str, keys: list[str]) -> None:
        self.kind = kind
        self.identifier = identifier
        self.keys = keys
        super().__init__(f"{kind} {identifier!r} already exists in: {', '.join(keys)}")


class DuplicateDOIError(DuplicateReferenceError):
    """Raised when the DOI already exists in the target library."""

    def __init__(self, doi: str, keys: list[str]) -> None:
        self.doi = doi
        super().__init__("DOI", doi, keys)


class DuplicateArxivError(DuplicateReferenceError):
    """Raised when the arXiv identifier already exists in the target library."""

    def __init__(self, arxiv_id: str, keys: list[str]) -> None:
        self.arxiv_id = arxiv_id
        super().__init__("arXiv id", arxiv_id, keys)


class CitationKeyConflictError(ReferenceImportError):
    """Raised when an explicitly requested citation key already exists."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Citation key {key!r} already exists")


FetchBibTeX = Callable[[str], str]
FetchArxivAtom = Callable[[str], str]


# --- identifier resolution -------------------------------------------------


def extract_doi_from_journal_url(url: str) -> str | None:
    """Extract a DOI from a recognized journal article URL, or return ``None``.

    Consults :data:`_JOURNAL_URL_RESOLVERS`. Currently supports:

    * ``nature.com/articles/{slug}`` → DOI ``10.1038/{slug}``
    * ``journals.aps.org/{journal}/abstract/{doi}`` → DOI embedded in path
    """
    stripped = url.strip()
    for pattern, extractor in _JOURNAL_URL_RESOLVERS:
        m = pattern.match(stripped)
        if m:
            doi = extractor(m)
            if _DOI_RE.match(doi):
                return doi
    return None


def resolve_identifier(value: str) -> tuple[str, str]:
    """Classify ``value`` and return ``(kind, normalized_identifier)``.

    ``kind`` is :data:`DOI` or :data:`ARXIV`. arXiv is detected first because an
    arXiv URL or ``arXiv:`` prefix is unambiguous; a bare ``10.x/...`` string is
    a DOI. Recognized journal article URLs (e.g. ``nature.com``) have their DOI
    extracted and also resolve as :data:`DOI`. Raises
    :class:`UnsupportedIdentifierError` for anything else.
    """
    raw = value.strip()
    if not raw:
        raise UnsupportedIdentifierError("Empty identifier")

    lowered = raw.lower()
    if "arxiv.org/" in lowered or lowered.startswith("arxiv:"):
        normalized = normalize_arxiv(raw)
        if normalized is None:
            raise UnsupportedIdentifierError(f"Malformed arXiv identifier: {value!r}")
        return ARXIV, normalized

    # A DOI URL or bare DOI.
    if _DOI_URL_RE.match(raw) or _DOI_RE.match(re.sub(r"^doi:\s*", "", raw, flags=re.IGNORECASE)):
        return DOI, normalize_doi(raw)

    # A bare arXiv identifier (no scheme), new or legacy form.
    if _ARXIV_NEW_RE.match(raw) or _ARXIV_OLD_RE.match(raw):
        normalized = normalize_arxiv(raw)
        if normalized is not None:
            return ARXIV, normalized

    # A recognized journal article URL (DOI extractable from the URL structure).
    extracted = extract_doi_from_journal_url(raw)
    if extracted is not None:
        return DOI, extracted

    raise UnsupportedIdentifierError(
        f"Unrecognized identifier {value!r}; expected a DOI, arXiv id/URL, "
        f"or a supported journal article URL (nature.com, journals.aps.org)"
    )


# --- DOI ------------------------------------------------------------------


def normalize_doi(value: str) -> str:
    """Normalize a DOI or DOI URL to the canonical bare DOI string."""
    doi = value.strip()
    doi = _DOI_URL_RE.sub("", doi)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE).strip()
    doi = doi.strip("<> \t\r\n")
    if not _DOI_RE.match(doi):
        raise ValueError(f"Malformed DOI: {value!r}")
    return doi


def canonical_doi(value: str) -> str:
    """Return a lowercase DOI string suitable for equality checks."""
    return normalize_doi(value).lower()


def fetch_bibtex_for_doi(doi: str, timeout: float = 15.0) -> str:
    """Fetch BibTeX metadata for ``doi`` using DOI content negotiation."""
    normalized = normalize_doi(doi)
    url = f"https://doi.org/{quote(normalized, safe='/')}"
    request = Request(
        url,
        headers={
            "Accept": "application/x-bibtex",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            encoding = response.headers.get_content_charset() or "utf-8"
            return data.decode(encoding, errors="replace")
    except HTTPError as exc:
        raise DOIImportError(f"DOI resolver returned HTTP {exc.code} for {normalized}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise DOIImportError(f"Could not resolve DOI {normalized!r}: {reason}") from exc


def entry_from_bibtex(text: str) -> BibEntry:
    """Parse provider BibTeX and return the first entry."""
    try:
        lib = parse_bib(text)
    except ParseError as exc:
        raise DOIImportError(f"Provider returned invalid BibTeX: {exc.message}") from exc
    entries = lib.entries.values()
    if not entries:
        raise DOIImportError("Provider returned no BibTeX entries")
    entry = entries[0]
    entry.raw_content = None
    entry.modified = True
    return entry


def existing_keys_for_doi(lib: BibFile, doi: str) -> list[str]:
    """Return citation keys already using ``doi`` in ``lib``."""
    target = canonical_doi(doi)
    keys: list[str] = []
    for entry in lib.entries.values():
        existing = entry.fields.get("doi")
        if not existing:
            continue
        try:
            if canonical_doi(existing) == target:
                keys.append(entry.key)
        except ValueError:
            continue
    return keys


# --- arXiv ----------------------------------------------------------------


@dataclass
class ArxivRecord:
    """The subset of arXiv Atom metadata pynakes turns into a BibTeX entry."""

    arxiv_id: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""  # ISO date, ``YYYY-MM-DD``
    primary_class: str = ""
    doi: str = ""
    journal: str = ""


def normalize_arxiv(value: str) -> str | None:
    """Normalize an arXiv id/URL to its bare, version-stripped, lowercase form."""
    cleaned = value.strip().strip("{}<>")
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.IGNORECASE)
    match = _ARXIV_URL_RE.search(cleaned)
    if match:
        cleaned = match.group(1)
    cleaned = cleaned.removesuffix(".pdf")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    cleaned = cleaned.strip("/")
    return cleaned.lower() or None


def entry_arxiv_id(entry: BibEntry) -> str | None:
    """Return the normalized arXiv id an entry already carries, if any."""
    for field_name in ("arxiv", "eprint"):
        value = entry.fields.get(field_name)
        if not value:
            continue
        archive = entry.fields.get("archiveprefix") or entry.fields.get("eprinttype") or ""
        if field_name == "arxiv" or archive.lower() == "arxiv":
            normalized = normalize_arxiv(value)
            if normalized:
                return normalized
    for field_name in ("url", "howpublished", "note"):
        match = _ARXIV_URL_RE.search(entry.fields.get(field_name, ""))
        if match:
            normalized = normalize_arxiv(match.group(1))
            if normalized:
                return normalized
    return None


def existing_keys_for_arxiv(lib: BibFile, identifier: str) -> list[str]:
    """Return citation keys already referencing ``identifier`` in ``lib``."""
    target = normalize_arxiv(identifier)
    if target is None:
        return []
    return [entry.key for entry in lib.entries.values() if entry_arxiv_id(entry) == target]


def fetch_arxiv_atom(identifier: str, timeout: float = 15.0) -> str:
    """Fetch arXiv Atom XML for ``identifier``. Split out so tests can stub it."""
    url = f"https://export.arxiv.org/api/query?id_list={quote(identifier)}"
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            encoding = response.headers.get_content_charset() or "utf-8"
            return data.decode(encoding, errors="replace")
    except HTTPError as exc:
        raise ArxivImportError(f"arXiv returned HTTP {exc.code} for {identifier}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ArxivImportError(
            f"Could not fetch arXiv metadata for {identifier}: {reason}"
        ) from exc


_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def parse_arxiv_atom(text: str, identifier: str) -> ArxivRecord:
    """Parse an arXiv Atom feed into an :class:`ArxivRecord`."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ArxivImportError(f"arXiv returned invalid XML for {identifier}") from exc
    entry = root.find("atom:entry", _ATOM_NS)
    if entry is None:
        raise ArxivImportError(f"arXiv returned no entry for {identifier}")

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


def _xml_text(element: ET.Element, path: str) -> str:
    found = element.find(path, _ATOM_NS)
    return " ".join((found.text or "").split()) if found is not None else ""


def arxiv_entry(record: ArxivRecord, *, dialect: str = "bibtex") -> BibEntry:
    """Build a fresh arXiv :class:`BibEntry` honoring the library ``dialect``.

    BibLaTeX libraries get an ``@online`` entry (with a ``date`` field and
    ``eprintclass``); BibTeX libraries get an ``@misc`` entry (with ``year``,
    ``archivePrefix``, and ``primaryClass``). The arXiv id is always recorded in
    ``eprint`` so :func:`entry_arxiv_id` and dedup recognize it in either form.
    """
    biblatex = dialect == "biblatex"
    fields: dict[str, str] = {}
    if record.authors:
        fields["author"] = " and ".join(record.authors)
    if record.title:
        fields["title"] = record.title
    if record.published:
        fields["date" if biblatex else "year"] = (
            record.published if biblatex else record.published[:4]
        )
    fields["eprint"] = record.arxiv_id
    fields["eprinttype" if biblatex else "archivePrefix"] = "arxiv" if biblatex else "arXiv"
    if record.primary_class:
        fields["eprintclass" if biblatex else "primaryClass"] = record.primary_class
    fields["url"] = f"https://arxiv.org/abs/{record.arxiv_id}"
    if record.doi:
        fields["doi"] = record.doi

    return BibEntry(
        key="arxiv",  # replaced with a unique key by prepare_imported_*
        type="online" if biblatex else "misc",
        fields=fields,
        raw_content=None,
        modified=True,
    )


def fetch_arxiv_record(identifier: str, fetcher: FetchArxivAtom | None = None) -> ArxivRecord:
    """Fetch and parse arXiv metadata for ``identifier``."""
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivImportError(f"Malformed arXiv identifier: {identifier!r}")
    if fetcher is None:
        fetcher = fetch_arxiv_atom
    return parse_arxiv_atom(fetcher(normalized), normalized)


# --- preparation -----------------------------------------------------------


def _assign_key(
    entry: BibEntry,
    lib: BibFile,
    *,
    key: str | None,
    key_source: str,
    provider_key: str | None,
) -> None:
    """Assign a unique citation key to ``entry`` per the chosen policy."""
    taken = set(lib.entries.keys())
    if key is not None:
        if key in taken:
            raise CitationKeyConflictError(key)
        entry.key = key
    elif key_source == "provider" and provider_key:
        entry.key = unique_key(provider_key, taken)
    else:
        try:
            generated = generate_key(entry, lib)
        except UnsupportedCitationKeyPatternError as exc:
            raise ReferenceImportError(str(exc)) from exc
        entry.key = unique_key(generated, taken)


def prepare_imported_entry(
    lib: BibFile,
    doi: str,
    *,
    key: str | None = None,
    key_source: str = "generated",
    allow_duplicate_doi: bool = False,
    fetcher: FetchBibTeX | None = None,
) -> BibEntry:
    """Fetch and prepare a DOI entry for appending to ``lib``.

    The library is not modified. The returned entry has a local citation key and
    a normalized ``doi`` field. Retained as the DOI-specific entry point;
    :func:`prepare_imported_reference` is the general dispatcher.
    """
    normalized = normalize_doi(doi)
    if key_source not in KEY_SOURCES:
        raise ValueError(
            f"Invalid key source {key_source!r}; expected one of: {', '.join(sorted(KEY_SOURCES))}"
        )
    if not allow_duplicate_doi:
        duplicate_keys = existing_keys_for_doi(lib, normalized)
        if duplicate_keys:
            raise DuplicateDOIError(normalized, duplicate_keys)

    if fetcher is None:
        fetcher = fetch_bibtex_for_doi
    entry = entry_from_bibtex(fetcher(normalized))
    provider_key = entry.key
    entry.fields["doi"] = normalized

    _assign_key(entry, lib, key=key, key_source=key_source, provider_key=provider_key)
    entry.modified = True
    entry.raw_content = None
    return entry


def prepare_imported_arxiv(
    lib: BibFile,
    identifier: str,
    *,
    dialect: str = "bibtex",
    key: str | None = None,
    key_source: str = "generated",
    allow_duplicate: bool = False,
    fetcher: FetchArxivAtom | None = None,
) -> BibEntry:
    """Fetch and prepare an arXiv entry for appending to ``lib``.

    No PDFs or linked files are downloaded — only Atom metadata. The library is
    not modified.
    """
    if key_source not in KEY_SOURCES:
        raise ValueError(
            f"Invalid key source {key_source!r}; expected one of: {', '.join(sorted(KEY_SOURCES))}"
        )
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivImportError(f"Malformed arXiv identifier: {identifier!r}")
    if not allow_duplicate:
        duplicate_keys = existing_keys_for_arxiv(lib, normalized)
        if duplicate_keys:
            raise DuplicateArxivError(normalized, duplicate_keys)

    record = fetch_arxiv_record(normalized, fetcher=fetcher)
    entry = arxiv_entry(record, dialect=dialect)
    # arXiv feeds carry no provider citation key, so "provider" falls back to
    # generation.
    _assign_key(entry, lib, key=key, key_source=key_source, provider_key=None)
    entry.modified = True
    entry.raw_content = None
    return entry


def prepare_imported_reference(
    lib: BibFile,
    identifier: str,
    *,
    dialect: str = "bibtex",
    key: str | None = None,
    key_source: str = "generated",
    allow_duplicate: bool = False,
    doi_fetcher: FetchBibTeX | None = None,
    arxiv_fetcher: FetchArxivAtom | None = None,
) -> tuple[str, BibEntry]:
    """Resolve ``identifier``, fetch metadata, and prepare an entry.

    Returns ``(kind, entry)`` where ``kind`` is :data:`DOI` or :data:`ARXIV`.
    Dispatches to the DOI or arXiv path; the library is not modified.
    """
    kind, normalized = resolve_identifier(identifier)
    if kind == ARXIV:
        entry = prepare_imported_arxiv(
            lib,
            normalized,
            dialect=dialect,
            key=key,
            key_source=key_source,
            allow_duplicate=allow_duplicate,
            fetcher=arxiv_fetcher,
        )
    else:
        entry = prepare_imported_entry(
            lib,
            normalized,
            key=key,
            key_source=key_source,
            allow_duplicate_doi=allow_duplicate,
            fetcher=doi_fetcher,
        )
    return kind, entry


def render_entry(entry: BibEntry, line_ending: str = "\n") -> str:
    """Render a single entry as BibTeX text."""
    lib = BibFile(entries=[entry], line_ending=line_ending)
    return write_bib(lib).rstrip("\r\n")
