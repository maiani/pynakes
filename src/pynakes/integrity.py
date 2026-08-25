"""Integrity verification and conservative metadata enrichment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from pynakes._identifiers import (
    doi_from_text,
    normalize_arxiv,
    normalize_doi,
)
from pynakes._text_utils import _normalize_text, entry_year
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.identity import evidence_from_entry
from pynakes.keys import _first_author_last_name
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile
from pynakes.progress import EntryProgress, EntryProgressEvent
from pynakes.provider_cache import open_cache
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.identity import resolve_arxiv_id_for_doi
from pynakes.providers.metadata import aps as aps_provider
from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.preferred_metadata import preferred_metadata_provider
from pynakes.providers.repositories import arxiv as arxiv_provider


@dataclass
class IntegrityIssue:
    """One verification or enrichment finding."""

    type: str
    severity: str
    message: str
    key: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the finding to a JSON-friendly dict for CLI output."""
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "key": self.key,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class VerifyReport:
    """Result of verifying entries against DOI metadata."""

    checked: int = 0
    issues: list[IntegrityIssue] = field(default_factory=list)

    @property
    def errors(self) -> int:
        """Number of error-severity findings."""
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> int:
        """Number of warning-severity findings."""
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def infos(self) -> int:
        """Number of info-severity findings."""
        return sum(1 for issue in self.issues if issue.severity == "info")

    def to_dict(self) -> dict[str, object]:
        """Serialize the report (counts and findings) to a JSON-friendly dict."""
        return {
            "checked": self.checked,
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class FieldUpdate:
    """One field added or updated by an enrichment operation."""

    key: str
    field: str
    value: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the field update to a JSON-friendly dict."""
        return {"key": self.key, "field": self.field, "value": self.value}


@dataclass
class EnrichReport:
    """Result of conservative metadata enrichment."""

    updates: list[FieldUpdate] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed_entries(self) -> int:
        """Number of distinct entries that received an enrichment update."""
        return len({update.key for update in self.updates})

    @property
    def changed_fields(self) -> int:
        """Total number of field updates applied across all entries."""
        return len(self.updates)

    def to_dict(self) -> dict[str, object]:
        """Serialize the enrichment report to a JSON-friendly dict."""
        return {
            "changed_entries": self.changed_entries,
            "changed_fields": self.changed_fields,
            "updates": [update.to_dict() for update in self.updates],
        }


@dataclass
class PublishedCandidate:
    """A preprint that may have published metadata available."""

    key: str
    source: str
    identifier: str
    status: str
    doi: str | None = None
    journal: str | None = None
    arxiv_id: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize the candidate to a JSON-friendly dict."""
        return {
            "key": self.key,
            "source": self.source,
            "identifier": self.identifier,
            "status": self.status,
            "doi": self.doi,
            "journal": self.journal,
            "arxiv_id": self.arxiv_id,
            "message": self.message,
        }


@dataclass
class PublishedReport:
    """Result of checking preprints for published metadata."""

    candidates: list[PublishedCandidate] = field(default_factory=list)
    updates: list[FieldUpdate] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def checked(self) -> int:
        """Number of preprint candidates examined."""
        return len(self.candidates)

    @property
    def published(self) -> int:
        """Number of candidates found to have published metadata available."""
        return sum(1 for c in self.candidates if c.status in {"published", "published_present"})

    @property
    def changed_entries(self) -> int:
        """Number of distinct entries that received a published-metadata update."""
        return len({update.key for update in self.updates})

    def to_dict(self) -> dict[str, object]:
        """Serialize the published-check report to a JSON-friendly dict."""
        return {
            "checked": self.checked,
            "published": self.published,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "updates": [update.to_dict() for update in self.updates],
        }


@dataclass
class FieldComparison:
    """One field where a local entry and the other side of a comparison disagree.

    ``local`` is ``None`` when the entry has no value at all for the field
    (a gap the other side can fill); otherwise it's the current value the
    other one would replace. ``other`` is always non-empty — see
    :func:`_diff_fields`.
    """

    field: str
    local: str | None
    other: str

    def to_dict(self) -> dict[str, str | None]:
        """Serialize the comparison to a JSON-friendly dict."""
        return {"field": self.field, "local": self.local, "other": self.other}


@dataclass
class EntryComparisonReport:
    """Per-field comparison of one entry against another reference, for manual review.

    Read-only: never mutates either side. ``fields`` lists only fields where
    the other side's value is non-empty and differs from the local one — an
    identical field isn't worth reviewing, and a blank field on the other side
    has nothing to offer. ``source`` identifies what the entry was compared
    against: ``"doi"`` or ``"arxiv"`` for a fetched remote record, ``"local"``
    for another entry already in a library; ``identifier`` is that source's DOI,
    arXiv id, or citation key respectively.
    """

    key: str
    source: str | None = None
    identifier: str | None = None
    fields: list[FieldComparison] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the comparison report to a JSON-friendly dict."""
        return {
            "key": self.key,
            "source": self.source,
            "identifier": self.identifier,
            "fields": [comparison.to_dict() for comparison in self.fields],
            "warnings": self.warnings,
        }


class MetadataFetchError(Exception):
    """Raised when authoritative metadata cannot be fetched or parsed."""


_PREPRINT_DOI_PREFIXES = ("10.1101/", "10.21203/", "10.2139/")

# Fields worth surfacing in an entry comparison. Deliberately the
# same conservative, citation-relevant set `_missing_field_updates` fills,
# plus `abstract` (arXiv's richest field) and `eprint` (an arXiv id worth
# recording even when the entry was already found by DOI).
_COMPARE_FIELDS = (
    "title",
    "author",
    "editor",
    "year",
    "date",
    "volume",
    "number",
    "pages",
    "journal",
    "journaltitle",
    "publisher",
    "numpages",
    "isbn",
    "doi",
    "pmid",
    "pmcid",
    "eprint",
    "abstract",
    "url",
)


def _emit_progress(progress: EntryProgress | None, event: EntryProgressEvent) -> None:
    if progress is not None:
        progress(event)


def verify_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_file: str | Path | None = None,
    progress: EntryProgress | None = None,
) -> VerifyReport:
    """Verify DOI-backed entries against provider metadata.

    Network access is never implicit. With ``online=False``, DOI entries are
    only syntax-checked and reported as unchecked.
    """
    report = VerifyReport()
    entry_total = len(lib.entries)
    for index, entry in enumerate(lib.entries.values(), start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            report.issues.append(
                IntegrityIssue(
                    "malformed_doi",
                    "error",
                    f"Entry {entry.key!r} has a malformed DOI",
                    entry.key,
                    "doi",
                    actual=doi,
                )
            )
            continue

        if not online:
            report.issues.append(
                IntegrityIssue(
                    "doi_not_checked",
                    "info",
                    "Pass --online to verify this DOI against provider metadata",
                    entry.key,
                    "doi",
                    actual=normalized,
                )
            )
            continue

        try:
            remote = fetch_doi_entry(normalized, cache_file=cache_file)
        except MetadataFetchError as exc:
            issue_type = (
                "provider_error"
                if isinstance(exc.__cause__, ProviderFetchError)
                else "doi_unresolved"
            )
            report.issues.append(
                IntegrityIssue(issue_type, "error", str(exc), entry.key, "doi", actual=doi)
            )
            continue

        report.checked += 1
        report.issues.extend(_compare_entry(entry, remote))
    return report


def enrich_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_file: str | Path | None = None,
    progress: EntryProgress | None = None,
) -> EnrichReport:
    """Fill missing fields from local DOI URLs and DOI provider metadata."""
    report = EnrichReport()
    entry_total = len(lib.entries)
    for index, entry in enumerate(lib.entries.values(), start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            inferred = _doi_from_entry_urls(entry)
            if inferred and set_entry_field(entry, "doi", inferred):
                report.updates.append(FieldUpdate(entry.key, "doi", inferred))
                doi = inferred

        if not doi:
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            report.warnings.append(
                {"type": "malformed_doi", "key": entry.key, "message": f"Malformed DOI: {doi!r}"}
            )
            continue
        if not online:
            continue

        remote = None
        provider = preferred_metadata_provider(
            entry.fields.get("journal") or entry.fields.get("journaltitle")
        )
        if provider == "aps":
            try:
                remote = aps_provider.fetch_entry(
                    normalized,
                    entry.fields.get("journal") or entry.fields.get("journaltitle"),
                    cache_file=cache_file,
                )
            except ProviderFetchError as exc:
                report.warnings.append(
                    {
                        "type": "preferred_provider_unresolved",
                        "key": entry.key,
                        "message": f"Could not fetch APS Harvest metadata for DOI "
                        f"{normalized!r}: {exc}",
                    }
                )
        if remote is None:
            try:
                remote = fetch_doi_entry(normalized, cache_file=cache_file)
            except MetadataFetchError as exc:
                report.warnings.append(
                    {"type": "doi_unresolved", "key": entry.key, "message": str(exc)}
                )
                continue
        for field_name, value in _missing_field_updates(entry, remote):
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

    arxiv_id = _entry_arxiv_id(entry)
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


def check_published(
    lib: BibFile,
    *,
    online: bool = False,
    apply: bool = False,
    cache_file: str | Path | None = None,
    openalex_fetcher: Callable[[str], dict | None] | None = None,
    semantic_scholar_fetcher: Callable[[str], dict | None] | None = None,
    progress: EntryProgress | None = None,
) -> PublishedReport:
    """Detect preprints and optionally apply published DOI/journal metadata."""
    report = PublishedReport()
    dialect = library_dialect(lib)
    entry_total = len(lib.entries)
    for index, entry in enumerate(lib.entries.values(), start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        preprint = _preprint_identity(entry)
        if preprint is None:
            if online:
                _check_doi_to_arxiv_backfill(
                    entry,
                    report,
                    apply=apply,
                    dialect=dialect,
                    cache_file=cache_file,
                    openalex_fetcher=openalex_fetcher,
                    semantic_scholar_fetcher=semantic_scholar_fetcher,
                )
            continue
        source, identifier = preprint
        existing_doi = entry.fields.get("doi", "").strip()
        existing_journal = _journal(entry)
        if existing_doi and existing_journal:
            candidate = PublishedCandidate(
                entry.key,
                source,
                identifier,
                "published_present",
                doi=existing_doi,
                journal=existing_journal,
                message="Entry already has DOI and journal metadata",
            )
            report.candidates.append(candidate)
            if apply:
                _apply_published_candidate(entry, candidate, report)
            continue
        if not online:
            report.candidates.append(
                PublishedCandidate(
                    entry.key,
                    source,
                    identifier,
                    "unchecked",
                    message="Pass --online to check authoritative preprint metadata",
                )
            )
            continue
        if source != "arxiv":
            report.candidates.append(
                PublishedCandidate(
                    entry.key,
                    source,
                    identifier,
                    "unsupported_source",
                    message="Online published-version lookup currently supports arXiv metadata",
                )
            )
            continue

        try:
            arxiv = fetch_arxiv_metadata(identifier, cache_file=cache_file)
        except MetadataFetchError as exc:
            report.warnings.append(
                {"type": "preprint_lookup_failed", "key": entry.key, "message": str(exc)}
            )
            continue
        status = "published" if arxiv.get("doi") or arxiv.get("journal") else "not_found"
        candidate = PublishedCandidate(
            entry.key,
            source,
            identifier,
            status,
            doi=arxiv.get("doi"),
            journal=arxiv.get("journal"),
            message="Published metadata found"
            if status == "published"
            else "No published metadata found",
        )
        report.candidates.append(candidate)
        if apply and status == "published":
            _apply_published_candidate(entry, candidate, report)
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


def _fetch_arxiv_record(
    identifier: str, *, cache_file: str | Path | None = None
) -> arxiv_provider.ArxivRecord:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise MetadataFetchError(f"Malformed arXiv identifier: {identifier!r}")
    cache = open_cache(cache_file)
    try:
        text = cache.get("arxiv", normalized, "xml")
        if text is None:
            text = arxiv_provider.fetch_atom(normalized)
            cache.put("arxiv", normalized, "xml", text)
        return arxiv_provider.parse_atom(text, normalized)
    except ProviderFetchError as exc:
        raise MetadataFetchError(str(exc)) from exc


def fetch_arxiv_metadata(
    identifier: str, *, cache_file: str | Path | None = None
) -> dict[str, str]:
    """Fetch the published DOI/journal an arXiv preprint links to, if any.

    Delegates fetch/parse to :mod:`pynakes.providers.repositories.arxiv` and keeps
    only the cache lookup here. Returns ``{"doi": ..., "journal": ...}``.
    """
    record = _fetch_arxiv_record(identifier, cache_file=cache_file)
    return {"doi": record.doi, "journal": record.journal}


def _fetch_arxiv_fields(identifier: str, *, cache_file: str | Path | None = None) -> dict[str, str]:
    """Fetch arXiv metadata as BibTeX-style field names, for field comparison."""
    record = _fetch_arxiv_record(identifier, cache_file=cache_file)
    fields: dict[str, str] = {"eprint": record.arxiv_id}
    if record.title:
        fields["title"] = record.title
    if record.authors:
        fields["author"] = " and ".join(record.authors)
    if record.published:
        fields["year"] = record.published[:4]
    if record.doi:
        fields["doi"] = record.doi
    if record.journal:
        fields["journal"] = record.journal
    if record.summary:
        fields["abstract"] = record.summary
    return fields


def _compare_entry(local: BibEntry, remote: BibEntry) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    local_title = local.fields.get("title", "")
    remote_title = remote.fields.get("title", "")
    if local_title and remote_title and _similarity(local_title, remote_title) < 0.86:
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


def _missing_field_updates(entry: BibEntry, remote: BibEntry) -> list[tuple[str, str]]:
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
    if not entry.fields.get("journal") and not entry.fields.get("journaltitle"):
        journal = remote.fields.get("journal") or remote.fields.get("journaltitle")
        if journal:
            updates.append(("journal", journal))
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
            elif local_value == other_value:
                continue
        comparisons.append(FieldComparison(field_name, local_value or None, other_value))
    return comparisons


def _dois_equivalent(left: str, right: str) -> bool:
    """Compare two DOI strings the way DOIs actually compare: case-insensitively.

    ``normalize_doi`` preserves case (round-trip fidelity for display), so
    equality still needs an explicit case fold here.
    """
    try:
        return normalize_doi(left).lower() == normalize_doi(right).lower()
    except ValueError:
        return left.strip().lower() == right.strip().lower()


def _apply_published_candidate(
    entry: BibEntry, candidate: PublishedCandidate, report: PublishedReport
) -> None:
    if candidate.doi and not entry.fields.get("doi"):
        try:
            value = normalize_doi(candidate.doi)
        except ValueError:
            value = candidate.doi
        if set_entry_field(entry, "doi", value):
            report.updates.append(FieldUpdate(entry.key, "doi", value))
    if candidate.journal and not _journal(entry):
        if set_entry_field(entry, "journal", candidate.journal):
            report.updates.append(FieldUpdate(entry.key, "journal", candidate.journal))
    if entry.type.lower() in {"misc", "online", "unpublished"} and (
        candidate.doi or candidate.journal
    ):
        if set_entry_type(entry, "article"):
            report.updates.append(FieldUpdate(entry.key, "type", "article"))


def _check_doi_to_arxiv_backfill(
    entry: BibEntry,
    report: PublishedReport,
    *,
    apply: bool,
    dialect: str,
    cache_file: str | Path | None,
    openalex_fetcher: Callable[[str], dict | None] | None,
    semantic_scholar_fetcher: Callable[[str], dict | None] | None,
) -> None:
    doi = entry.fields.get("doi", "").strip()
    if not doi:
        return
    try:
        normalized = normalize_doi(doi)
    except ValueError:
        return

    try:
        arxiv_id = resolve_arxiv_id_for_doi(
            normalized,
            cache_file=cache_file,
            openalex_fetcher=openalex_fetcher,
            semantic_scholar_fetcher=semantic_scholar_fetcher,
        )
    except ProviderFetchError as exc:
        report.warnings.append(
            {"type": "doi_to_arxiv_lookup_failed", "key": entry.key, "message": str(exc)}
        )
        return

    if arxiv_id is None:
        report.candidates.append(
            PublishedCandidate(
                entry.key,
                "doi",
                normalized,
                "not_found",
                doi=normalized,
                message="No arXiv id found in OpenAlex or Semantic Scholar",
            )
        )
        return

    candidate = PublishedCandidate(
        entry.key,
        "doi",
        normalized,
        "arxiv_found",
        doi=normalized,
        arxiv_id=arxiv_id,
        message="arXiv identity found",
    )
    report.candidates.append(candidate)
    if apply:
        _apply_arxiv_backfill_candidate(entry, candidate, report, dialect)


def _apply_arxiv_backfill_candidate(
    entry: BibEntry,
    candidate: PublishedCandidate,
    report: PublishedReport,
    dialect: str,
) -> None:
    if not candidate.arxiv_id:
        return

    existing_eprint = _field_value(entry, "eprint").strip()
    if existing_eprint:
        existing_arxiv = normalize_arxiv(existing_eprint)
        if existing_arxiv != candidate.arxiv_id:
            return
    elif set_entry_field(entry, "eprint", candidate.arxiv_id):
        report.updates.append(FieldUpdate(entry.key, "eprint", candidate.arxiv_id))

    archive_field = "eprinttype" if dialect == "biblatex" else "archiveprefix"
    archive_value = "arxiv" if dialect == "biblatex" else "arXiv"
    if not _field_value(entry, archive_field).strip():
        if set_entry_field(entry, archive_field, archive_value):
            report.updates.append(FieldUpdate(entry.key, archive_field, archive_value))


def _field_value(entry: BibEntry, field_name: str) -> str:
    target = field_name.lower()
    for name, value in entry.fields.items():
        if name.lower() == target:
            return value
    return ""


def _doi_from_entry_urls(entry: BibEntry) -> str | None:
    for field_name in ("url", "howpublished", "note"):
        normalized = doi_from_text(entry.fields.get(field_name, ""))
        if normalized is not None:
            return normalized
    return None


def _preprint_identity(entry: BibEntry) -> tuple[str, str] | None:
    identifiers = evidence_from_entry(entry).identifiers.by_kind()
    if arxiv := identifiers.get("arxiv"):
        return "arxiv", sorted(arxiv)[0]
    if doi := identifiers.get("doi"):
        normalized = sorted(doi)[0]
        if normalized.startswith(_PREPRINT_DOI_PREFIXES):
            return "preprint_doi", normalized
    if ssrn := identifiers.get("ssrn"):
        return "ssrn", sorted(ssrn)[0]
    url = " ".join(entry.fields.get(field, "") for field in ("url", "howpublished", "note")).lower()
    if "ssrn.com" in url:
        return "ssrn", url
    return None


def _entry_arxiv_id(entry: BibEntry) -> str | None:
    identifiers = evidence_from_entry(entry).identifiers.by_kind()
    if arxiv := identifiers.get("arxiv"):
        return sorted(arxiv)[0]
    return None


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _first_author(entry: BibEntry) -> str:
    return _first_author_last_name(entry).lower()


def _journal(entry: BibEntry) -> str:
    return entry.fields.get("journal", "").strip() or entry.fields.get("journaltitle", "").strip()


def _has_retraction_flag(entry: BibEntry) -> bool:
    haystack = " ".join(entry.fields.get(field, "") for field in ("title", "note", "annote"))
    return "retract" in haystack.lower()
