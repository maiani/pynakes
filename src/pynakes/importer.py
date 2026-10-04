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

import re
from collections.abc import Callable
from dataclasses import replace

from pynakes._identifiers import (
    arxiv_doi,
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
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile
from pynakes.providers._http import DEFAULT_TIMEOUT, ProviderFetchError
from pynakes.providers.metadata import (
    acl_anthology,
    crossref,
    datacite,
    dblp,
    iacr,
    inspire,
    openalex,
    semantic_scholar,
    zbmath,
)
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
    resolve_reference_url,
    url_resolution_hint,
)

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
CROSSREF = "crossref"
DATACITE = "datacite"
OPENALEX = "openalex"
SEMANTIC_SCHOLAR = "semantic_scholar"
IACR = "iacr"
ZBMATH = "zbmath"


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

# A bare "RFC 9110" / "rfc9110" / "RFC-9110" spelling is unambiguous: no other
# supported identifier kind uses the "rfc" word, so it needs no prefix.
_BARE_RFC_RE = re.compile(r"^rfc[\s-]?(\d+)$", re.IGNORECASE)
_RFC_NUMBER_RE = re.compile(r"^\d+$")


def _normalize_rfc_number(value: str) -> str:
    """Normalize an ``RFC:<number>`` prefix's payload to the RFC's DOI.

    The DOI is unpadded (``10.17487/rfc791``, not ``10.17487/rfc0791``): the
    padded form is only a 301 alias, and for the lowest-numbered RFCs it does
    not resolve at all, so any padding supplied is stripped via ``int()``.
    """
    digits = value.strip()
    if not _RFC_NUMBER_RE.match(digits):
        raise ValueError(f"Malformed RFC number: {value!r}")
    return normalize_doi(f"10.17487/rfc{int(digits)}")


# --- identifier resolution -------------------------------------------------


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
        ("crossref:", CROSSREF, crossref.normalize_identifier),
        ("datacite:", DATACITE, datacite.normalize_identifier),
        ("openalex:", OPENALEX, openalex.normalize_identifier),
        ("semanticscholar:", SEMANTIC_SCHOLAR, semantic_scholar.normalize_identifier),
        ("iacr:", IACR, iacr.normalize_identifier),
        ("zbmath:", ZBMATH, zbmath.normalize_identifier),
        ("rfc:", DOI, _normalize_rfc_number),
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

    # A bare RFC number ("RFC 9110", "rfc9110", "RFC-9110").
    bare_rfc = _BARE_RFC_RE.match(raw)
    if bare_rfc is not None:
        return DOI, normalize_doi(f"10.17487/rfc{int(bare_rfc.group(1))}")

    # A recognized host whose article URLs carry no recoverable identifier.
    hint = url_resolution_hint(raw)
    if hint is not None:
        raise UnsupportedIdentifierError(f"Cannot resolve {value!r}: {hint}")

    raise UnsupportedIdentifierError(
        f"Unrecognized identifier {value!r}; expected a DOI, arXiv id, ISBN, "
        "provider-prefixed identifier, or supported repository/catalogue/publisher URL"
    )


def fetch_bibtex_for_doi(doi: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch BibTeX metadata for ``doi`` via DOI content negotiation.

    Thin domain wrapper over :func:`pynakes.providers.metadata.doi.fetch_bibtex` that
    translates provider transport errors into :class:`DOIImportError`.
    """
    try:
        return doi_provider.fetch_bibtex(doi, timeout=timeout)
    except ProviderFetchError as exc:
        raise DOIImportError(str(exc)) from exc


def fetch_crossref_work(doi: str) -> dict | None:
    """Fetch Crossref's structured work record for ``doi``. Split out so tests can stub it."""
    return crossref.fetch_work_by_doi(doi)


def _with_crossref_locator(metadata: ReferenceMetadata, doi: str) -> ReferenceMetadata:
    """Add the article number DOI BibTeX drops, from Crossref's structured record.

    See :func:`~pynakes.providers.metadata.crossref.lacks_article_locator`. Best
    effort: the import stands on the registrar's own BibTeX, so a Crossref
    failure leaves the record as it came rather than failing the import.
    """
    if not crossref.lacks_article_locator(metadata.fields):
        return metadata
    try:
        work = fetch_crossref_work(doi)
    except ProviderFetchError:
        return metadata
    locator = crossref.article_locator(work) if work else ""
    if not locator:
        return metadata
    return replace(metadata, fields={**metadata.fields, "pages": locator})


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


def fetch_arxiv_atom(identifier: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch arXiv Atom XML for ``identifier``. Split out so tests can stub it.

    Thin domain wrapper over :func:`pynakes.providers.repositories.arxiv.fetch_atom` that
    translates provider transport errors into :class:`ArxivImportError`.
    """
    try:
        return arxiv.fetch_atom(identifier, timeout=timeout)
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
    dialect: str | None = None,
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

    # As for arXiv, a second route is only taken when pynakes does the fetching.
    supplement = fetcher is None
    if fetcher is None:
        fetcher = fetch_bibtex_for_doi
    try:
        metadata = get_import_provider(DOI).load(
            normalized, dialect or library_dialect(lib), fetcher
        )
    except ProviderFetchError as exc:
        raise DOIImportError(str(exc)) from exc
    if supplement:
        metadata = _with_crossref_locator(metadata, normalized)
    entry = entry_from_metadata(metadata)
    provider_key = metadata.provider_key

    _assign_key(entry, lib, key=key, key_source=key_source, provider_key=provider_key)
    return entry


def _arxiv_metadata_via_doi(identifier: str, fetcher: FetchBibTeX | None, dialect: str):
    """Fetch arXiv metadata through DataCite, or ``None`` if that route fails too."""
    try:
        return get_import_provider(DOI).load(arxiv_doi(identifier), dialect, fetcher)
    except (ProviderFetchError, ValueError):
        return None


def _arxiv_error_message(message: str, identifier: str) -> str:
    """Name the DOI route in the failure, so the workaround is in the error itself."""
    return f"{message}. The same work is registered as DOI {arxiv_doi(identifier)}"


def prepare_imported_arxiv(
    lib: BibFile,
    identifier: str,
    *,
    dialect: str = "bibtex",
    key: str | None = None,
    key_source: str = "generated",
    allow_duplicate: bool = False,
    fetcher: FetchArxivAtom | None = None,
    doi_fetcher: FetchBibTeX | None = None,
) -> BibEntry:
    """Fetch and prepare an arXiv entry for appending to ``lib``.

    No PDFs or linked files are downloaded — only Atom metadata. The library is
    not modified.

    When arXiv's own API cannot answer — it throttles aggressively, and a busy
    period shows up as HTTP 429 or a read timeout — the same work is fetched
    from its registered DataCite DOI instead (see :func:`arxiv_doi`). That is a
    different host with different rate limits, so a throttled arXiv does not
    have to mean a failed import. The fallback runs when pynakes is doing the
    fetching itself (no injected ``fetcher``) or when ``doi_fetcher`` is given
    explicitly, so a caller that supplies its own transport keeps full control
    over what is contacted.
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

    may_fall_back = fetcher is None or doi_fetcher is not None
    if fetcher is None:
        fetcher = fetch_arxiv_atom
    try:
        metadata = get_import_provider(ARXIV).load(normalized, dialect, fetcher)
    except (ProviderFetchError, ArxivImportError) as exc:
        # The default fetcher, fetch_arxiv_atom, reports failure as ArxivImportError.
        metadata = None
        if may_fall_back:
            metadata = _arxiv_metadata_via_doi(normalized, doi_fetcher, dialect)
        if metadata is None:
            raise ArxivImportError(_arxiv_error_message(str(exc), normalized)) from exc
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
            doi_fetcher=doi_fetcher,
        )
    elif kind == DOI:
        entry = prepare_imported_entry(
            lib,
            normalized,
            dialect=dialect,
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
