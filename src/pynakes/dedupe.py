"""Duplicate-work detection and conservative merge operations."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from pynakes._identifiers import canonical_doi, normalize_arxiv
from pynakes._text_utils import _normalize_text
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.identity import (
    WorkIdentifier,
    WorkIdentifiers,
    compare_work_evidence,
    evidence_from_entry,
)
from pynakes.keys import rewrite_key_references
from pynakes.model import BibEntry, BibFile


@dataclass
class DuplicateCluster:
    """A group of entries that appear to describe the same work."""

    identity: WorkIdentifier
    reason: str
    entries: list[BibEntry]

    def to_dict(self) -> dict[str, object]:
        """Serialize the cluster (identity, reason, and members) to a dict."""
        return {
            "identity": self.identity.to_dict(),
            "reason": self.reason,
            "entries": [
                {"key": entry.key, "type": entry.type, "fields": dict(entry.fields)}
                for entry in self.entries
            ],
            "keys": [entry.key for entry in self.entries],
        }


@dataclass
class MergeConflict:
    """One ambiguous value that blocks an automatic merge."""

    cluster: WorkIdentifier
    field: str
    values: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        """Serialize the conflict (field and per-key values) to a dict."""
        return {
            "cluster": self.cluster.to_dict(),
            "field": self.field,
            "values": dict(self.values),
        }


@dataclass
class ClusterMerge:
    """Summary of one cluster merge."""

    identity: WorkIdentifier
    primary_key: str
    removed_keys: list[str]
    field_changes: dict[str, str] = field(default_factory=dict)
    type_changed: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the merge (primary, removed keys, and changes) to a dict."""
        return {
            "identity": self.identity.to_dict(),
            "primary_key": self.primary_key,
            "removed_keys": list(self.removed_keys),
            "field_changes": dict(self.field_changes),
            "type_changed": self.type_changed,
        }


@dataclass
class DedupeMergeReport:
    """Result of a duplicate merge."""

    clusters: list[DuplicateCluster]
    merged: list[ClusterMerge]
    removed_entries: list[BibEntry]
    field_changes: int = 0
    pinax_materials: list[dict[str, str]] = field(default_factory=list)

    @property
    def merged_clusters(self) -> int:
        """Number of duplicate clusters that were merged."""
        return len(self.merged)

    @property
    def removed_entry_count(self) -> int:
        """Number of entries removed as redundant duplicates."""
        return len(self.removed_entries)

    @property
    def modified_entries(self) -> int:
        """Total entries affected: merged primaries plus removed duplicates."""
        return self.merged_clusters + self.removed_entry_count

    def to_dict(self) -> dict[str, object]:
        """Serialize the merge report to a JSON-friendly dict for CLI output."""
        return {
            "clusters": [cluster.to_dict() for cluster in self.clusters],
            "merged": [item.to_dict() for item in self.merged],
            "merged_clusters": self.merged_clusters,
            "removed_entries": self.removed_entry_count,
            "field_changes": self.field_changes,
            "pinax_materials": list(self.pinax_materials),
        }


class DedupeConflictError(Exception):
    """Raised when duplicate entries cannot be merged without guessing."""

    def __init__(self, conflicts: list[MergeConflict], clusters: list[DuplicateCluster]) -> None:
        self.conflicts = conflicts
        self.clusters = clusters
        super().__init__(f"{len(conflicts)} dedupe merge conflict(s)")


_DELIMITED_FIELDS = {"groups", "keywords", "keyword", "tags"}


def find_duplicate_clusters(lib: BibFile) -> list[DuplicateCluster]:
    """Detect duplicate works in ``lib``.

    Exact stable identifiers are unioned first. Fuzzy title/author/year matches
    are then allowed only when the two entries do not carry incompatible stable
    identifiers.
    """
    entries = lib.entries.values()
    if len(entries) < 2:
        return []

    parent = list(range(len(entries)))
    reasons: dict[int, set[str]] = defaultdict(set)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int, reason: str) -> None:
        ra = find(a)
        rb = find(b)
        if ra == rb:
            reasons[ra].add(reason)
            return
        keep, drop = (ra, rb) if ra < rb else (rb, ra)
        parent[drop] = keep
        reasons[keep].update(reasons.pop(drop, set()))
        reasons[keep].add(reason)

    evidence = [evidence_from_entry(entry) for entry in entries]
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            match = compare_work_evidence(evidence[i], evidence[j])
            if match.status == "exact":
                left_ids = evidence[i].identifiers.by_kind()
                right_ids = evidence[j].identifiers.by_kind()
                for kind in sorted(set(left_ids).intersection(right_ids)):
                    if left_ids[kind].intersection(right_ids[kind]):
                        union(i, j, kind)
            elif match.status == "probable":
                union(i, j, "fuzzy")

    grouped: dict[int, list[int]] = defaultdict(list)
    for i in range(len(entries)):
        grouped[find(i)].append(i)

    clusters: list[DuplicateCluster] = []
    for root in sorted(grouped):
        indices = grouped[root]
        if len(indices) < 2:
            continue
        cluster_entries = [entries[i] for i in indices]
        identity = _cluster_identity(cluster_entries)
        reason = "+".join(sorted(reasons.get(root, {"fuzzy"})))
        clusters.append(DuplicateCluster(identity, reason, cluster_entries))
    return clusters


def clusters_for_keys(
    clusters: list[DuplicateCluster], keys: Iterable[str]
) -> list[DuplicateCluster]:
    """Return the clusters containing any of ``keys``, in their original order.

    This is what lets a caller merge one duplicate pair it has looked at rather
    than every pair in the file. A key belonging to no cluster raises
    :class:`ValueError`: the caller believed it named a duplicate, and merging
    nothing while reporting success would hide the mistake.
    """
    wanted = {key.strip() for key in keys if key.strip()}
    if not wanted:
        raise ValueError("No citation key given to select a duplicate cluster")
    selected = [
        cluster for cluster in clusters if any(entry.key in wanted for entry in cluster.entries)
    ]
    matched = {entry.key for cluster in selected for entry in cluster.entries}
    unmatched = sorted(wanted - matched)
    if unmatched:
        raise ValueError(
            "No duplicate cluster contains " + ", ".join(repr(key) for key in unmatched)
        )
    return selected


def merge_duplicates(
    lib: BibFile,
    clusters: list[DuplicateCluster] | None = None,
) -> DedupeMergeReport:
    """Merge duplicate clusters into their first entry.

    The function validates every cluster before mutating ``lib``. Ambiguous
    field/type disagreements raise :class:`DedupeConflictError` and leave the
    library untouched.
    """
    clusters = find_duplicate_clusters(lib) if clusters is None else clusters
    if not clusters:
        return DedupeMergeReport([], [], [])

    plans: list[_MergePlan] = []
    conflicts: list[MergeConflict] = []
    for cluster in clusters:
        plan, cluster_conflicts = _plan_cluster_merge(cluster)
        conflicts.extend(cluster_conflicts)
        if plan is not None:
            plans.append(plan)

    if conflicts:
        raise DedupeConflictError(conflicts, clusters)

    merged: list[ClusterMerge] = []
    removed: list[BibEntry] = []
    field_changes = 0
    for plan in plans:
        primary = plan.primary
        if plan.type_value is not None:
            set_entry_type(primary, plan.type_value)
        for name, value in plan.fields.items():
            if set_entry_field(primary, name, value):
                field_changes += 1
        for entry in plan.remove:
            lib.entries.remove(entry)
        removed.extend(plan.remove)
        # A crossref/xdata naming a merged-away key now names the survivor.
        retired = {entry.key for entry in plan.remove} - set(lib.entries.keys())
        rewrite_key_references(lib, [(key, primary.key) for key in sorted(retired)])
        merged.append(
            ClusterMerge(
                identity=plan.cluster.identity,
                primary_key=primary.key,
                removed_keys=[entry.key for entry in plan.remove],
                field_changes=dict(plan.fields),
                type_changed=plan.type_value,
            )
        )

    return DedupeMergeReport(clusters, merged, removed, field_changes)


@dataclass
class _MergePlan:
    cluster: DuplicateCluster
    primary: BibEntry
    remove: list[BibEntry]
    fields: dict[str, str]
    type_value: str | None = None


def _plan_cluster_merge(cluster: DuplicateCluster) -> tuple[_MergePlan | None, list[MergeConflict]]:
    primary = cluster.entries[0]
    fields = dict(primary.fields)
    type_value = primary.type
    changes: dict[str, str] = {}
    conflicts: list[MergeConflict] = []

    for entry in cluster.entries[1:]:
        resolved_type = _resolve_type(type_value, entry.type)
        if resolved_type is None:
            conflicts.append(
                MergeConflict(
                    cluster.identity, "type", {primary.key: type_value, entry.key: entry.type}
                )
            )
        elif resolved_type != type_value:
            type_value = resolved_type

        for name, value in entry.fields.items():
            if name not in fields:
                fields[name] = value
                changes[name] = value
                continue
            resolved = _resolve_field_value(name, fields[name], value)
            if resolved is None:
                conflicts.append(
                    MergeConflict(
                        cluster.identity,
                        name,
                        {primary.key: fields[name], entry.key: value},
                    )
                )
                continue
            if resolved != fields[name]:
                fields[name] = resolved
                changes[name] = resolved

    if conflicts:
        return None, conflicts

    type_change = type_value if type_value != primary.type else None
    return _MergePlan(cluster, primary, cluster.entries[1:], changes, type_change), []


def _resolve_type(left: str, right: str) -> str | None:
    if left.lower() == right.lower():
        return left
    if left.lower() == "misc":
        return right
    if right.lower() == "misc":
        return left
    return None


def _resolve_field_value(field: str, left: str, right: str) -> str | None:
    if field == "doi":
        return _resolve_doi(left, right)
    if field == "eprint":
        return _resolve_arxiv(left, right)
    if field in {"pmid", "pmcid", "isbn"}:
        return left if _normalize_identifier(left) == _normalize_identifier(right) else None
    if _normalize_text(left) == _normalize_text(right):
        return left
    if field in _DELIMITED_FIELDS:
        return _merge_delimited(left, right, ",")
    if field == "file":
        return _merge_delimited(left, right, ";")
    richer = _richer_containing_value(left, right)
    if richer is not None:
        return richer
    return None


def _resolve_doi(left: str, right: str) -> str | None:
    try:
        left_canonical = canonical_doi(left)
        right_canonical = canonical_doi(right)
    except ValueError:
        return left if _normalize_text(left) == _normalize_text(right) else None
    if left_canonical != right_canonical:
        return None
    return left


def _resolve_arxiv(left: str, right: str) -> str | None:
    left_id = normalize_arxiv(left)
    right_id = normalize_arxiv(right)
    if left_id and right_id and left_id == right_id:
        return left
    return left if _normalize_text(left) == _normalize_text(right) else None


def _merge_delimited(left: str, right: str, sep: str) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in (left, right):
        for item in raw.split(sep):
            clean = item.strip()
            key = _normalize_text(clean)
            if clean and key not in seen:
                items.append(clean)
                seen.add(key)
    return f"{sep} ".join(items)


def _richer_containing_value(left: str, right: str) -> str | None:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return left or right
    if left_norm in right_norm:
        return right if len(right.strip()) > len(left.strip()) else left
    if right_norm in left_norm:
        return left if len(left.strip()) >= len(right.strip()) else right
    return None


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _cluster_identity(entries: list[BibEntry]) -> WorkIdentifier:
    identifiers = WorkIdentifiers.from_pairs(
        [
            (identifier.kind, identifier.value)
            for entry in entries
            for identifier in evidence_from_entry(entry).identifiers.items
        ]
    )
    if primary := identifiers.primary():
        return primary
    first = entries[0]
    evidence = evidence_from_entry(first)
    author = evidence.authors[0] if evidence.authors else "anon"
    return WorkIdentifier(
        "fuzzy",
        f"{author}:{evidence.year}:{evidence.title_fingerprint}",
    )
