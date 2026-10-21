"""Descriptive analysis of one bibliography: what it holds and how complete it is.

:func:`analyze` composes existing reports — the entry store, group membership,
``lint``, linked-file checks, and the Pinax store — into one
:class:`AnalysisReport` of descriptive counts, grouped into named sections:

``entries``
    Physical entries, distinct citation keys, and duplicated keys.
``types`` / ``years``
    How many entries have each type and each year (``undated`` for none).
``authors`` / ``venues``
    How many entries each creator and venue appears in, most frequent first.
``coauthors``
    The co-authorship network in brief: authors, co-listed pairs, connected
    components and name-variant candidates, with the most frequent pairs and
    the most connected authors (:func:`pynakes.analysis.coauthor_network`
    reports the whole network).
``identifiers`` / ``fields``
    How many entries carry each identifier, and each field name.
``groups``
    Group-tree size and ``groups``-field memberships.
``lint``
    The finding counts ``lint`` reports, after the library's own waivers.
``materials``
    Linked-file statuses and, in a Pinax library, which materials exist.

Counts are offline and reconcile with the reports they come from: the ``lint``
section equals ``lint``'s summary, every entry is counted once per section,
and duplicate citation keys are counted as the separate entries they are.
Nothing here scores scientific quality or infers anything about a work.

Frequency lists group spellings that differ only in case, braces, or spacing,
and report the first spelling seen; authors are compared in normalized
``Last, First`` form (:func:`pynakes.authors.normalize_name_list`), so
``John Smith`` and ``Smith, John`` count as one person, but ``Smith, J.`` does
not — telling those apart is a curation decision, not a count. The
``coauthors`` section compares people the same way, so its ``authors`` equals
the ``authors`` section's ``distinct``, and lists such look-alike names as
``variant_candidates`` instead of merging them. Ties are broken
alphabetically, so the report is deterministic.

The report's ``sections`` mapping is the stable unit of composition: a later
multi-file rollup sums per-file sections rather than re-deriving them.

Co-authorship network
--------------------

:func:`coauthor_network` reads the ``author`` field of each entry and reports,
offline and deterministically:

``authors``
    Every person listed, with the entries they appear in, their distinct
    collaborators, the years they span, and the spellings that normalized to
    them.
``pairs``
    Every two people listed together on at least one entry, with the number of
    shared entries, their first and last year, and the citation keys.
``components``
    Connected components of the network: groups of people linked by chains
    of shared entries.
``variants``
    Distinct names that may be one person (``Smith, J.`` and ``Smith, John``),
    with the reasons and the evidence against. They are never merged.

People are compared exactly as the ``authors`` section of
:func:`pynakes.analysis.analyze` compares them, so the two reconcile: the
network has as many authors as that section's ``distinct``. ``others`` (or
``et al.``) truncates an author list; the people it stands for are unknown, so
the network links only the listed authors and counts the truncated entries
under ``with_others``.

With ``focus``, the report is an ego view of those people: the focus names,
everyone who shares an entry with one of them, and the pairs among all of
these, which answers "who among my co-authors has worked together". Its
components leave the focus names out, since every collaborator is linked
through them by definition. Several focus names are treated as one view, not
as one person: pass each spelling of a person deliberately when the
``variants`` list shows them.

An entry listing more than ``max_authors`` people (default
:data:`DEFAULT_MAX_AUTHORS`, the library's ``coauthors-max-authors`` setting
in the CLI; ``0`` for no limit) is not linked: its people still count as
authors, but it adds no pairs and joins no components, and its key is listed
under ``unlinked_keys``. A thousand-author collaboration paper would otherwise
add half a million pairs that describe the collaboration, not its members.

Counts describe the records; they say nothing about the people's work or the
strength of a collaboration beyond the entries in this file.

Entry totals, author counts and author years cover the whole selection even
in a focus view. ``visible_collaborators`` counts neighbours in the visible
graph; ``collaborators`` counts neighbours in the selection. The serialized
``scope`` labels these distinctions and components/isolates excluding focus.
Warnings are retained in documents, including conflicting ORCID annotations
on one normalized name: these flag possible homonyms without splitting nodes.

"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes._analysis_coauthors import (
    DEFAULT_MAX_AUTHORS,
    MAX_AUTHORS_SETTING,
    CoauthorNetwork,
    UnknownAuthorError,
    coauthor_network,
    library_max_authors,
)
from pynakes._analysis_coauthors import SCHEMA as COAUTHOR_SCHEMA
from pynakes._analysis_people import entry_people, fold, year_of
from pynakes._text_utils import fold_field_names
from pynakes.files import check_linked_files, parse_file_field
from pynakes.filestore import FileStore
from pynakes.group_tree import library_group_tree
from pynakes.groups import entry_groups
from pynakes.lint import lint, suppress_findings
from pynakes.model import BibEntry

if TYPE_CHECKING:
    from pynakes.engine import Bibliography

__all__ = [
    "COAUTHOR_SCHEMA",
    "DEFAULT_MAX_AUTHORS",
    "IDENTIFIER_FIELDS",
    "MAX_AUTHORS_SETTING",
    "SECTIONS",
    "AnalysisReport",
    "CoauthorNetwork",
    "UnknownAuthorError",
    "analyze",
    "coauthor_network",
    "library_max_authors",
]

#: Every section :func:`analyze` can report, in report order.
SECTIONS = (
    "entries",
    "types",
    "years",
    "authors",
    "coauthors",
    "venues",
    "identifiers",
    "fields",
    "groups",
    "lint",
    "materials",
)

#: Identifier fields whose coverage the ``identifiers`` section reports.
IDENTIFIER_FIELDS = ("doi", "eprint", "isbn", "issn", "url")

#: Venue fields, in preference order: an entry's venue is the first one present.
_VENUE_FIELDS = ("journaltitle", "journal", "booktitle")

_PINAX_KINDS = ("published_pdf", "preprint_pdf", "preprint_source", "supplement_pdf", "erratum_pdf")


@dataclass
class AnalysisReport:
    """Descriptive counts for one bibliography, keyed by section name."""

    file: str | None
    top: int
    sections: dict[str, dict[str, object]] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the report to a JSON-friendly dict."""
        return {"top": self.top, "sections": self.sections}


def analyze(
    coll: Bibliography,
    *,
    sections: Iterable[str] | None = None,
    top: int = 10,
    max_authors: int | None = None,
) -> AnalysisReport:
    """Return the :class:`AnalysisReport` of ``coll``.

    ``sections`` limits the report to the named :data:`SECTIONS` (all of them
    by default), skipping the work the others need — ``lint`` and
    ``materials`` are the expensive ones. ``top`` caps the author and venue
    frequency lists and the ``coauthors`` section's top pairs and
    collaborators; the counts beside them always cover every value.
    ``max_authors`` is the ``coauthors`` section's limit on linked author
    lists; ``None`` reads the library's ``coauthors-max-authors`` setting.

    Raises:
        ValueError: for an unknown section name or a negative ``top``.
    """
    wanted = list(SECTIONS) if sections is None else list(dict.fromkeys(sections))
    unknown = [name for name in wanted if name not in SECTIONS]
    if unknown:
        raise ValueError(
            f"Unknown analysis section(s) {', '.join(unknown)}; expected: {', '.join(SECTIONS)}"
        )
    if top < 0:
        raise ValueError("top must not be negative")
    if max_authors is not None and max_authors < 0:
        raise ValueError("max_authors must not be negative")

    entries = list(coll.lib.entries.values())
    report = AnalysisReport(file=str(coll.path) if coll.path is not None else None, top=top)

    def coauthors_section() -> dict[str, object]:
        network = coauthor_network(
            entries,
            max_authors=library_max_authors(coll.lib) if max_authors is None else max_authors,
        )
        report.warnings.extend(network.warnings)
        return network.summary_section(top)

    builders: dict[str, Callable[[], dict[str, object]]] = {
        "entries": lambda: _entries_section(entries),
        "types": lambda: _types_section(entries),
        "years": lambda: _years_section(entries),
        "authors": lambda: _authors_section(entries, top),
        "coauthors": coauthors_section,
        "venues": lambda: _venues_section(entries, top),
        "identifiers": lambda: _identifiers_section(entries),
        "fields": lambda: _fields_section(entries),
        "groups": lambda: _groups_section(coll, entries),
        "lint": lambda: _lint_section(coll),
        "materials": lambda: _materials_section(coll, entries, report.warnings),
    }
    for name in SECTIONS:
        if name in wanted:
            report.sections[name] = builders[name]()
    return report


# --- helpers -----------------------------------------------------------------------


def _ranked(counts: Counter[str], names: dict[str, str]) -> list[tuple[str, int]]:
    """Return ``(display, count)`` pairs, most frequent first, ties alphabetical."""
    return sorted(
        ((names[key], count) for key, count in counts.items()),
        key=lambda item: (-item[1], item[0].casefold(), item[0]),
    )


def _coverage(present: int, total: int) -> dict[str, object]:
    return {
        "present": present,
        "missing": total - present,
        "coverage": round(present / total, 4) if total else None,
    }


# --- sections --------------------------------------------------------------------


def _entries_section(entries: list[BibEntry]) -> dict[str, object]:
    keys = Counter(entry.key for entry in entries)
    duplicated = sorted((key, count) for key, count in keys.items() if count > 1)
    return {
        "total": len(entries),
        "unique_keys": len(keys),
        "duplicate_keys": [{"key": key, "entries": count} for key, count in duplicated],
        "entries_with_duplicate_keys": sum(count for _key, count in duplicated),
    }


def _types_section(entries: list[BibEntry]) -> dict[str, object]:
    counts = Counter(entry.type.lower() for entry in entries)
    ranked = _ranked(counts, {name: name for name in counts})
    return {
        "distinct": len(counts),
        "counts": [{"type": name, "entries": count} for name, count in ranked],
    }


def _years_section(entries: list[BibEntry]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    undated = 0
    for entry in entries:
        year = year_of(entry)
        if year is None:
            undated += 1
        else:
            counts[year] += 1
    years = sorted(counts)
    return {
        "dated": sum(counts.values()),
        "undated": undated,
        "earliest": years[0] if years else None,
        "latest": years[-1] if years else None,
        "counts": [{"year": year, "entries": counts[year]} for year in years],
    }


def _authors_section(entries: list[BibEntry], top: int) -> dict[str, object]:
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    with_authors = 0
    truncated_lists = 0
    for entry in entries:
        listed = entry_people(entry)
        truncated_lists += listed.others
        for key, name, _spelling in listed.people:
            names.setdefault(key, name)
        if listed.people:
            with_authors += 1
        counts.update(listed.keys)
    ranked = _ranked(counts, names)
    return {
        "distinct": len(counts),
        "entries_with_authors": with_authors,
        "entries_without_authors": len(entries) - with_authors,
        "entries_with_others": truncated_lists,
        "top": [{"name": name, "entries": count} for name, count in ranked[:top]],
    }


def _venues_section(entries: list[BibEntry], top: int) -> dict[str, object]:
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    fields_used: dict[str, str] = {}
    for entry in entries:
        folded = fold_field_names(entry.fields)
        for name in _VENUE_FIELDS:
            value = (folded.get(name) or "").strip()
            if value:
                key = fold(value)
                names.setdefault(key, " ".join(value.split()))
                fields_used.setdefault(key, name)
                counts[key] += 1
                break
    ranked = sorted(
        counts.items(), key=lambda item: (-item[1], names[item[0]].casefold(), names[item[0]])
    )
    with_venue = sum(counts.values())
    return {
        "distinct": len(counts),
        "entries_with_venue": with_venue,
        "entries_without_venue": len(entries) - with_venue,
        "top": [
            {"venue": names[key], "field": fields_used[key], "entries": count}
            for key, count in ranked[:top]
        ],
    }


def _identifiers_section(entries: list[BibEntry]) -> dict[str, object]:
    present: Counter[str] = Counter()
    with_any = 0
    for entry in entries:
        folded = fold_field_names(entry.fields)
        found = {name for name in IDENTIFIER_FIELDS if (folded.get(name) or "").strip()}
        present.update(found)
        with_any += bool(found)
    total = len(entries)
    return {
        "total": total,
        "fields": {name: _coverage(present[name], total) for name in IDENTIFIER_FIELDS},
        "any": _coverage(with_any, total),
    }


def _fields_section(entries: list[BibEntry]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    for entry in entries:
        counts.update({name.lower() for name, value in entry.fields.items() if value.strip()})
    ranked = _ranked(counts, {name: name for name in counts})
    return {
        "distinct": len(counts),
        "counts": [{"field": name, "entries": count} for name, count in ranked],
    }


def _groups_section(coll: Bibliography, entries: list[BibEntry]) -> dict[str, object]:
    tree = library_group_tree(coll.lib)
    declared = [node.name for node in tree] if tree else []
    counts: Counter[str] = Counter()
    with_groups = 0
    for entry in entries:
        groups = set(entry_groups(entry))
        with_groups += bool(groups)
        counts.update(groups)
    ranked = _ranked(counts, {name: name for name in counts})
    declared_set = set(declared)
    return {
        "tree_defined": tree is not None,
        "declared": len(declared),
        "entries_with_groups": with_groups,
        "entries_without_groups": len(entries) - with_groups,
        "memberships": [{"group": name, "entries": count} for name, count in ranked],
        "undeclared": sorted(
            name for name in counts if tree is not None and name not in declared_set
        ),
        "unused_declared": [name for name in declared if name not in counts],
    }


def _lint_section(coll: Bibliography) -> dict[str, object]:
    base_dir = coll.path.parent if coll.path is not None else None
    issues, suppressed = suppress_findings(coll.lib, lint(coll.lib, base_dir=base_dir))
    by_type = Counter(issue.type for issue in issues)
    by_category = Counter(issue.category for issue in issues)
    severities = Counter(issue.severity for issue in issues)
    return {
        "issues": len(issues),
        "errors": severities["error"],
        "warnings": severities["warning"],
        "info": severities["info"],
        "suppressed": suppressed,
        "by_category": dict(sorted(by_category.items())),
        "by_type": dict(sorted(by_type.items())),
        "entries_with_findings": len({issue.key for issue in issues if issue.key}),
    }


def _materials_section(
    coll: Bibliography, entries: list[BibEntry], warnings: list[dict[str, str]]
) -> dict[str, object]:
    with_links = sum(1 for entry in entries if parse_file_field(entry))
    linked: dict[str, object] = {"entries_with_files": with_links}
    if coll.path is not None:
        report = check_linked_files(coll.lib, coll.path)
        linked.update(
            checked=report.checked,
            ok=report.ok,
            missing=report.missing,
            wrong_type=report.wrong_type,
            unresolved=report.unresolved,
        )
    return {"linked_files": linked, "pinax": _pinax_counts(coll, entries, warnings)}


def _pinax_counts(
    coll: Bibliography, entries: list[BibEntry], warnings: list[dict[str, str]]
) -> dict[str, object]:
    if coll.path is None:
        return {"configured": False}
    try:
        store = FileStore.from_metadata(coll.lib, Path(coll.path))
        if store is None:
            return {"configured": False}
        scan = store.scan_entries(entries)
    except (OSError, ValueError) as exc:
        warnings.append({"type": "pinax_unavailable", "message": f"Pinax scan failed: {exc}"})
        return {"configured": True, "error": str(exc)}
    by_kind = {
        kind: sum(1 for item in scan.entries if getattr(item, kind)) for kind in _PINAX_KINDS
    }
    with_materials = sum(1 for item in scan.entries if item.any_present)
    return {
        "configured": True,
        "keys": len(scan.entries),
        "keys_with_materials": with_materials,
        "keys_without_materials": len(scan.entries) - with_materials,
        "by_kind": by_kind,
        "orphans": len(scan.orphans),
        "drift": len(scan.drift),
    }
