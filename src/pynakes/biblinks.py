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

from pynakes.bibtex_parser import ParseError
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
