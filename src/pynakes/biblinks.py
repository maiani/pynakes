"""Bibliography links: declared parent/child relationships between ``.bib`` files.

A link joins two bibliographies, typically a manuscript's bibliography (the
child) and the master bibliography it draws from (the parent). Both files
declare it, each naming the other, in ``pynakes-meta``::

    biblink-parents: ../master.bib constraint=field-subset flow=down
    biblink-children: chapters/ch1.bib constraint=key-subset flow=down

A stored path resolves from the declaring file's folder. A link is independent
of any Library and needs no index or project layout. One file may have several
parents and several children, and be a child of one file and a parent of
another.

The constraint says what must hold between the two files:

- ``key-subset``: every citation key of the child exists in the parent.
- ``field-subset`` (the default): additionally, each child entry has the
  parent's entry type and, for every field the child has, the parent's value.
  Fields only the parent has may be omitted.

Values are compared after ``@string`` and ``#`` expansion, without their outer
delimiters and with whitespace collapsed; inner braces stay significant, since
they protect capitalization. A child entry's own fields are compared with the
parent entry's effective fields (``crossref`` and ``xdata`` inheritance
applied), because a copy often flattens a cross-reference. Field names and
entry types compare case-insensitively. Fields that record a bibliography's own
bookkeeping (:data:`LOCAL_FIELDS`, such as ``groups`` and ``file``) are not
compared.

The flow (``down``, ``up``, ``both`` or ``none``) records which way a sync may
move values; declaring a link never moves anything by itself. Checking a link
is read-only and reports what it could not check rather than guessing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pynakes._text_utils import find_field_name
from pynakes.bibtex_parser import ParseError
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.inheritance import resolve_entry_fields
from pynakes.io import load_bib, save_text
from pynakes.metadata.core import format_metadata_list, metadata_list_values
from pynakes.model import BibEntry, BibFile

PARENTS_KEY = "biblink-parents"
CHILDREN_KEY = "biblink-children"
CONSTRAINTS: tuple[str, ...] = ("field-subset", "key-subset")
FLOWS: tuple[str, ...] = ("down", "up", "both", "none")
DEFAULT_CONSTRAINT = "field-subset"
DEFAULT_FLOW = "down"

#: Fields that belong to one bibliography rather than to the work: group
#: memberships, linked files, and JabRef's per-library bookkeeping. A child and
#: its parent may differ on them without drift.
LOCAL_FIELDS = frozenset(
    {
        "groups",
        "file",
        "owner",
        "timestamp",
        "creationdate",
        "modificationdate",
        "readstatus",
        "ranking",
        "priority",
        "printed",
        "qualityassured",
        "relevance",
    }
)

#: What the linked file is to the declaring one.
Role = Literal["parent", "child"]
_KEY_FOR_ROLE: dict[str, str] = {"parent": PARENTS_KEY, "child": CHILDREN_KEY}
_OPPOSITE: dict[str, Role] = {"parent": "child", "child": "parent"}
_OPTION = re.compile(r"(?:^|\s+)(constraint|flow)=(\S*)\s*$")


@dataclass(frozen=True)
class LinkDeclaration:
    """One link as a bibliography declares it: the other file and its role."""

    path: str
    role: Role
    constraint: str = DEFAULT_CONSTRAINT
    flow: str = DEFAULT_FLOW

    def format(self) -> str:
        """Return the declaration as stored in its list item."""
        return f"{self.path} constraint={self.constraint} flow={self.flow}"

    def resolve(self, declaring_file: str | Path) -> Path:
        """Return the linked file's path, resolved from the declaring file's folder."""
        return Path(os.path.normpath(Path(declaring_file).parent / self.path))

    def to_dict(self) -> dict[str, str]:
        """Serialize the declaration for a JSON envelope."""
        return {
            "path": self.path,
            "role": self.role,
            "constraint": self.constraint,
            "flow": self.flow,
        }


def parse_declaration(item: str, role: Role) -> LinkDeclaration:
    """Parse one ``biblink-parents``/``biblink-children`` list item, or raise ``ValueError``."""
    rest = item.strip()
    options: dict[str, str] = {}
    while match := _OPTION.search(rest):
        name, value = match.group(1), match.group(2)
        if name in options:
            raise ValueError(f"Link {item.strip()!r} gives {name} twice")
        options[name] = value
        rest = rest[: match.start()]
    path = rest.strip()
    if not path:
        raise ValueError(f"Link {item.strip()!r} names no file")
    constraint = options.get("constraint", DEFAULT_CONSTRAINT)
    flow = options.get("flow", DEFAULT_FLOW)
    if constraint not in CONSTRAINTS:
        raise ValueError(
            f"Invalid link constraint {constraint!r}; expected one of: {', '.join(CONSTRAINTS)}"
        )
    if flow not in FLOWS:
        raise ValueError(f"Invalid link flow {flow!r}; expected one of: {', '.join(FLOWS)}")
    return LinkDeclaration(path, role, constraint, flow)


def validate_link_value(value: str, role: Role) -> None:
    """Raise ``ValueError`` unless ``value`` is a valid list of link declarations."""
    for item in _items(value):
        parse_declaration(item, role)


def _items(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def declared_links(lib: BibFile) -> list[LinkDeclaration]:
    """Return ``lib``'s link declarations: parents first, then children.

    Raises ``ValueError`` for a malformed declaration, as ``lint`` reports it.
    """
    links: list[LinkDeclaration] = []
    for role in ("parent", "child"):
        for value in metadata_list_values(lib, _KEY_FOR_ROLE[role]):
            links.append(parse_declaration(value, role))
    return links


def declarations_with(lib: BibFile, link: LinkDeclaration) -> str:
    """Return the new value of ``link``'s key with ``link`` added or replaced.

    An existing declaration naming the same file is replaced in place, so
    changing a constraint keeps the list's order.
    """
    if "," in link.path or ";" in link.path:
        raise ValueError(f"A linked file's path cannot contain ',' or ';': {link.path!r}")
    items: list[str] = []
    replaced = False
    for existing in _declarations(lib, link.role):
        if _same_path(existing.path, link.path):
            items.append(link.format())
            replaced = True
        else:
            items.append(existing.format())
    if not replaced:
        items.append(link.format())
    return format_metadata_list(items)


def declarations_without(lib: BibFile, path: str, role: Role) -> str | None:
    """Return ``role``'s key without the declaration of ``path``, or ``None`` if now empty."""
    items = [
        existing.format()
        for existing in _declarations(lib, role)
        if not _same_path(existing.path, path)
    ]
    return format_metadata_list(items) if items else None


def find_declaration(lib: BibFile, path: str, role: Role) -> LinkDeclaration | None:
    """Return ``lib``'s declaration of ``path`` in ``role``, if it has one."""
    return next((d for d in _declarations(lib, role) if _same_path(d.path, path)), None)


def key_for_role(role: Role) -> str:
    """Return the metadata key holding declarations of ``role``."""
    return _KEY_FOR_ROLE[role]


def opposite(role: Role) -> Role:
    """Return the role the other end declares: a parent declares its child."""
    return _OPPOSITE[role]


def relative_path(target: str | Path, declaring_file: str | Path) -> str:
    """Return ``target`` as a path relative to the declaring file's folder."""
    base = Path(os.path.abspath(Path(declaring_file).parent))
    return Path(os.path.relpath(os.path.abspath(target), base)).as_posix()


def _declarations(lib: BibFile, role: Role) -> list[LinkDeclaration]:
    return [parse_declaration(v, role) for v in metadata_list_values(lib, _KEY_FOR_ROLE[role])]


def _same_path(a: str, b: str) -> bool:
    return os.path.normpath(a) == os.path.normpath(b)


# --- checking ------------------------------------------------------------------


@dataclass
class LinkFinding:
    """One problem a link check found, with where it is."""

    type: str
    message: str
    key: str | None = None
    field: str | None = None
    child_value: str | None = None
    parent_value: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the finding, leaving out what does not apply."""
        out: dict[str, object] = {"type": self.type, "message": self.message}
        for name in ("key", "field", "child_value", "parent_value"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out


@dataclass
class LinkReport:
    """The result of checking one link from one of its ends."""

    declaration: LinkDeclaration
    child: str
    parent: str
    #: Whether every check the constraint asks for ran. ``False`` when a file
    #: could not be read, so an empty ``findings`` cannot be taken as agreement.
    complete: bool = True
    reciprocal: bool = True
    checked_entries: int = 0
    findings: list[LinkFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether the link holds: complete, reciprocal and without findings."""
        return self.complete and self.reciprocal and not self.findings

    def to_dict(self) -> dict[str, object]:
        """Serialize the report for a JSON envelope."""
        return {
            "declaration": self.declaration.to_dict(),
            "child": self.child,
            "parent": self.parent,
            "ok": self.ok,
            "complete": self.complete,
            "reciprocal": self.reciprocal,
            "checked_entries": self.checked_entries,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def compare_value(value: str) -> str:
    """Return ``value`` as link checks compare it: whitespace collapsed."""
    return " ".join(value.split())


def check_constraint(
    child: BibFile, parent: BibFile, constraint: str
) -> tuple[int, list[LinkFinding]]:
    """Check ``constraint`` between two loaded bibliographies.

    Returns the number of child entries checked and the findings. A key that
    appears more than once in either file is reported as ambiguous and not
    compared: choosing one of the entries would be a guess.
    """
    findings: list[LinkFinding] = []
    parent_duplicates = set(parent.entries.duplicate_keys())
    child_duplicates = set(child.entries.duplicate_keys())

    def lookup(key: str) -> BibEntry | None:
        return parent.entries.get(key)

    checked = 0
    seen: set[str] = set()
    for entry in child.entries.values():
        if entry.key in seen:
            continue
        seen.add(entry.key)
        if entry.key in child_duplicates or entry.key in parent_duplicates:
            where = "the child" if entry.key in child_duplicates else "the parent"
            findings.append(
                LinkFinding(
                    "ambiguous_key",
                    f"Citation key {entry.key!r} appears more than once in {where}; not compared",
                    key=entry.key,
                )
            )
            continue
        source = parent.entries.get(entry.key)
        if source is None:
            findings.append(
                LinkFinding(
                    "missing_key",
                    f"Citation key {entry.key!r} is in the child but not in the parent",
                    key=entry.key,
                )
            )
            continue
        checked += 1
        if constraint != "field-subset":
            continue
        if entry.type.lower() != source.type.lower():
            findings.append(
                LinkFinding(
                    "type_mismatch",
                    f"{entry.key!r} is @{entry.type} in the child and @{source.type} in the parent",
                    key=entry.key,
                    child_value=entry.type,
                    parent_value=source.type,
                )
            )
        effective = {
            name.lower(): value for name, value in resolve_entry_fields(source, lookup).items()
        }
        for name, value in entry.fields.items():
            lowered = name.lower()
            if lowered in LOCAL_FIELDS:
                continue
            expected = effective.get(lowered)
            if expected is None:
                findings.append(
                    LinkFinding(
                        "field_drift",
                        f"{entry.key!r} has {lowered} in the child but not in the parent",
                        key=entry.key,
                        field=lowered,
                        child_value=value,
                    )
                )
            elif compare_value(value) != compare_value(expected):
                findings.append(
                    LinkFinding(
                        "field_drift",
                        f"{entry.key!r} differs from the parent in {lowered}",
                        key=entry.key,
                        field=lowered,
                        child_value=value,
                        parent_value=expected,
                    )
                )
    return checked, findings


def check_links(path: str | Path) -> list[LinkReport]:
    """Check every link ``path`` declares, one hop, in declaration order.

    Each report says which file is the child and which the parent, whether the
    other end declares the link back with the same constraint and flow, and
    what the constraint found. Only declared links are followed; nothing is
    repaired.
    """
    path = Path(path)
    lib = load_bib(str(path))
    reports: list[LinkReport] = []
    for declaration in declared_links(lib):
        other_path = declaration.resolve(path)
        child_path, parent_path = (
            (path, other_path) if declaration.role == "parent" else (other_path, path)
        )
        report = LinkReport(declaration, str(child_path), str(parent_path))
        reports.append(report)
        if other_path.resolve() == path.resolve():
            report.complete = False
            report.findings.append(
                LinkFinding("self_link", "The bibliography declares a link to itself")
            )
            continue
        try:
            other = load_bib(str(other_path))
        except (OSError, ValueError, ParseError) as exc:
            report.complete = False
            report.findings.append(
                LinkFinding("unreadable_file", f"Could not read {other_path}: {exc}")
            )
            continue
        report.findings.extend(_reciprocity(report, path, other_path, other, declaration))
        child, parent = (lib, other) if declaration.role == "parent" else (other, lib)
        report.checked_entries, findings = check_constraint(child, parent, declaration.constraint)
        report.findings.extend(findings)
    return reports


def _reciprocity(
    report: LinkReport,
    path: Path,
    other_path: Path,
    other: BibFile,
    declaration: LinkDeclaration,
) -> list[LinkFinding]:
    try:
        back = find_declaration(other, relative_path(path, other_path), opposite(declaration.role))
    except ValueError as exc:
        report.reciprocal = False
        return [LinkFinding("not_reciprocal", f"{other_path} has a malformed link: {exc}")]
    if back is None:
        report.reciprocal = False
        role = opposite(declaration.role)
        return [
            LinkFinding(
                "not_reciprocal",
                f"{other_path} does not declare this bibliography as its {role} "
                f"(in {key_for_role(role)}); run biblink add from either end to repair it",
            )
        ]
    if (back.constraint, back.flow) != (declaration.constraint, declaration.flow):
        report.reciprocal = False
        return [
            LinkFinding(
                "declaration_mismatch",
                f"The two ends disagree: constraint={declaration.constraint} "
                f"flow={declaration.flow} here, constraint={back.constraint} "
                f"flow={back.flow} in {other_path}",
            )
        ]
    return []


# --- coordinated edits of both ends --------------------------------------------


def stage_link(
    child: Bibliography, parent: Bibliography, constraint: str, flow: str
) -> tuple[LinkDeclaration, LinkDeclaration]:
    """Stage the link's declaration in both files; return (child's, parent's).

    A declaration either end already has for the other file is replaced, so
    re-running ``biblink add`` with a new constraint or flow repairs or changes the
    link at both ends.
    """
    child_path, parent_path = _bound(child), _bound(parent)
    if child_path.resolve() == parent_path.resolve():
        raise ValueError("A bibliography cannot be linked to itself")
    child_side = LinkDeclaration(relative_path(parent_path, child_path), "parent", constraint, flow)
    parent_side = LinkDeclaration(relative_path(child_path, parent_path), "child", constraint, flow)
    for coll, declaration in ((child, child_side), (parent, parent_side)):
        coll.set_metadata(
            key_for_role(declaration.role),
            declarations_with(coll.lib, declaration),
            namespace="pynakes",
        )
    return child_side, parent_side


def stage_unlink(first: Bibliography, second: Bibliography) -> list[LinkDeclaration]:
    """Stage removing every declaration between the two files, at both ends.

    Returns the declarations removed, the first file's before the second's.
    Raises ``LookupError`` when neither file declares the other, so a mistyped
    path is an error rather than a change that does nothing.
    """
    removed: list[LinkDeclaration] = []
    for coll, other in ((first, second), (second, first)):
        target = relative_path(_bound(other), _bound(coll))
        for role in ("parent", "child"):
            declaration = find_declaration(coll.lib, target, role)
            if declaration is None:
                continue
            removed.append(declaration)
            remaining = declarations_without(coll.lib, target, role)
            if remaining is None:
                coll.remove_metadata(key_for_role(role), namespace="pynakes")
            else:
                coll.set_metadata(key_for_role(role), remaining, namespace="pynakes")
    if not removed:
        raise LookupError(f"{_bound(first)} and {_bound(second)} declare no link to each other")
    return removed


def commit_together(colls: list[Bibliography], *, backup: bool = False) -> list[bool]:
    """Commit each bibliography's staged edits, all of them or none.

    Every file is checked for an external change before anything is written.
    If a later write fails, the files already written are restored to the text
    they had, and the error is raised. Returns, per file, whether it changed.
    """
    for coll in colls:
        if coll.externally_changed():
            raise ExternalModificationError(_bound(coll))
    written: list[tuple[Bibliography, str]] = []
    changed: list[bool] = []
    try:
        for coll in colls:
            original = coll.pristine_text
            result = coll.commit(backup=backup)
            changed.append(result.modified)
            if result.modified:
                written.append((coll, original))
    except Exception:
        for coll, original in reversed(written):
            save_text(original, str(_bound(coll)), encoding=coll.lib.encoding, validate=True)
        raise
    return changed


def _bound(coll: Bibliography) -> Path:
    if coll.path is None:
        raise ValueError("A linked bibliography must be a file")
    return Path(coll.path)


# --- sync along one link -------------------------------------------------------

#: The flows that allow a sync in each direction.
_ALLOWED_FLOWS = {"down": {"down", "both"}, "up": {"up", "both"}}


@dataclass
class SyncChange:
    """One value a sync writes: ``field`` of ``key`` in ``file``, or its type when ``None``."""

    file: str
    key: str
    field: str | None
    old: str | None
    new: str
    source: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the change for a JSON envelope."""
        return {
            "file": self.file,
            "key": self.key,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "source": self.source,
        }


@dataclass
class SyncSkip:
    """Something a sync left alone, and why."""

    reason: str
    link: str
    key: str | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the skip, leaving out what does not apply."""
        out: dict[str, object] = {"link": self.link, "reason": self.reason}
        if self.key is not None:
            out["key"] = self.key
        if self.field is not None:
            out["field"] = self.field
        return out


@dataclass
class SyncPlan:
    """What a sync along the selected links would write, skip and refuse."""

    changes: list[SyncChange] = field(default_factory=list)
    skipped: list[SyncSkip] = field(default_factory=list)
    #: Fields two links would set to different values; none of them is written.
    conflicts: list[dict[str, object]] = field(default_factory=list)


def sync_links(
    path: str | Path,
    *,
    parents: bool = True,
    children: bool = True,
    direction: str = "down",
) -> tuple[SyncPlan, Bibliography, list[Bibliography]]:
    """Stage a one-step sync along ``path``'s selected links, in one direction.

    ``down`` copies the parent's value into each drifted field of the child, and
    the parent's entry type where they differ; ``up`` copies the child's values
    into the parent. A link is followed only when its flow allows the
    direction, it is ``field-subset``, and the other end declares it back
    alike. Entries are never added, removed or renamed, ``down`` never deletes
    a field only the child has, and ``up`` leaves a field the parent inherits
    through ``crossref``/``xdata``. Two links proposing different values for
    one field are a conflict, and that field is left as it is.

    Returns the plan, the opened bibliography for ``path``, and every opened
    bibliography the plan edits, all staged and uncommitted.
    """
    if direction not in _ALLOWED_FLOWS:
        raise ValueError(f"Unknown sync direction {direction!r}; expected down or up")
    path = Path(path)
    origin = Bibliography.open(path)
    opened: dict[Path, Bibliography] = {path.resolve(): origin}
    plan = SyncPlan()
    proposals: dict[tuple[Path, str, str | None], list[SyncChange]] = {}

    for declaration in declared_links(origin.lib):
        if not (parents if declaration.role == "parent" else children):
            continue
        link = declaration.path
        if declaration.flow not in _ALLOWED_FLOWS[direction]:
            reason = f"flow={declaration.flow} does not allow a sync {direction}"
            plan.skipped.append(SyncSkip(reason, link))
            continue
        if declaration.constraint != "field-subset":
            reason = "a key-subset link has no field values to sync"
            plan.skipped.append(SyncSkip(reason, link))
            continue
        other_path = declaration.resolve(path)
        try:
            other = opened.get(other_path.resolve()) or Bibliography.open(other_path)
        except (OSError, ValueError, ParseError) as exc:
            plan.skipped.append(SyncSkip(f"could not read {other_path}: {exc}", link))
            continue
        opened[other_path.resolve()] = other
        back = find_declaration(
            other.lib, relative_path(path, other_path), opposite(declaration.role)
        )
        if back is None or (back.constraint, back.flow) != (
            declaration.constraint,
            declaration.flow,
        ):
            reason = "the other end does not declare the link alike; repair it with biblink add"
            plan.skipped.append(SyncSkip(reason, link))
            continue
        child, parent = (origin, other) if declaration.role == "parent" else (other, origin)
        _, findings = check_constraint(child.lib, parent.lib, "field-subset")
        for finding in findings:
            change = _proposal(finding, child, parent, direction, link, plan)
            if change is not None:
                target = Path(change.file).resolve()
                proposals.setdefault((target, change.key, change.field), []).append(change)

    targets: dict[Path, Bibliography] = {}
    for (target, key, field_name), changes in proposals.items():
        values = {change.new for change in changes}
        if len(values) > 1:
            plan.conflicts.append(
                {
                    "file": changes[0].file,
                    "key": key,
                    "field": field_name,
                    "values": [{"source": c.source, "value": c.new} for c in changes],
                }
            )
            continue
        change = changes[0]
        _apply(opened[target], change)
        plan.changes.append(change)
        targets[target] = opened[target]
    return plan, origin, list(targets.values())


def _proposal(
    finding: LinkFinding,
    child: Bibliography,
    parent: Bibliography,
    direction: str,
    link: str,
    plan: SyncPlan,
) -> SyncChange | None:
    """Return the change ``finding`` calls for in ``direction``, or record why none."""
    key, field_name = finding.key, finding.field
    if finding.type in ("missing_key", "ambiguous_key") or key is None:
        reason = (
            "entries are not added by a sync"
            if finding.type == "missing_key"
            else "the key is ambiguous"
        )
        plan.skipped.append(SyncSkip(reason, link, key))
        return None
    source, target = (parent, child) if direction == "down" else (child, parent)
    new = finding.parent_value if direction == "down" else finding.child_value
    old = finding.child_value if direction == "down" else finding.parent_value
    if finding.type == "type_mismatch":
        assert new is not None
        return SyncChange(str(target.path), key, None, old, new, str(source.path))
    if direction == "down" and new is None:
        reason = "only the child has this field, and a sync never deletes"
        plan.skipped.append(SyncSkip(reason, link, key, field_name))
        return None
    parent_entry = parent.lib.entries.get(key)
    if direction == "up" and parent_entry is not None and old is not None:
        if field_name not in {name.lower() for name in parent_entry.fields}:
            reason = "the parent inherits this field through crossref or xdata"
            plan.skipped.append(SyncSkip(reason, link, key, field_name))
            return None
    assert new is not None
    return SyncChange(str(target.path), key, field_name, old, new, str(source.path))


def _apply(target: Bibliography, change: SyncChange) -> None:
    entry = target.lib.entries.get(change.key)
    if entry is None:
        return
    if change.field is None:
        set_entry_type(entry, change.new)
        return
    name = find_field_name(entry.fields, change.field) or change.field
    set_entry_field(entry, name, change.new)
