"""Conservative, offline evidence for comparing bibliographic works.

This module does not assign a universal identity to a publication. It extracts
normalized identifier and metadata evidence, then classifies a comparison as
``exact``, ``probable``, ``conflict``, or ``unknown`` with explicit reasons.
Provider lookups and preprint/publication relationships remain separate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pynakes._identifiers import (
    arxiv_id_from_text,
    canonical_doi,
    normalize_arxiv,
)
from pynakes._text_utils import _normalize_text, entry_year
from pynakes.authors import last_name, split_name_list
from pynakes.model import BibEntry, BibFile

__all__ = [
    "IdentityClass",
    "MatchStatus",
    "WorkEvidence",
    "WorkIdentifier",
    "WorkIdentifiers",
    "WorkMatch",
    "compare_work_evidence",
    "entry_arxiv_id",
    "evidence_from_entry",
    "identity_class",
    "find_exact_matches",
    "normalize_work_identifier",
]

MatchStatus = Literal["exact", "probable", "conflict", "unknown"]
IdentityClass = Literal["preprint", "published", "book", "code", "unknown"]

# Entry types that decide a class on their own.
_CODE_TYPES = frozenset({"software", "dataset"})
_BOOK_TYPES = frozenset(
    {
        "book",
        "mvbook",
        "inbook",
        "bookinbook",
        "suppbook",
        "booklet",
        "collection",
        "mvcollection",
        "incollection",
        "suppcollection",
        "reference",
        "mvreference",
        "inreference",
    }
)
# Types whose venue alone establishes publication, without a volume or pages.
_PUBLISHED_TYPES = frozenset({"inproceedings", "conference", "proceedings", "mvproceedings"})
_VENUE_FIELDS = ("journal", "journaltitle", "booktitle", "eventtitle")
_LOCATOR_FIELDS = ("volume", "pages", "number", "issue", "publisher")
_PREPRINT_SERVER_FIELDS = ("biorxiv", "medrxiv", "chemrxiv", "researchsquare", "ssrn", "osf")

_ID_PRIORITY = {
    "doi": 0,
    "arxiv": 1,
    "pmid": 2,
    "pmcid": 3,
    "openalex": 4,
    "isbn": 5,
}
_DOI_KINDS = {"doi", "biorxiv", "medrxiv"}
_COMPACT_KINDS = {"pmid", "pmcid", "isbn"}
_ENTRY_IDENTIFIER_FIELDS: dict[str, tuple[str, ...]] = {
    "doi": ("doi",),
    "pmid": ("pmid",),
    "pmcid": ("pmcid",),
    "openalex": ("openalex",),
    "isbn": ("isbn",),
    "europe_pmc": ("europepmc",),
    "ssrn": ("ssrn",),
    "zenodo": ("zenodo",),
    "osf": ("osf",),
    "hal": ("halid",),
    "chemrxiv": ("chemrxiv",),
    "research_square": ("researchsquare",),
}


@dataclass(frozen=True, order=True)
class WorkIdentifier:
    """One normalized identifier offered as evidence about a work."""

    kind: str
    value: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly representation."""
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class WorkIdentifiers:
    """An immutable, normalized set of work identifiers."""

    items: tuple[WorkIdentifier, ...] = ()

    @classmethod
    def from_mapping(cls, identifiers: Mapping[str, str]) -> "WorkIdentifiers":
        """Build a set from provider or entry identifier values."""
        normalized = {
            item
            for kind, value in identifiers.items()
            for item in _normalize_identifier_evidence(kind, value)
        }
        return cls(tuple(sorted(normalized, key=_identifier_sort_key)))

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> "WorkIdentifiers":
        """Build a set from possibly repeated identifier kinds."""
        normalized = {
            item for kind, value in pairs for item in _normalize_identifier_evidence(kind, value)
        }
        return cls(tuple(sorted(normalized, key=_identifier_sort_key)))

    def by_kind(self) -> dict[str, frozenset[str]]:
        """Group values by identifier kind."""
        grouped: dict[str, set[str]] = {}
        for item in self.items:
            grouped.setdefault(item.kind, set()).add(item.value)
        return {kind: frozenset(values) for kind, values in grouped.items()}

    def primary(self) -> WorkIdentifier | None:
        """Return the preferred identifier for display and cluster reports."""
        return self.items[0] if self.items else None

    def to_dict(self) -> dict[str, list[str]]:
        """Return identifier values grouped by kind."""
        return {kind: sorted(values) for kind, values in sorted(self.by_kind().items())}


@dataclass(frozen=True)
class WorkEvidence:
    """Offline identifier and bibliographic evidence for one candidate work."""

    identifiers: WorkIdentifiers = WorkIdentifiers()
    title_fingerprint: str = ""
    authors: tuple[str, ...] = ()
    year: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "identifiers": self.identifiers.to_dict(),
            "title_fingerprint": self.title_fingerprint,
            "authors": list(self.authors),
            "year": self.year,
        }


@dataclass(frozen=True)
class WorkMatch:
    """A conservative comparison result with inspectable evidence."""

    status: MatchStatus
    reasons: tuple[str, ...]
    score: float | None = None

    @property
    def is_match(self) -> bool:
        """Return whether the evidence supports clustering the candidates."""
        return self.status in {"exact", "probable"}

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "score": self.score,
        }


def normalize_work_identifier(kind: str, value: str) -> WorkIdentifier | None:
    """Normalize one work identifier, returning ``None`` when malformed.

    ORCID is intentionally excluded: it identifies a contributor, not a work.
    """
    normalized_kind = kind.strip().lower()
    raw = value.strip()
    if not normalized_kind or not raw or normalized_kind == "orcid":
        return None
    try:
        if normalized_kind in _DOI_KINDS:
            normalized = canonical_doi(raw)
        elif normalized_kind == "arxiv":
            normalized = normalize_arxiv(raw)
        elif normalized_kind in _COMPACT_KINDS:
            normalized = re.sub(r"[^a-z0-9]", "", raw.casefold())
        else:
            normalized = raw.casefold()
    except ValueError:
        return None
    if not normalized:
        return None
    return WorkIdentifier(normalized_kind, normalized)


def entry_arxiv_id(entry: BibEntry) -> str | None:
    """Return the normalized arXiv id carried by an entry, if any."""
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
        normalized = arxiv_id_from_text(entry.fields.get(field_name, ""))
        if normalized:
            return normalized
    return None


def identity_class(entry: BibEntry) -> IdentityClass:
    """Classify what kind of work an entry describes, from offline evidence only.

    The classes describe how a work was made available, which is what governs
    the metadata it can be expected to carry: a ``preprint`` has no issue or
    publisher, a ``code`` record has no pagination. Cross-entry consistency
    checks use this so that records are only compared with comparable peers.

    Publication evidence wins over eprint evidence: an entry with both a journal
    reference and an eprint is a published article that also exists as a
    preprint, not a preprint.
    """
    etype = entry.type.lower()
    if etype in _CODE_TYPES:
        return "code"
    if etype in _BOOK_TYPES:
        return "book"
    fields = entry.fields
    has_venue = any(fields.get(name, "").strip() for name in _VENUE_FIELDS)
    has_locator = any(fields.get(name, "").strip() for name in _LOCATOR_FIELDS)
    if has_venue and (has_locator or etype in _PUBLISHED_TYPES):
        return "published"
    if _has_eprint_evidence(entry):
        return "preprint"
    if has_venue:
        return "published"
    return "unknown"


def _has_eprint_evidence(entry: BibEntry) -> bool:
    """Return whether an entry carries preprint-server evidence."""
    if entry_arxiv_id(entry) is not None:
        return True
    fields = entry.fields
    if any(fields.get(name, "").strip() for name in ("eprint", "archiveprefix", "eprinttype")):
        return True
    return any(fields.get(name, "").strip() for name in _PREPRINT_SERVER_FIELDS)


def evidence_from_entry(
    entry: BibEntry,
    *,
    additional_identifiers: Mapping[str, str] | None = None,
) -> WorkEvidence:
    """Extract deterministic, offline matching evidence from one entry."""
    pairs: list[tuple[str, str]] = []
    for kind, fields in _ENTRY_IDENTIFIER_FIELDS.items():
        for field in fields:
            value = entry.fields.get(field)
            if value:
                pairs.append((kind, value))
    arxiv = entry_arxiv_id(entry)
    if arxiv:
        pairs.append(("arxiv", arxiv))
    number = entry.fields.get("number", "").strip()
    if re.fullmatch(r"w\d+", number, re.IGNORECASE):
        pairs.append(("nber", number))
    pairs.extend((additional_identifiers or {}).items())

    raw_names = entry.fields.get("author") or entry.fields.get("editor") or ""
    authors = tuple(
        dict.fromkeys(
            name
            for raw_name in split_name_list(raw_names)
            if (name := last_name(raw_name).casefold())
        )
    )
    return WorkEvidence(
        identifiers=WorkIdentifiers.from_pairs(pairs),
        title_fingerprint=_normalize_text(entry.fields.get("title", "")),
        authors=authors,
        year=entry_year(entry),
    )


def compare_work_evidence(left: WorkEvidence, right: WorkEvidence) -> WorkMatch:
    """Compare two candidates without turning uncertainty into identity."""
    left_ids = left.identifiers.by_kind()
    right_ids = right.identifiers.by_kind()
    shared_kinds = sorted(set(left_ids).intersection(right_ids))
    conflicts = [kind for kind in shared_kinds if left_ids[kind].isdisjoint(right_ids[kind])]
    if conflicts:
        return WorkMatch(
            "conflict",
            tuple(
                f"conflicting {kind}: {', '.join(sorted(left_ids[kind]))} != "
                f"{', '.join(sorted(right_ids[kind]))}"
                for kind in conflicts
            ),
        )

    exact = [
        WorkIdentifier(kind, value)
        for kind in shared_kinds
        for value in sorted(left_ids[kind].intersection(right_ids[kind]))
    ]
    if exact:
        return WorkMatch(
            "exact",
            tuple(f"matching {item.kind}: {item.value}" for item in exact),
            1.0,
        )

    if not left.year or left.year != right.year:
        return WorkMatch("unknown", ("no matching stable identifier",))
    if len(left.title_fingerprint) < 12 or len(right.title_fingerprint) < 12:
        return WorkMatch("unknown", ("insufficient title evidence",))
    score = SequenceMatcher(None, left.title_fingerprint, right.title_fingerprint).ratio()
    if score < 0.92:
        return WorkMatch("unknown", ("title similarity below threshold",), score)
    shared_authors = sorted(set(left.authors).intersection(right.authors))
    if not shared_authors:
        return WorkMatch("unknown", ("no shared author evidence",), score)
    return WorkMatch(
        "probable",
        (
            f"title similarity {score:.3f}",
            f"same year: {left.year}",
            f"shared author: {shared_authors[0]}",
        ),
        score,
    )


def find_exact_matches(
    lib: BibFile,
    identifiers: WorkIdentifiers | Mapping[str, str],
) -> list[str]:
    """Return keys whose entry evidence exactly matches any supplied identifier."""
    target = (
        identifiers
        if isinstance(identifiers, WorkIdentifiers)
        else WorkIdentifiers.from_mapping(identifiers)
    )
    if not target.items:
        return []
    target_by_kind = target.by_kind()
    matches: list[str] = []
    for entry in lib.entries.values():
        entry_by_kind = evidence_from_entry(entry).identifiers.by_kind()
        if any(
            not values.isdisjoint(entry_by_kind.get(kind, frozenset()))
            for kind, values in target_by_kind.items()
        ):
            matches.append(entry.key)
    return matches


def _identifier_sort_key(identifier: WorkIdentifier) -> tuple[int, str, str]:
    return (_ID_PRIORITY.get(identifier.kind, 100), identifier.kind, identifier.value)


def _normalize_identifier_evidence(kind: str, value: str) -> set[WorkIdentifier]:
    identifier = normalize_work_identifier(kind, value)
    if identifier is None:
        return set()
    evidence = {identifier}
    if identifier.kind in {"biorxiv", "medrxiv"}:
        doi = normalize_work_identifier("doi", value)
        if doi is not None:
            evidence.add(doi)
    return evidence
