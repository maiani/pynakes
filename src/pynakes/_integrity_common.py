"""Shared report types and entry helpers for integrity operations.

Split out of :mod:`pynakes.integrity` so that verification/enrichment and the
preprint-publication check can each import the vocabulary they share without
importing each other. Nothing here performs I/O: these are the result objects
the operations fill in, plus the small field accessors that have to agree
across all three (a "journal" that may be spelled ``journaltitle``, a DOI
comparison that has to be case-insensitive, a container title that belongs in
``booktitle`` on a chapter).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TypeVar

from pynakes._identifiers import doi_from_text, normalize_doi
from pynakes._text_utils import _normalize_text
from pynakes.entry_types import CONTAINER_FIELDS, container_field, has_container
from pynakes.keys import _first_author_last_name
from pynakes.model import BibEntry
from pynakes.progress import EntryProgress, EntryProgressEvent


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
    metadata: dict[str, str] = field(default_factory=dict)
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
    # Keys whose *preprint* record gained published metadata (a DOI, a journal,
    # an @article type) — the direction "promotion" describes.
    promoted_keys: list[str] = field(default_factory=list)
    # Keys whose *published* record gained eprint provenance pointing back at
    # its preprint. The opposite direction, and by far the commoner one on a
    # library of already-published work, so it is counted separately rather
    # than reported as a promotion.
    linked_keys: list[str] = field(default_factory=list)

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

    @property
    def promoted(self) -> int:
        """Number of preprints given their published metadata."""
        return len(self.promoted_keys)

    @property
    def linked(self) -> int:
        """Number of published entries given eprint provenance for their preprint."""
        return len(self.linked_keys)

    def to_dict(self) -> dict[str, object]:
        """Serialize the published-check report to a JSON-friendly dict."""
        return {
            "checked": self.checked,
            "published": self.published,
            "promoted": self.promoted,
            "linked": self.linked,
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


_JobItem = TypeVar("_JobItem")
_JobResult = TypeVar("_JobResult")


def _map_concurrently(
    items: list[_JobItem], fn: Callable[[_JobItem], _JobResult], *, concurrency: int
) -> list[_JobResult]:
    """Apply ``fn`` to each item, computing up to ``concurrency`` at once.

    Returns results in the same order as ``items`` regardless of completion
    order. Every caller uses this only for the network fetch itself — result
    application (report ordering, entry mutation, progress events) stays a
    separate, single-threaded pass over ``items`` in original order, so
    parallelizing the network never introduces the unstable ordering this
    project otherwise avoids in its core logic.
    """
    if not items:
        return []
    if concurrency <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(concurrency, len(items))) as executor:
        return list(executor.map(fn, items))


def _remote_container(remote: BibEntry) -> str:
    """Return the container title a provider record carries, under any spelling."""
    for field_name in CONTAINER_FIELDS:
        value = remote.fields.get(field_name, "").strip()
        if value:
            return value
    return ""


def _container_update(
    entry: BibEntry, container: str, *, dialect: str = "bibtex"
) -> tuple[str, str] | None:
    """Route a provider's container title to the field ``entry``'s type allows.

    Returns ``None`` when the entry already records a container under any
    spelling, or when its type has no container field at all. DOI content
    negotiation renders a book chapter's container into ``journal``, so copying
    it across verbatim would write a book title into a field only ``@article``
    styles read — and would duplicate a ``booktitle`` the user set deliberately.
    """
    if not container:
        return None
    target = container_field(entry.type, dialect=dialect)
    if target is None or has_container(entry.fields):
        return None
    return (target, container)


def _dois_equivalent(left: str, right: str) -> bool:
    """Compare two DOI strings the way DOIs actually compare: case-insensitively.

    ``normalize_doi`` preserves case (round-trip fidelity for display), so
    equality still needs an explicit case fold here.
    """
    try:
        return normalize_doi(left).lower() == normalize_doi(right).lower()
    except ValueError:
        return left.strip().lower() == right.strip().lower()


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


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _first_author(entry: BibEntry) -> str:
    return _first_author_last_name(entry).lower()


def _journal(entry: BibEntry) -> str:
    return entry.fields.get("journal", "").strip() or entry.fields.get("journaltitle", "").strip()


def _has_retraction_flag(entry: BibEntry) -> bool:
    haystack = " ".join(entry.fields.get(field, "") for field in ("title", "note", "annote"))
    return "retract" in haystack.lower()
