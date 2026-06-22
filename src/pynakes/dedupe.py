"""Duplicate-work detection and conservative merge operations."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pynakes.authors import last_name, split_name_list
from pynakes.doi import canonical_doi
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.model import BibEntry, BibFile


@dataclass(frozen=True)
class WorkIdentity:
    """Stable identity for one bibliographic work."""

    kind: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


@dataclass
class DuplicateCluster:
    """A group of entries that appear to describe the same work."""

    identity: WorkIdentity
    reason: str
    entries: list[BibEntry]

    def to_dict(self) -> dict[str, object]:
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

    cluster: WorkIdentity
    field: str
    values: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster": self.cluster.to_dict(),
            "field": self.field,
            "values": dict(self.values),
        }


@dataclass
class ClusterMerge:
    """Summary of one cluster merge."""

    identity: WorkIdentity
    primary_key: str
    removed_keys: list[str]
    field_changes: dict[str, str] = field(default_factory=dict)
    type_changed: str | None = None

    def to_dict(self) -> dict[str, object]:
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

    @property
    def merged_clusters(self) -> int:
        return len(self.merged)

    @property
    def removed_entry_count(self) -> int:
        return len(self.removed_entries)

    @property
    def modified_entries(self) -> int:
        return self.merged_clusters + self.removed_entry_count

    def to_dict(self) -> dict[str, object]:
        return {
            "clusters": [cluster.to_dict() for cluster in self.clusters],
            "merged": [item.to_dict() for item in self.merged],
            "merged_clusters": self.merged_clusters,
            "removed_entries": self.removed_entry_count,
            "field_changes": self.field_changes,
        }


class DedupeConflictError(Exception):
    """Raised when duplicate entries cannot be merged without guessing."""

    def __init__(self, conflicts: list[MergeConflict], clusters: list[DuplicateCluster]) -> None:
        self.conflicts = conflicts
        self.clusters = clusters
        super().__init__(f"{len(conflicts)} dedupe merge conflict(s)")


_ID_PRIORITY = {"doi": 0, "arxiv": 1, "pmid": 2, "pmcid": 3, "isbn": 4}
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#\s]+)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_YEAR_RE = re.compile(r"\d{4}")
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

    stable_by_entry = [_stable_identities(entry) for entry in entries]
    by_identity: dict[WorkIdentity, list[int]] = defaultdict(list)
    for i, identities in enumerate(stable_by_entry):
        for identity in identities:
            by_identity[identity].append(i)
    for identity, indices in by_identity.items():
        if len(indices) < 2:
            continue
        first = indices[0]
        for other in indices[1:]:
            union(first, other, identity.kind)

    for i, left in enumerate(entries):
        for j in range(i + 1, len(entries)):
            right = entries[j]
            if not _stable_ids_compatible(stable_by_entry[i], stable_by_entry[j]):
                continue
            if _fuzzy_same_work(left, right):
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
    if _normalized_value(left) == _normalized_value(right):
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
        return left if _normalized_value(left) == _normalized_value(right) else None
    if left_canonical != right_canonical:
        return None
    return left


def _resolve_arxiv(left: str, right: str) -> str | None:
    left_id = _normalize_arxiv(left)
    right_id = _normalize_arxiv(right)
    if left_id and right_id and left_id == right_id:
        return left
    return left if _normalized_value(left) == _normalized_value(right) else None


def _merge_delimited(left: str, right: str, sep: str) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in (left, right):
        for item in raw.split(sep):
            clean = item.strip()
            key = _normalized_value(clean)
            if clean and key not in seen:
                items.append(clean)
                seen.add(key)
    return f"{sep} ".join(items)


def _richer_containing_value(left: str, right: str) -> str | None:
    left_norm = _normalized_value(left)
    right_norm = _normalized_value(right)
    if not left_norm or not right_norm:
        return left or right
    if left_norm in right_norm:
        return right if len(right.strip()) > len(left.strip()) else left
    if right_norm in left_norm:
        return left if len(left.strip()) >= len(right.strip()) else right
    return None


def _stable_identities(entry: BibEntry) -> list[WorkIdentity]:
    identities: list[WorkIdentity] = []
    doi = entry.fields.get("doi")
    if doi:
        try:
            identities.append(WorkIdentity("doi", canonical_doi(doi)))
        except ValueError:
            pass

    arxiv = _entry_arxiv_id(entry)
    if arxiv:
        identities.append(WorkIdentity("arxiv", arxiv))

    for field_name in ("pmid", "pmcid", "isbn"):
        value = entry.fields.get(field_name)
        if value:
            identities.append(WorkIdentity(field_name, _normalize_identifier(value)))

    return sorted(identities, key=lambda identity: _ID_PRIORITY[identity.kind])


def _entry_arxiv_id(entry: BibEntry) -> str | None:
    for field_name in ("arxiv", "eprint"):
        value = entry.fields.get(field_name)
        if not value:
            continue
        archive = entry.fields.get("archiveprefix") or entry.fields.get("eprinttype") or ""
        if field_name == "arxiv" or archive.lower() == "arxiv":
            normalized = _normalize_arxiv(value)
            if normalized:
                return normalized
    for field_name in ("url", "howpublished", "note"):
        value = entry.fields.get(field_name, "")
        match = _ARXIV_URL_RE.search(value)
        if match:
            normalized = _normalize_arxiv(match.group(1))
            if normalized:
                return normalized
    return None


def _normalize_arxiv(value: str) -> str | None:
    cleaned = value.strip().strip("{}<>")
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.IGNORECASE)
    match = _ARXIV_URL_RE.search(cleaned)
    if match:
        cleaned = match.group(1)
    cleaned = cleaned.removesuffix(".pdf")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    cleaned = cleaned.strip("/")
    return cleaned.lower() or None


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _stable_ids_compatible(left: list[WorkIdentity], right: list[WorkIdentity]) -> bool:
    if not left or not right:
        return True
    left_by_kind = {identity.kind: identity.value for identity in left}
    right_by_kind = {identity.kind: identity.value for identity in right}
    shared = set(left_by_kind).intersection(right_by_kind)
    if not shared:
        return True
    return all(left_by_kind[kind] == right_by_kind[kind] for kind in shared)


def _fuzzy_same_work(left: BibEntry, right: BibEntry) -> bool:
    if _year(left) != _year(right):
        return False
    left_title = _normalized_title(left)
    right_title = _normalized_title(right)
    if len(left_title) < 12 or len(right_title) < 12:
        return False
    if SequenceMatcher(None, left_title, right_title).ratio() < 0.92:
        return False
    return bool(set(_author_names(left)).intersection(_author_names(right)))


def _cluster_identity(entries: list[BibEntry]) -> WorkIdentity:
    stable: list[WorkIdentity] = []
    for entry in entries:
        stable.extend(_stable_identities(entry))
    if stable:
        return sorted(stable, key=lambda identity: _ID_PRIORITY[identity.kind])[0]
    first = entries[0]
    author = _author_names(first)[0] if _author_names(first) else "anon"
    return WorkIdentity("fuzzy", f"{author}:{_year(first)}:{_normalized_title(first)}")


def _year(entry: BibEntry) -> str:
    raw = entry.fields.get("year") or entry.fields.get("date") or ""
    match = _YEAR_RE.search(raw)
    return match.group(0) if match else ""


def _author_names(entry: BibEntry) -> list[str]:
    raw = entry.fields.get("author") or entry.fields.get("editor") or ""
    names = [last_name(name).lower() for name in split_name_list(raw)]
    return [name for name in names if name]


def _normalized_title(entry: BibEntry) -> str:
    return _normalized_value(entry.fields.get("title", ""))


def _normalized_value(value: str) -> str:
    value = value.replace("{", "").replace("}", "")
    words = re.findall(r"[a-z0-9]+", value.lower())
    return " ".join(words)
