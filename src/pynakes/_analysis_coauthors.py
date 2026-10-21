"""Co-authorship graph implementation for the public :mod:`pynakes.analysis` API."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from pynakes._analysis_people import entry_people, fold, year_of
from pynakes._coauthor_render import render_graphml, render_markdown
from pynakes._coauthor_variants import classify, name_parts, variant_candidates
from pynakes.authors import normalize_name_list
from pynakes.metadata.core import metadata_value
from pynakes.model import BibEntry, BibFile

__all__ = [
    "DEFAULT_MAX_AUTHORS",
    "MAX_AUTHORS_SETTING",
    "SCHEMA",
    "CoauthorNetwork",
    "UnknownAuthorError",
    "coauthor_network",
    "library_max_authors",
]

#: One JSON-ready record of the network document (an author, pair, component...).
Record = dict[str, Any]

#: Identifier and version of the network document (:meth:`CoauthorNetwork.to_dict`).
SCHEMA = "pynakes.coauthors/1"

#: Entries listing more authors than this are not linked, unless a run or the
#: library says otherwise.
DEFAULT_MAX_AUTHORS = 100

#: The ``pynakes-meta`` setting that stores a library's limit.
MAX_AUTHORS_SETTING = "coauthors-max-authors"


def library_max_authors(lib: BibFile) -> int:
    """Return the library's ``coauthors-max-authors`` setting, or the default.

    Raises:
        ValueError: when the stored value is not a non-negative integer.
    """
    raw = metadata_value(lib, MAX_AUTHORS_SETTING)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_AUTHORS
    try:
        limit = int(raw.strip())
    except ValueError:
        limit = -1
    if limit < 0:
        raise ValueError(f"{MAX_AUTHORS_SETTING} must be a non-negative integer, not {raw!r}")
    return limit


class UnknownAuthorError(ValueError):
    """A focus name that no selected entry lists, with the names that resemble it."""

    def __init__(self, name: str, candidates: list[str]) -> None:
        self.name = name
        self.candidates = candidates
        hint = f"; similar names: {'; '.join(candidates)}" if candidates else ""
        super().__init__(f"No selected entry lists the author {name!r}{hint}")


@dataclass
class CoauthorNetwork:
    """The co-authorship network of selected entries (see :mod:`pynakes.analysis`)."""

    entries: dict[str, int]
    max_authors: int
    unlinked_keys: list[str]
    authors: list[Record]
    pairs: list[Record]
    components: list[Record]
    variants: list[Record]
    focus: list[dict[str, str]] | None = None
    warnings: list[Record] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        """Visible authors/pairs; components and isolates exclude focus when given."""
        sizes = [int(component["size"]) for component in self.components]
        return {
            "authors": len(self.authors),
            "pairs": len(self.pairs),
            "components": len(sizes),
            "largest_component": max(sizes, default=0),
            "isolated_authors": sizes.count(1),
            "variant_candidates": len(self.variants),
        }

    def to_dict(self, source: Record | None = None) -> Record:
        """Serialize the network using :data:`pynakes.analysis.COAUTHOR_SCHEMA`.

        ``source`` describes where the entries came from (the CLI records the
        file, its digest and the selection); it is included when given.
        """
        return {
            "schema": SCHEMA,
            **({"source": source} if source is not None else {}),
            "max_authors": self.max_authors,
            "summary": self.summary,
            "entries": self.entries,
            "unlinked_keys": self.unlinked_keys,
            "focus": self.focus,
            "authors": self.authors,
            "pairs": self.pairs,
            "components": self.components,
            "variants": self.variants,
            "warnings": self.warnings,
            "scope": {
                "entries": "selection",
                "author_counts_and_years": "selection",
                "authors_and_pairs": "focus_neighborhood"
                if self.focus is not None
                else "selection",
                "components_and_isolates": "excluding_focus"
                if self.focus is not None
                else "selection",
                "component_entries": "selected linked entries incident to component members",
                "warnings": "selection",
            },
        }

    def to_graphml(self, source: Record | None = None) -> str:
        """Render GraphML with graph-level JSON context, warnings and optional source."""
        return render_graphml(self.to_dict(source))

    def to_markdown(self, title: str = "Co-author network", source: Record | None = None) -> str:
        """Render the network as a Markdown report with one table per list."""
        return render_markdown(self.to_dict(source), title)

    def summary_section(self, top: int) -> Record:
        """Return the bounded summary that ``analyze`` reports as its ``coauthors`` section."""
        collaborators = sorted(
            self.authors,
            key=lambda item: (-item["collaborators"], str(item["name"]).casefold()),
        )
        return {
            **self.summary,
            "entries_with_authors": self.entries["with_authors"],
            "single_author_entries": self.entries["single_author"],
            "coauthored_entries": self.entries["coauthored"],
            "entries_with_others": self.entries["with_others"],
            "entries_over_max_authors": self.entries["over_max_authors"],
            "max_authors": self.max_authors,
            "top_pairs": [
                {"authors": pair["authors"], "entries": pair["entries"]}
                for pair in self.pairs[:top]
            ],
            "top_collaborators": [
                {"name": item["name"], "collaborators": item["collaborators"]}
                for item in collaborators[:top]
            ],
        }


def coauthor_network(
    entries: Iterable[BibEntry],
    *,
    focus: Iterable[str] = (),
    max_authors: int = DEFAULT_MAX_AUTHORS,
) -> CoauthorNetwork:
    """Return the :class:`CoauthorNetwork` of ``entries``, or its ego view around ``focus``.

    ``entries`` are counted as given, duplicate citation keys included; select
    them first (for example with :func:`pynakes.query.parse_query`) to slice by
    year or topic. Each ``focus`` name is normalized like an author field, so
    ``Isaac Newton`` finds ``Newton, Isaac``. An entry listing more than
    ``max_authors`` people is not linked (``0``: no limit).

    Raises:
        UnknownAuthorError: when a focus name is not listed by any entry.
        ValueError: for a negative ``max_authors``.
    """
    if max_authors < 0:
        raise ValueError("max_authors must not be negative")
    listed = list(entries)
    years = [year_of(entry) for entry in listed]
    scan = _Scan(max_authors)
    for index, entry in enumerate(listed):
        scan.add(index, entry)
    for key in sorted(scan.orcids):
        if len(scan.orcids[key]) > 1:
            scan.warnings.append(
                {
                    "type": "conflicting_author_orcids",
                    "name": scan.names[key],
                    "orcids": sorted(scan.orcids[key]),
                    "evidence": scan.orcid_evidence[key],
                    "message": f"{scan.names[key]} has multiple ORCID iDs; the name remains "
                    "one node and may conflate different people. Review its annotated entries.",
                }
            )

    focus_keys: list[str] = []
    focus_report: list[dict[str, str]] | None = None
    requested = list(focus)
    if requested:
        focus_report = []
        for name in requested:
            key = fold(normalize_name_list(name, "jabref").strip())
            if key not in scan.names:
                raise UnknownAuthorError(name, _similar(name, scan.names))
            focus_report.append({"requested": name, "name": scan.names[key]})
            focus_keys.append(key)
    focus_set = set(focus_keys)
    neighbors = scan.neighbors()
    if focus_set:
        nodes = focus_set.union(*(neighbors[key] for key in focus_set))
    else:
        nodes = set(scan.names)

    def keys_of(indices: Iterable[int]) -> list[str]:
        return [listed[i].key for i in indices]

    linked_entries = {
        key: [i for i in indices if i not in scan.unlinked]
        for key, indices in scan.author_entries.items()
    }
    component_of, components = _components(nodes - focus_set, neighbors, scan.names, linked_entries)
    authors = []
    for key in nodes:
        indices = scan.author_entries[key]
        record: Record = {
            "name": scan.names[key],
            "entries": len(indices),
            "collaborators": len(neighbors[key]),
            "visible_collaborators": len(neighbors[key] & nodes),
            "coauthored_entries": scan.coauthored[key],
            "entries_with_others": scan.with_others[key],
            "unlinked_entries": len(indices) - len(linked_entries[key]),
            **_year_span(indices, years),
            "component": component_of.get(key),
            "spellings": sorted(scan.spellings[key]),
            "orcids": sorted(scan.orcids.get(key, ())),
        }
        if focus_set:
            shared = sorted({i for other in focus_set - {key} for i in scan.pair(key, other)})
            record["focus"] = key in focus_set
            record["with_focus"] = len(shared)
            record["with_focus_keys"] = keys_of(shared)
        authors.append(record)
    authors.sort(key=lambda item: (-item["entries"], str(item["name"]).casefold(), item["name"]))

    pairs: list[Record] = []
    for (a, b), indices in scan.pairs.items():
        if a in nodes and b in nodes:
            first, second = sorted((scan.names[a], scan.names[b]), key=lambda n: (n.casefold(), n))
            pairs.append(
                {
                    "authors": [first, second],
                    "entries": len(indices),
                    **_year_span(indices, years),
                    "keys": keys_of(indices),
                }
            )
    pairs.sort(key=lambda item: (-item["entries"], [n.casefold() for n in item["authors"]]))

    entry_keys = {key: keys_of(indices) for key, indices in scan.author_entries.items()}
    entry_ids = {key: set(indices) for key, indices in scan.author_entries.items()}
    variants = variant_candidates(scan.names, entry_keys, entry_ids, scan.orcids)
    shown = {scan.names[key] for key in nodes}
    variants = [item for item in variants if set(item["names"]) & shown]

    network = CoauthorNetwork(
        entries=scan.entry_counts(len(listed)),
        max_authors=max_authors,
        unlinked_keys=keys_of(sorted(scan.unlinked)),
        authors=authors,
        pairs=pairs,
        components=components,
        variants=variants,
        focus=focus_report,
        warnings=scan.warnings,
    )
    if scan.unlinked:
        network.warnings.append(
            {
                "type": "large_author_lists",
                "max_authors": max_authors,
                "keys": network.unlinked_keys,
                "message": f"{len(scan.unlinked)} entries list more than {max_authors} "
                "authors and are not linked into the network (raise or disable the "
                f"limit with --max-authors or {MAX_AUTHORS_SETTING})",
            }
        )
    focus_names = {scan.names[key] for key in focus_keys}
    for key in focus_keys:
        name = scan.names[key]
        others = [
            other
            for item in variants
            if name in item["names"]
            for other in item["names"]
            if other not in focus_names
        ]
        if others:
            network.warnings.append(
                {
                    "type": "focus_variants",
                    "name": name,
                    "variants": others,
                    "message": f"Focus {name!r} has possible name variants "
                    f"({'; '.join(others)}); entries listing only those are not in "
                    "this view unless each is also given as a focus name",
                }
            )
    return network


class _Scan:
    """One pass over the entries: people, their entries, and co-listed pairs."""

    def __init__(self, max_authors: int) -> None:
        self.max_authors = max_authors
        self.unlinked: set[int] = set()
        self.names: dict[str, str] = {}
        self.spellings: dict[str, set[str]] = defaultdict(set)
        self.author_entries: dict[str, list[int]] = defaultdict(list)
        self.coauthored: Counter[str] = Counter()
        self.with_others: Counter[str] = Counter()
        self.orcids: dict[str, set[str]] = defaultdict(set)
        self.orcid_evidence: dict[str, list[Record]] = defaultdict(list)
        self.pairs: dict[tuple[str, str], list[int]] = defaultdict(list)
        self.counts: Counter[str] = Counter()
        self.warnings: list[Record] = []

    def add(self, index: int, entry: BibEntry) -> None:
        listed = entry_people(entry)
        if listed.invalid_orcids:
            self.warnings.append(
                {
                    "type": "invalid_orcid_annotation",
                    "key": entry.key,
                    "items": listed.invalid_orcids,
                    "message": f"{entry.key}: unreadable author+an:orcid item(s) "
                    f"{', '.join(listed.invalid_orcids)}; they were ignored",
                }
            )
        keys = listed.keys
        if keys:
            self.counts["with_authors"] += 1
            self.counts["coauthored" if len(keys) > 1 else "single_author"] += 1
        self.counts["with_others"] += listed.others
        linked = not self.max_authors or len(keys) <= self.max_authors
        if not linked:
            self.unlinked.add(index)
        for key, name, spelling in listed.people:
            self.names.setdefault(key, name)
            self.spellings[key].add(spelling)
            self.author_entries[key].append(index)
            self.coauthored[key] += len(keys) > 1
            self.with_others[key] += listed.others
        for key, orcid in listed.orcids.items():
            self.orcids[key].add(orcid)
            self.orcid_evidence[key].append(
                {"key": entry.key, "selection_index": index, "orcid": orcid}
            )
        if linked:
            for pair in combinations(sorted(keys), 2):
                self.pairs[pair].append(index)

    def pair(self, a: str, b: str) -> list[int]:
        return self.pairs.get((a, b) if a < b else (b, a), [])

    def neighbors(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {key: set() for key in self.names}
        for a, b in self.pairs:
            found[a].add(b)
            found[b].add(a)
        return found

    def entry_counts(self, total: int) -> dict[str, int]:
        return {
            "total": total,
            "with_authors": self.counts["with_authors"],
            "without_authors": total - self.counts["with_authors"],
            "single_author": self.counts["single_author"],
            "coauthored": self.counts["coauthored"],
            "with_others": self.counts["with_others"],
            "over_max_authors": len(self.unlinked),
        }


def _year_span(indices: list[int], years: list[str | None]) -> Record:
    dated = sorted(year for i in indices if (year := years[i]) is not None)
    return {
        "first_year": dated[0] if dated else None,
        "last_year": dated[-1] if dated else None,
        "undated": len(indices) - len(dated),
    }


def _components(
    nodes: set[str],
    neighbors: dict[str, set[str]],
    names: dict[str, str],
    author_entries: dict[str, list[int]],
) -> tuple[dict[str, int], list[Record]]:
    """Return each node's component id and the components, largest first."""
    groups: list[list[str]] = []
    seen: set[str] = set()
    for start in sorted(nodes):
        if start in seen:
            continue
        seen.add(start)
        stack, members = [start], []
        while stack:
            node = stack.pop()
            members.append(node)
            for other in neighbors[node] & nodes:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        groups.append(members)
    records: list[tuple[list[str], Record]] = []
    for members in groups:
        labels = sorted((names[key] for key in members), key=lambda n: (n.casefold(), n))
        entries = {i for key in members for i in author_entries[key]}
        records.append(
            (members, {"size": len(members), "entries": len(entries), "authors": labels})
        )
    records.sort(
        key=lambda item: (-item[1]["size"], -item[1]["entries"], item[1]["authors"][0].casefold())
    )
    component_of: dict[str, int] = {}
    components = []
    for number, (members, record) in enumerate(records):
        components.append({"id": number, **record})
        for key in members:
            component_of[key] = number
    return component_of, components


def _similar(requested: str, names: dict[str, str]) -> list[str]:
    """Return the listed names that may be the requested one (same family name or a variant)."""
    wanted = name_parts(normalize_name_list(requested, "jabref").strip())
    if wanted is None:
        return []
    similar = []
    for display in names.values():
        parts = name_parts(display)
        if parts is not None and (
            parts.family_letters == wanted.family_letters or classify(wanted, parts)
        ):
            similar.append(display)
    return sorted(similar, key=lambda n: (n.casefold(), n))
