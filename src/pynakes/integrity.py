"""Integrity verification and conservative metadata enrichment.

Three provider-backed operations over a library, all offline unless explicitly
asked to go online:

``verify_library``
    Compare entries against authoritative DOI metadata and report differences.
``enrich_library``
    Fill *missing* fields from that metadata, never overwriting what is there.
``check_published``
    Detect preprints and apply published metadata — re-exported from
    :mod:`pynakes._integrity_published`, which owns that operation.

The report types and shared field helpers live in
:mod:`pynakes._integrity_common`; this module re-exports them so
``pynakes.integrity`` remains the single import site for callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pynakes._identifiers import normalize_doi
from pynakes._integrity_common import (
    _COMPARE_FIELDS,
    EnrichReport,
    EntryComparisonReport,
    FieldComparison,
    FieldUpdate,
    IntegrityIssue,
    MetadataFetchError,
    PublishedCandidate,
    PublishedReport,
    VerifyReport,
    _container_update,
    _doi_from_entry_urls,
    _dois_equivalent,
    _emit_progress,
    _field_value,
    _first_author,
    _has_retraction_flag,
    _map_concurrently,
    _remote_container,
)
from pynakes._integrity_published import (
    _fetch_arxiv_fields,
    check_published,
    fetch_arxiv_metadata,
)
from pynakes._text_utils import entry_year, title_similarity
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.editing import set_entry_field
from pynakes.entry_types import container_title
from pynakes.identity import entry_arxiv_id
from pynakes.journals import _journal_titles_equivalent
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile
from pynakes.progress import EntryProgress, EntryProgressEvent
from pynakes.provider_cache import open_cache
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import aps as aps_provider
from pynakes.providers.metadata import crossref as crossref_provider
from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.preferred_metadata import preferred_metadata_provider

__all__ = [
    "EnrichReport",
    "EntryComparisonReport",
    "FieldComparison",
    "FieldUpdate",
    "IntegrityIssue",
    "MetadataFetchError",
    "PublishedCandidate",
    "PublishedReport",
    "VerifyReport",
    "check_published",
    "compare_entries",
    "compare_entry_with_remote",
    "enrich_library",
    "fetch_arxiv_metadata",
    "fetch_doi_entry",
    "verify_library",
]


def _verify_fetch_job(args: tuple[str, str | Path | None]) -> BibEntry | MetadataFetchError:
    normalized, cache_file = args
    try:
        return fetch_doi_entry(normalized, cache_file=cache_file)
    except MetadataFetchError as exc:
        return exc


def verify_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_file: str | Path | None = None,
    progress: EntryProgress | None = None,
    concurrency: int = 1,
) -> VerifyReport:
    """Verify DOI-backed entries against provider metadata.

    Network access is never implicit. With ``online=False``, DOI entries are
    only syntax-checked and reported as unchecked. ``concurrency`` bounds how
    many DOI lookups run at once; report ordering and progress events always
    follow the library's own entry order regardless of fetch completion order.
    """
    report = VerifyReport()
    entries = list(lib.entries.values())
    entry_total = len(entries)

    # kind in {"no_doi", "malformed", "offline", "fetch"}; data carries the
    # DOI text needed to finish that entry once fetch results are in.
    plan: list[tuple[str, str | None]] = []
    fetch_positions: list[int] = []
    fetch_jobs: list[tuple[str, str | Path | None]] = []

    for pos, entry in enumerate(entries):
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            plan.append(("no_doi", None))
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            plan.append(("malformed", doi))
            continue
        if not online:
            plan.append(("offline", normalized))
            continue
        plan.append(("fetch", doi))
        fetch_positions.append(pos)
        fetch_jobs.append((normalized, cache_file))

    fetch_results = _map_concurrently(fetch_jobs, _verify_fetch_job, concurrency=concurrency)
    result_by_pos = dict(zip(fetch_positions, fetch_results))

    for index, entry in enumerate(entries, start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        kind, data = plan[index - 1]
        if kind == "no_doi":
            continue
        if kind == "malformed":
            report.issues.append(
                IntegrityIssue(
                    "malformed_doi",
                    "error",
                    f"Entry {entry.key!r} has a malformed DOI",
                    entry.key,
                    "doi",
                    actual=data,
                )
            )
            continue
        if kind == "offline":
            report.issues.append(
                IntegrityIssue(
                    "doi_not_checked",
                    "info",
                    "Pass --online to verify this DOI against provider metadata",
                    entry.key,
                    "doi",
                    actual=data,
                )
            )
            continue

        result = result_by_pos[index - 1]
        if isinstance(result, MetadataFetchError):
            issue_type = (
                "provider_error"
                if isinstance(result.__cause__, ProviderFetchError)
                else "doi_unresolved"
            )
            report.issues.append(
                IntegrityIssue(issue_type, "error", str(result), entry.key, "doi", actual=data)
            )
            continue

        report.checked += 1
        report.issues.extend(_compare_entry(entry, result))
    return report


@dataclass
class _EnrichFetchResult:
    """Result of one entry's remote-metadata fetch, for the sequential apply pass."""

    remote: BibEntry | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)


def _enrich_fetch_job(
    args: tuple[str, str | None, str, str | Path | None],
) -> _EnrichFetchResult:
    normalized, journal, key, cache_file = args
    result = _EnrichFetchResult()
    if preferred_metadata_provider(journal) == "aps":
        try:
            result.remote = aps_provider.fetch_entry(normalized, journal, cache_file=cache_file)
        except ProviderFetchError as exc:
            result.warnings.append(
                {
                    "type": "preferred_provider_unresolved",
                    "key": key,
                    "message": f"Could not fetch APS Harvest metadata for DOI "
                    f"{normalized!r}: {exc}",
                }
            )
    if result.remote is None:
        try:
            result.remote = fetch_doi_entry(normalized, cache_file=cache_file)
        except MetadataFetchError as exc:
            result.warnings.append({"type": "doi_unresolved", "key": key, "message": str(exc)})
    if result.remote is not None and crossref_provider.lacks_article_locator(result.remote.fields):
        try:
            work = crossref_provider.fetch_work_by_doi(normalized, cache_file=cache_file)
            if work:
                structured = crossref_provider.metadata_from_work(work, normalized, "bibtex")
                for field_name, value in structured.fields.items():
                    result.remote.fields.setdefault(field_name, value)
        except ProviderFetchError as exc:
            result.warnings.append(
                {
                    "type": "crossref_supplement_unresolved",
                    "key": key,
                    "message": f"Could not supplement DOI {normalized!r} from Crossref: {exc}",
                }
            )
    return result


def enrich_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_file: str | Path | None = None,
    progress: EntryProgress | None = None,
    concurrency: int = 1,
) -> EnrichReport:
    """Fill missing fields from local DOI URLs and DOI provider metadata.

    ``concurrency`` bounds how many remote lookups run at once; field updates
    are still applied in the library's own entry order regardless of fetch
    completion order, so the result is identical to a serial run either way.
    """
    report = EnrichReport()
    dialect = library_dialect(lib)
    entries = list(lib.entries.values())
    entry_total = len(entries)

    # kind in {"no_doi", "malformed", "offline", "fetch"}; data carries the
    # DOI text for a warning message, unused otherwise.
    plan: list[tuple[str, str | None]] = []
    fetch_positions: list[int] = []
    fetch_jobs: list[tuple[str, str | None, str, str | Path | None]] = []

    for pos, entry in enumerate(entries):
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            inferred = _doi_from_entry_urls(entry)
            if inferred and set_entry_field(entry, "doi", inferred):
                report.updates.append(FieldUpdate(entry.key, "doi", inferred))
                doi = inferred

        if not doi:
            plan.append(("no_doi", None))
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            plan.append(("malformed", doi))
            continue
        if not online:
            plan.append(("offline", None))
            continue

        plan.append(("fetch", None))
        journal = container_title(entry.fields) or None
        fetch_positions.append(pos)
        fetch_jobs.append((normalized, journal, entry.key, cache_file))

    fetch_results = _map_concurrently(fetch_jobs, _enrich_fetch_job, concurrency=concurrency)
    result_by_pos = dict(zip(fetch_positions, fetch_results))

    for index, entry in enumerate(entries, start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        kind, data = plan[index - 1]
        if kind in ("no_doi", "offline"):
            continue
        if kind == "malformed":
            report.warnings.append(
                {"type": "malformed_doi", "key": entry.key, "message": f"Malformed DOI: {data!r}"}
            )
            continue

        result = result_by_pos[index - 1]
        report.warnings.extend(result.warnings)
        if result.remote is None:
            continue
        for field_name, value in _missing_field_updates(entry, result.remote, dialect=dialect):
            if set_entry_field(entry, field_name, value):
                report.updates.append(FieldUpdate(entry.key, field_name, value))
    return report


def compare_entry_with_remote(
    entry: BibEntry,
    *,
    online: bool = False,
    cache_file: str | Path | None = None,
) -> EntryComparisonReport:
    """Fetch remote metadata for one entry and compare it field by field.

    Unlike :func:`enrich_library`, this never writes to ``entry`` — it's for
    a caller (e.g. an interactive UI) to review the differences and apply
    only the fields they choose, through the normal surgical field-edit path.
    Prefers the entry's DOI (existing or inferred from a local URL); falls
    back to an arXiv id when no DOI is available or resolvable. See
    :func:`compare_entries` for comparing two already-local entries instead.
    """
    report = EntryComparisonReport(key=entry.key)
    if not online:
        report.warnings.append(
            {
                "type": "offline",
                "key": entry.key,
                "message": "Pass online=True (--online) to fetch remote metadata",
            }
        )
        return report

    doi = entry.fields.get("doi", "").strip() or _doi_from_entry_urls(entry) or ""
    if doi:
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            report.warnings.append(
                {"type": "malformed_doi", "key": entry.key, "message": f"Malformed DOI: {doi!r}"}
            )
        else:
            try:
                remote = fetch_doi_entry(normalized, cache_file=cache_file)
            except MetadataFetchError as exc:
                report.warnings.append(
                    {"type": "doi_unresolved", "key": entry.key, "message": str(exc)}
                )
            else:
                report.source = "doi"
                report.identifier = normalized
                report.fields = _diff_fields(entry, remote.fields)
                return report

    arxiv_id = entry_arxiv_id(entry)
    if arxiv_id:
        try:
            remote_fields = _fetch_arxiv_fields(arxiv_id, cache_file=cache_file)
        except MetadataFetchError as exc:
            report.warnings.append(
                {"type": "arxiv_unresolved", "key": entry.key, "message": str(exc)}
            )
        else:
            report.source = "arxiv"
            report.identifier = arxiv_id
            report.fields = _diff_fields(entry, remote_fields)
            return report

    if not doi and not arxiv_id:
        report.warnings.append(
            {
                "type": "no_identifier",
                "key": entry.key,
                "message": "No DOI or arXiv id found for this entry",
            }
        )
    return report


def compare_entries(entry: BibEntry, other: BibEntry) -> EntryComparisonReport:
    """Compare two already-local entries field by field, for manual review.

    Unlike :func:`compare_entry_with_remote`, both sides are entries already
    loaded from a library — no network access, no DOI/arXiv resolution. Useful
    for reviewing a candidate duplicate pair before merging, or any other
    two-reference comparison where fetching a remote record doesn't apply.
    """
    report = EntryComparisonReport(key=entry.key, source="local", identifier=other.key)
    report.fields = _diff_fields(entry, other.fields)
    return report


def fetch_doi_entry(doi: str, *, cache_file: str | Path | None = None) -> BibEntry:
    """Fetch DOI BibTeX metadata, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    cache = open_cache(cache_file)
    text = cache.get("doi", normalized, "bib")
    if text is None:
        try:
            text = doi_provider.fetch_bibtex(normalized)
        except ProviderFetchError as exc:
            raise MetadataFetchError(
                f"Could not fetch DOI {normalized!r} via doi.org content negotiation: {exc}"
            ) from exc
        cache.put("doi", normalized, "bib", text)

    try:
        entries = parse_bib(text).entries.values()
    except ParseError as exc:
        cache.drop("doi", normalized, "bib")
        raise MetadataFetchError(
            f"Provider returned invalid BibTeX for {normalized}: {exc}"
        ) from exc
    if not entries:
        raise MetadataFetchError(f"Provider returned no BibTeX for {normalized}")
    return entries[0]


def _compare_entry(local: BibEntry, remote: BibEntry) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    local_title = local.fields.get("title", "")
    remote_title = remote.fields.get("title", "")
    if local_title and remote_title and title_similarity(local_title, remote_title) < 0.86:
        issues.append(
            IntegrityIssue(
                "title_mismatch",
                "error",
                "Local title does not match DOI provider title",
                local.key,
                "title",
                expected=remote_title,
                actual=local_title,
            )
        )
    local_year = entry_year(local)
    remote_year = entry_year(remote)
    if local_year and remote_year and local_year != remote_year:
        issues.append(
            IntegrityIssue(
                "year_mismatch",
                "warning",
                "Local year does not match DOI provider year",
                local.key,
                "year",
                expected=remote_year,
                actual=local_year,
            )
        )
    local_author = _first_author(local)
    remote_author = _first_author(remote)
    if local_author and remote_author and local_author != remote_author:
        issues.append(
            IntegrityIssue(
                "author_mismatch",
                "warning",
                "Local first author does not match DOI provider first author",
                local.key,
                "author",
                expected=remote_author,
                actual=local_author,
            )
        )
    if _has_retraction_flag(remote):
        issues.append(
            IntegrityIssue(
                "retraction_flag",
                "error",
                "DOI provider metadata appears to flag this work as retracted",
                local.key,
                "doi",
            )
        )
    return issues


def _missing_field_updates(
    entry: BibEntry, remote: BibEntry, *, dialect: str = "bibtex"
) -> list[tuple[str, str]]:
    updates: list[tuple[str, str]] = []
    for field_name in (
        "title",
        "author",
        "editor",
        "volume",
        "number",
        "pages",
        "numpages",
        "month",
        "publisher",
        "isbn",
        "url",
    ):
        value = remote.fields.get(field_name, "").strip()
        if value and not entry.fields.get(field_name, "").strip():
            updates.append((field_name, value))
    container = _container_update(entry, _remote_container(remote), dialect=dialect)
    if container is not None:
        updates.append(container)
    if not entry.fields.get("year") and not entry.fields.get("date"):
        date = remote.fields.get("date") or remote.fields.get("year")
        if date:
            updates.append(("date" if "-" in date else "year", date))
    for field_name in ("doi", "pmid", "pmcid"):
        value = remote.fields.get(field_name, "").strip()
        if value and not entry.fields.get(field_name, "").strip():
            updates.append((field_name, value))
    return updates


def _diff_fields(entry: BibEntry, other_fields: Mapping[str, str]) -> list[FieldComparison]:
    """List :data:`_COMPARE_FIELDS` where a non-empty ``other_fields`` value differs from local."""
    comparisons: list[FieldComparison] = []
    for field_name in _COMPARE_FIELDS:
        other_value = (other_fields.get(field_name) or "").strip()
        if not other_value:
            continue
        local_value = _field_value(entry, field_name).strip()
        if local_value:
            if field_name == "doi":
                if _dois_equivalent(local_value, other_value):
                    continue
            elif field_name in {"journal", "journaltitle"}:
                if _journal_titles_equivalent(local_value, other_value):
                    continue
            elif local_value == other_value:
                continue
        comparisons.append(FieldComparison(field_name, local_value or None, other_value))
    return comparisons
