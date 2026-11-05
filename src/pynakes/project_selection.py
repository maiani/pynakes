"""Select or refresh a source reference in an independent project bibliography.

A versioned, base64 JSON comment attached to the entry records source identity
and both accepted field baselines. It moves with citation-key renames and commits
atomically with the entry. It is provenance, not a backend connection setting.
No source is written, no material bytes are transferred, and conflicts require
review rather than last-writer-wins replacement.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from pynakes.convert import convert
from pynakes.editing import remove_entry_field, set_entry_field, set_entry_type
from pynakes.engine import Bibliography
from pynakes.fields import check_field_value
from pynakes.identity import compare_work_evidence, evidence_from_entry
from pynakes.library.backends.base import (
    ItemRef,
    LibraryBackend,
    ReferenceView,
    Revision,
    SourceChanged,
    SourceUnsupported,
)
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile

_PREFIX = "pynakes-source-v1: "
_MAPPING = 1


class SelectionConflict(SourceChanged):
    """The project/source requires an explicit reconciliation decision."""

    def __init__(
        self,
        message: str,
        *,
        conflicts: tuple[SelectionFieldConflict, ...] = (),
        source_revision: Revision | None = None,
    ) -> None:
        super().__init__(message)
        self.conflicts = conflicts
        self.source_revision = source_revision


@dataclass(frozen=True)
class SelectionFieldConflict:
    """One divergent field; ``None`` means absent and ``@type`` is entry type."""

    field: str
    baseline_source: str | None
    baseline_project: str | None
    source: str | None
    project: str | None


@dataclass(frozen=True)
class SelectionPlan:
    """A staged Bibliography and inspectable source mapping/loss report."""

    bibliography: Bibliography
    reference: ReferenceView
    key: str
    changes: tuple[str, ...]
    issues: tuple[str, ...]


def _decode(text: str) -> dict:
    try:
        token = text.removeprefix(_PREFIX)
        if len(token) > 4 * 1024 * 1024:
            raise ValueError("Oversized binding")
        result = json.loads(base64.b64decode(token, validate=True))
        if not isinstance(result, dict) or result.get("schema") != _MAPPING:
            raise ValueError("Unsupported source binding schema")
        if not all(isinstance(result[name], str) for name in ("source_type", "target_type")):
            raise ValueError("Invalid baseline types")
        for name in ("source_fields", "target_fields"):
            fields = result[name]
            if not isinstance(fields, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in fields.items()
            ):
                raise ValueError("Invalid baseline fields")
        if (
            not isinstance(result["ref"], dict)
            or set(result["ref"]) != {"source", "key"}
            or not all(isinstance(v, str) for v in result["ref"].values())
        ):
            raise ValueError("Invalid source reference")
        return result
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise SelectionConflict("Invalid source binding; review the project comment") from exc


def _binding(ref: ItemRef, source_type: str, source: dict, target_type: str, target: dict) -> str:
    value = {
        "schema": _MAPPING,
        "ref": ref.to_dict(),
        "source_type": source_type,
        "source_fields": source,
        "target_type": target_type,
        "target_fields": target,
    }
    return (
        _PREFIX
        + base64.b64encode(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).decode()
    )


def prepare_selection(
    backend: LibraryBackend,
    ref: ItemRef,
    bibliography: Bibliography,
    *,
    key: str | None = None,
    resolutions: Mapping[str, Literal["source", "project"]] | None = None,
    expected_revision: Revision | None = None,
) -> SelectionPlan:
    """Stage one source reference, or three-way refresh its existing binding.

    Preview/diff the returned bibliography, then call its normal ``commit()``.
    Source freshness is checked again at commit; target bytes retain the normal
    Bibliography guard. Repeated selection is idempotent. Source and target edits
    to different fields merge; divergent edits to the same field refuse the whole
    operation. Local-only fields and project citation keys remain independent.
    Unknown source data is reported via ``issues``, never treated as absent data
    that should delete an arbitrary project field.

    Resolve reviewed conflicts with ``resolutions={"title": "project"}`` (or
    ``"source"``); use ``@type`` for the entry type. Decisions require the
    conflict's ``expected_revision`` and apply only to currently conflicting
    fields. Accepted source and project baselines advance together, so keeping
    a deliberate project difference is idempotent. Future divergent edits still
    require review. These are one-operation decisions, not persistent policies.
    """
    resolutions = dict(resolutions or {})
    if any(
        not isinstance(k, str) or v not in ("source", "project") for k, v in resolutions.items()
    ):
        raise ValueError("Resolutions must map field names to source or project")
    if resolutions and expected_revision is None:
        raise ValueError("Conflict decisions require the reviewed source revision")
    if bibliography.preview() != bibliography.pristine_text:
        raise SelectionConflict(
            "Select into a pristine Bibliography; commit or reset staged changes first"
        )
    if bibliography.duplicate_keys():
        raise SelectionConflict("Project contains duplicate citation keys")
    if bibliography.path is not None and bibliography._fingerprint is None:
        raise SelectionConflict("Open the project file with Bibliography.open for guarded writes")
    record = backend.get(ref, expected_revision=expected_revision)
    if record.entry_type is None:
        raise SourceUnsupported("Source item has no supported citation projection")
    projected = BibEntry(key="", type=record.entry_type, fields=dict(record.fields))
    dialect = library_dialect(bibliography.lib)
    conversion = convert(BibFile(entries=[projected]), dialect)
    if dialect == "bibtex" and projected.type == "online":
        set_entry_type(projected, "misc")
    record = replace(
        record,
        entry_type=projected.type,
        fields=tuple(projected.fields.items()),
        issues=record.issues + tuple(w["message"] for w in conversion.warnings),
    )
    assert record.entry_type is not None  # Conversion preserves a concrete citation type.
    incoming = dict(record.fields)
    if not incoming.get("title"):
        raise SourceUnsupported("Source reference has no title")
    for field, value in incoming.items():
        check_field_value(field, value)
    found = []
    for entry in bibliography.entries.values():
        comments = [
            text for _, text in bibliography.entry_comments(entry.key) if text.startswith(_PREFIX)
        ]
        if len(comments) > 1:
            raise SelectionConflict("Multiple source bindings on a project entry")
        for comment in comments:
            data = _decode(comment)
            if data["ref"] == ref.to_dict():
                found.append((entry, comment, data))
    if len(found) > 1:
        raise SelectionConflict("Source is bound to several project entries")
    changes = []
    if found:
        entry, old_comment, baseline = found[0]
        if key is not None and key != entry.key:
            raise SelectionConflict("Source already has an independent project key: " + entry.key)
        desired = dict(entry.fields)
        accepted_target = dict(baseline["target_fields"])
        accepted_type = baseline["target_type"]
        conflicts: list[SelectionFieldConflict] = []
        used_resolutions = set()
        for field in sorted(set(baseline["source_fields"]) | set(incoming)):
            before = baseline["source_fields"].get(field)
            after = incoming.get(field)
            if before == after:
                continue
            local = entry.fields.get(field)
            accepted = baseline["target_fields"].get(field)
            if local != accepted and local != after:
                decision = resolutions.get(field)
                if decision is None:
                    conflicts.append(SelectionFieldConflict(field, before, accepted, after, local))
                    continue
                used_resolutions.add(field)
                chosen = local if decision == "project" else after
            else:
                chosen = after
            if chosen is None:
                desired.pop(field, None)
            else:
                desired[field] = chosen
            if chosen is None:
                accepted_target.pop(field, None)
            else:
                accepted_target[field] = chosen
            changes.append(field)
        desired_type = entry.type
        if record.entry_type != baseline["source_type"]:
            if entry.type not in (baseline["target_type"], record.entry_type):
                decision = resolutions.get("@type")
                if decision is None:
                    conflicts.append(
                        SelectionFieldConflict(
                            "@type",
                            baseline["source_type"],
                            baseline["target_type"],
                            record.entry_type,
                            entry.type,
                        )
                    )
                else:
                    used_resolutions.add("@type")
                    desired_type = entry.type if decision == "project" else record.entry_type
                    accepted_type = desired_type
                    changes.append("type")
            else:
                desired_type = record.entry_type
                accepted_type = record.entry_type
                changes.append("type")
        if conflicts:
            raise SelectionConflict(
                "Conflicting source/project edits: " + ", ".join(c.field for c in conflicts),
                conflicts=tuple(conflicts),
                source_revision=record.revision,
            )
        if unused := set(resolutions) - used_resolutions:
            raise SelectionConflict(
                "Decisions do not match current conflicts: " + ", ".join(sorted(unused))
            )
        for field in sorted(set(entry.fields) - set(desired)):
            remove_entry_field(entry, field)
        for field, value in desired.items():
            set_entry_field(entry, field, value)
        set_entry_type(entry, desired_type)
    else:
        if resolutions:
            raise SelectionConflict("Conflict decisions require an existing source binding")
        candidate = BibEntry(key=key or "", type=record.entry_type, fields=incoming)
        evidence = evidence_from_entry(candidate)
        for existing in bibliography.entries.values():
            match = compare_work_evidence(evidence, evidence_from_entry(existing))
            if (key and existing.key == key) or match.is_match:
                raise SelectionConflict(
                    "Existing project record needs reconciliation: " + existing.key
                )
        entry = bibliography.add_entry(record.entry_type, key, incoming)
        old_comment = None
        changes.append("added")
        accepted_target = dict(entry.fields)
        accepted_type = entry.type
    comment = _binding(ref, record.entry_type, incoming, accepted_type, accepted_target)
    if comment != old_comment:
        if old_comment:
            bibliography.remove_entry_comment(entry.key, old_comment)
        bibliography._insert_directive(entry, "% " + comment)

    # Keep the entire source revision namespace; an item version alone is insufficient.
    def guard() -> None:
        backend.get(ref, expected_revision=record.revision)

    bibliography._commit_guards.append(guard)
    return SelectionPlan(bibliography, record, entry.key, tuple(sorted(changes)), record.issues)
