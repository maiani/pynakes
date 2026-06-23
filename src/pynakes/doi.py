"""Import BibTeX metadata from DOI content negotiation."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.keys import UnsupportedCitationKeyPatternError, generate_key, unique_key
from pynakes.model import BibEntry, BibFile

_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


class DOIImportError(Exception):
    """Raised when a DOI cannot be resolved into a BibTeX entry."""


class DuplicateDOIError(DOIImportError):
    """Raised when the DOI already exists in the target library."""

    def __init__(self, doi: str, keys: list[str]) -> None:
        self.doi = doi
        self.keys = keys
        super().__init__(f"DOI {doi!r} already exists in: {', '.join(keys)}")


class CitationKeyConflictError(DOIImportError):
    """Raised when an explicitly requested citation key already exists."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Citation key {key!r} already exists")


FetchBibTeX = Callable[[str], str]
KEY_SOURCES = {"generated", "provider"}


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
            "User-Agent": "pynakes/0.3.0 DOI import (mailto:unknown@example.invalid)",
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
    a normalized ``doi`` field.
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
    entry.fields["doi"] = normalized

    taken = set(lib.entries.keys())
    if key is not None:
        if key in taken:
            raise CitationKeyConflictError(key)
        entry.key = key
    elif key_source == "provider":
        entry.key = unique_key(entry.key, taken)
    else:
        try:
            generated = generate_key(entry, lib)
        except UnsupportedCitationKeyPatternError as exc:
            raise DOIImportError(str(exc)) from exc
        entry.key = unique_key(generated, taken)

    entry.modified = True
    entry.raw_content = None
    return entry


def render_entry(entry: BibEntry, line_ending: str = "\n") -> str:
    """Render a single entry as BibTeX text."""
    lib = BibFile(entries=[entry], line_ending=line_ending)
    return write_bib(lib).rstrip("\r\n")
