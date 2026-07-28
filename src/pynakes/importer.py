"""Import BibTeX entries from external identifiers.

Resolves a user-supplied identifier or supported URL, asks the matching
provider for normalized metadata, and prepares a ready-to-append
:class:`~pynakes.model.BibEntry`. The library is never mutated here; callers
(see :class:`~pynakes.engine.Bibliography`) stage the returned entry.

Metadata comes from the API or citation-metadata interface of the selected
identifier authority or repository. Import never downloads PDFs or linked
files — only metadata.
"""

from __future__ import annotations

from collections.abc import Callable

from pynakes._identifiers import (
    canonical_doi,
    looks_like_arxiv_id,
    looks_like_isbn,
    normalize_arxiv,
    normalize_doi,
    normalize_isbn,
    normalize_pii,
)
from pynakes.identity import (
    WorkIdentifiers,
    evidence_from_entry,
    find_exact_matches,
)
from pynakes.keys import UnsupportedCitationKeyPatternError, generate_key, unique_key
from pynakes.model import BibEntry, BibFile
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import acl_anthology, dblp, inspire
from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.registry import RawMetadataFetcher, get_import_provider
from pynakes.providers.repositories import (
    arxiv,
    chemrxiv,
    europe_pmc,
    hal,
    nber,
    osf,
    pubmed,
    research_square,
    ssrn,
    zenodo,
)
from pynakes.providers.url_resolvers import (
    extract_publisher_doi,
    resolve_reference_url,
    url_resolution_hint,
)

# Re-exported for callers that import the parsed-record type from this module.
ArxivRecord = arxiv.ArxivRecord

KEY_SOURCES = {"generated", "provider"}

# Identifier types ``resolve_identifier`` can return.
DOI = "doi"
ARXIV = "arxiv"
PMID = "pmid"
PMCID = "pmcid"
EUROPE_PMC = "europe_pmc"
SSRN = "ssrn"
NBER = "nber"
BIORXIV = "biorxiv"
MEDRXIV = "medrxiv"
ZENODO = "zenodo"
OSF = "osf"
HAL = "hal"
CHEMRXIV = "chemrxiv"
RESEARCH_SQUARE = "research_square"
PII = "pii"
ISBN = "isbn"
INSPIRE = "inspire"
DBLP = "dblp"
ACL = "acl"

IDENTIFIER_KINDS = {
    DOI,
    ARXIV,
    PMID,
    PMCID,
    EUROPE_PMC,
    SSRN,
    NBER,
    BIORXIV,
    MEDRXIV,
    ZENODO,
    OSF,
    HAL,
    CHEMRXIV,
    RESEARCH_SQUARE,
    PII,
    ISBN,
    INSPIRE,
    DBLP,
    ACL,
}


# --- errors ----------------------------------------------------------------


class ReferenceImportError(Exception):
    """Base error for any failure to resolve an identifier into an entry."""


class DOIImportError(ReferenceImportError):
    """Raised when a DOI cannot be resolved into a BibTeX entry."""


class ArxivImportError(ReferenceImportError):
    """Raised when an arXiv identifier cannot be resolved into an entry."""


class UnsupportedIdentifierError(ReferenceImportError):
    """Raised when an identifier is not recognized by an import provider."""


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

    Consults the DOI-bearing rules of the declarative publisher URL resolver
    table. Currently supports:

    * ``nature.com/articles/{slug}`` → DOI ``10.1038/{slug}``
    * ``journals.aps.org/{journal}/abstract/{doi}`` → DOI embedded in path
    * ``link.springer.com/{article,chapter,book,…}/{doi}`` → DOI in path
    * ``onlinelibrary.wiley.com/doi/{doi}`` → DOI in path
    * ``journals.plos.org/{journal}/article?id={doi}`` → DOI in query

    Publisher URLs addressed by another identifier — such as a ScienceDirect
    PII — resolve through :func:`resolve_identifier` and their own provider
    instead, so they are not returned here.
    """
    return extract_publisher_doi(url)


def resolve_identifier(value: str) -> tuple[str, str]:
    """Classify ``value`` and return ``(kind, normalized_identifier)``.

    URLs are resolved by the ordered provider URL table, so any supported
    repository, catalogue, or publisher article URL can be passed directly.
    Bare DOI, arXiv, and unambiguous ISBN identifiers retain their convenient
    forms; identifiers that would otherwise be ambiguous require a provider
    prefix such as ``PMID:`` or ``Zenodo:``.
    """
    raw = value.strip()
    if not raw:
        raise UnsupportedIdentifierError("Empty identifier")

    resolved_url = resolve_reference_url(raw)
    if resolved_url is not None:
        return resolved_url.kind, resolved_url.identifier

    lowered = raw.lower()
    if lowered.startswith("arxiv:"):
        normalized = normalize_arxiv(raw)
        if normalized is None:
            raise UnsupportedIdentifierError(f"Malformed arXiv identifier: {value!r}")
        return ARXIV, normalized

    labeled: tuple[tuple[str, str, Callable[[str], str]], ...] = (
        ("pmcid:", PMCID, lambda value: pubmed.canonical_identifier(value, kind=PMCID)),
        ("pmid:", PMID, lambda value: pubmed.canonical_identifier(value, kind=PMID)),
        ("epmc:", EUROPE_PMC, europe_pmc.normalize_identifier),
        ("europepmc:", EUROPE_PMC, europe_pmc.normalize_identifier),
        ("ssrn:", SSRN, ssrn.normalize_identifier),
        ("nber:", NBER, nber.normalize_identifier),
        ("biorxiv:", BIORXIV, normalize_doi),
        ("medrxiv:", MEDRXIV, normalize_doi),
        ("zenodo:", ZENODO, zenodo.normalize_identifier),
        ("osf:", OSF, osf.normalize_identifier),
        ("hal:", HAL, hal.normalize_identifier),
        ("chemrxiv:", CHEMRXIV, chemrxiv.normalize_identifier),
        ("researchsquare:", RESEARCH_SQUARE, research_square.normalize_identifier),
        ("pii:", PII, normalize_pii),
        ("isbn:", ISBN, normalize_isbn),
        ("isbn-10:", ISBN, normalize_isbn),
        ("isbn-13:", ISBN, normalize_isbn),
        ("inspire:", INSPIRE, inspire.normalize_identifier),
        ("dblp:", DBLP, dblp.normalize_identifier),
        ("acl:", ACL, acl_anthology.normalize_identifier),
    )
    for prefix, kind, normalizer in labeled:
        if lowered.startswith(prefix):
            try:
                return kind, normalizer(raw[len(prefix) :])
            except ValueError as exc:
                raise UnsupportedIdentifierError(str(exc)) from exc

    try:
        return DOI, normalize_doi(raw)
    except ValueError:
        pass

    # A bare arXiv identifier (no scheme), new or legacy form.
    if looks_like_arxiv_id(raw):
        normalized = normalize_arxiv(raw)
        if normalized is not None:
            return ARXIV, normalized

    # A bare ISBN, restricted to the forms no other record id can be mistaken for.
    if looks_like_isbn(raw):
        return ISBN, normalize_isbn(raw)

    # A recognized host whose article URLs carry no recoverable identifier.
    hint = url_resolution_hint(raw)
    if hint is not None:
        raise UnsupportedIdentifierError(f"Cannot resolve {value!r}: {hint}")

    raise UnsupportedIdentifierError(
        f"Unrecognized identifier {value!r}; expected a DOI, arXiv id, ISBN, "
        "provider-prefixed identifier, or supported repository/catalogue/publisher URL"
    )


def fetch_bibtex_for_doi(doi: str, timeout: float = 15.0) -> str:
    """Fetch BibTeX metadata for ``doi`` via DOI content negotiation.

    Thin domain wrapper over :func:`pynakes.providers.metadata.doi.fetch_bibtex` that
    translates provider transport errors into :class:`DOIImportError`.
    """
    try:
        return doi_provider.fetch_bibtex(doi, timeout=timeout)
    except ProviderFetchError as exc:
        raise DOIImportError(str(exc)) from exc


def entry_from_bibtex(text: str) -> BibEntry:
    """Parse provider BibTeX and return the first entry."""
    try:
        metadata = doi_provider.parse_bibtex(text)
    except ProviderFetchError as exc:
        raise DOIImportError(str(exc)) from exc
    return entry_from_metadata(metadata)


def entry_from_metadata(metadata: ReferenceMetadata) -> BibEntry:
    """Convert normalized provider metadata into an unstaged entry."""
    return BibEntry(
        key=metadata.provider_key or "imported",
        type=metadata.entry_type,
        fields=dict(metadata.fields),
        field_expressions=dict(metadata.field_expressions),
        raw_content=None,
        modified=True,
    )


def existing_keys_for_doi(lib: BibFile, doi: str) -> list[str]:
    """Return citation keys already using ``doi`` in ``lib``."""
    target = canonical_doi(doi)
    return find_exact_matches(lib, {"doi": target})


# --- arXiv ----------------------------------------------------------------


def existing_keys_for_arxiv(lib: BibFile, identifier: str) -> list[str]:
    """Return citation keys already referencing ``identifier`` in ``lib``."""
    target = normalize_arxiv(identifier)
    if target is None:
        return []
    return find_exact_matches(lib, {"arxiv": target})


def existing_keys_for_identifier(lib: BibFile, kind: str, identifier: str) -> list[str]:
    """Return citation keys already carrying one normalized provider identity."""
    return find_exact_matches(lib, {kind: identifier})


def imported_entry_identifier(entry: BibEntry, kind: str) -> str:
    """Return the provider identifier recorded on an imported entry."""
    evidence = evidence_from_entry(entry)
    values = evidence.identifiers.by_kind().get(kind)
    if values:
        return sorted(values)[0]
    primary = evidence.identifiers.primary()
    return primary.value if primary is not None else entry.key


def fetch_arxiv_atom(identifier: str, timeout: float = 15.0) -> str:
    """Fetch arXiv Atom XML for ``identifier``. Split out so tests can stub it.

    Thin domain wrapper over :func:`pynakes.providers.repositories.arxiv.fetch_atom` that
    translates provider transport errors into :class:`ArxivImportError`.
    """
    try:
        return arxiv.fetch_atom(identifier, timeout=timeout)
    except ProviderFetchError as exc:
        raise ArxivImportError(str(exc)) from exc


def arxiv_entry(record: ArxivRecord, *, dialect: str = "bibtex") -> BibEntry:
    """Build a fresh arXiv :class:`BibEntry` honoring the library ``dialect``.

    BibLaTeX libraries get an ``@online`` entry (with a ``date`` field and
    ``eprintclass``); BibTeX libraries get an ``@misc`` entry (with ``year``,
    ``archivePrefix``, and ``primaryClass``). The arXiv id is always recorded in
    ``eprint`` so :func:`pynakes.identity.entry_arxiv_id` and dedup recognize it
    in either form.
    """
    metadata = arxiv.metadata_from_record(record, dialect=dialect)
    return entry_from_metadata(metadata)


def fetch_arxiv_record(identifier: str, fetcher: FetchArxivAtom | None = None) -> ArxivRecord:
    """Fetch and parse arXiv metadata for ``identifier``.

    Delegates fetch/parse to :mod:`pynakes.providers.repositories.arxiv`. The default Atom
    fetcher is this module's :func:`fetch_arxiv_atom` wrapper so callers and
    tests can substitute it; provider errors become :class:`ArxivImportError`.
    """
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivImportError(f"Malformed arXiv identifier: {identifier!r}")
    if fetcher is None:
        fetcher = fetch_arxiv_atom
    try:
        return arxiv.fetch_record(normalized, fetcher=fetcher)
    except ProviderFetchError as exc:
        raise ArxivImportError(str(exc)) from exc


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
    try:
        metadata = get_import_provider(DOI).load(normalized, "bibtex", fetcher)
    except ProviderFetchError as exc:
        raise DOIImportError(str(exc)) from exc
    entry = entry_from_metadata(metadata)
    provider_key = metadata.provider_key

    _assign_key(entry, lib, key=key, key_source=key_source, provider_key=provider_key)
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

    if fetcher is None:
        fetcher = fetch_arxiv_atom
    try:
        metadata = get_import_provider(ARXIV).load(normalized, dialect, fetcher)
    except ProviderFetchError as exc:
        raise ArxivImportError(str(exc)) from exc
    entry = entry_from_metadata(metadata)
    # arXiv feeds carry no provider citation key, so "provider" falls back to
    # generation.
    _assign_key(entry, lib, key=key, key_source=key_source, provider_key=None)
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
    metadata_fetcher: RawMetadataFetcher | None = None,
) -> tuple[str, BibEntry]:
    """Resolve ``identifier``, fetch metadata, and prepare an entry.

    Returns ``(kind, entry)``. The library is not modified.
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
    elif kind == DOI:
        entry = prepare_imported_entry(
            lib,
            normalized,
            key=key,
            key_source=key_source,
            allow_duplicate_doi=allow_duplicate,
            fetcher=doi_fetcher,
        )
    else:
        if key_source not in KEY_SOURCES:
            raise ValueError(
                f"Invalid key source {key_source!r}; expected one of: "
                f"{', '.join(sorted(KEY_SOURCES))}"
            )
        if not allow_duplicate:
            duplicate_keys = existing_keys_for_identifier(lib, kind, normalized)
            if duplicate_keys:
                raise DuplicateReferenceError(kind, normalized, duplicate_keys)
        provider = get_import_provider(kind)
        try:
            metadata = provider.load(normalized, dialect, metadata_fetcher)
        except (ProviderFetchError, ValueError) as exc:
            raise ReferenceImportError(f"{provider.name}: {exc}") from exc

        entry = entry_from_metadata(metadata)
        if not allow_duplicate:
            candidate_identifiers = WorkIdentifiers.from_pairs(
                [
                    *metadata.identifiers.items(),
                    *(
                        (item.kind, item.value)
                        for item in evidence_from_entry(entry).identifiers.items
                    ),
                ]
            )
            duplicate_keys = find_exact_matches(
                lib,
                candidate_identifiers,
            )
            if duplicate_keys:
                raise DuplicateReferenceError(kind, normalized, duplicate_keys)
        _assign_key(
            entry,
            lib,
            key=key,
            key_source=key_source,
            provider_key=metadata.provider_key,
        )
    return kind, entry
