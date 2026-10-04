"""Apply a sequence of operations to one :class:`~pynakes.engine.Bibliography`.

A *batch* lets an agent stage several edits and commit them in one atomic,
reviewable step: the operations mutate the in-memory bibliography, the caller
previews a single combined diff/plan, and one commit writes them together (or
nothing, if any operation fails). This exposes the engine's existing
stage-then-commit lifecycle to multi-operation callers.

Each operation is a dict ``{"op": "<name>", ...params}``. The supported names and
their parameters are in :data:`OPERATION_SPECS` (also surfaced in
``capabilities``).

Every operation maps to a deterministic, offline, in-memory ``Bibliography``
method. That is the line the batch surface draws, and it is drawn there on
purpose: a batch is previewed as one diff and approved as one decision, which
only means anything if replaying it would do the same thing again. So
``ref import`` stays out — it reaches the network, and what it returns depends
on when it is asked. Use it directly, then batch what follows.

An operation that *refuses* is not excluded by that rule. ``ref.add`` on a
taken key and ``dedupe.merge`` on an irreconcilable cluster both raise, and a
raised error aborts the batch before anything is committed, which is exactly
the all-or-nothing guarantee rather than a violation of it.

One asymmetry worth knowing: ``ref.remove`` removes the entry from the
bibliography and leaves any Pinax materials on disk. Deleting those is a
filesystem act, and a batch stages only in memory, so it cannot be part of the
same atomic commit. The ``ref remove`` command deletes them by default; the
batch operation never does.
"""

import re
from dataclasses import dataclass

from pynakes.engine import Bibliography
from pynakes.normalize import NormalizeOptions


class BatchError(ValueError):
    """A batch operation could not be applied. Carries the offending op index."""

    def __init__(self, index: int, op: str, message: str):
        self.index = index
        self.op = op
        super().__init__(f"operation {index} ({op!r}): {message}")


@dataclass(frozen=True)
class OperationSpec:
    """Declares one batch operation: its required and optional parameter names."""

    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    description: str = ""


# The supported operations, their parameters, and how each maps onto a
# Bibliography method. Keep this the single source of truth for the batch surface.
OPERATION_SPECS: dict[str, OperationSpec] = {
    "fields.set": OperationSpec(("field", "value"), ("where",), "Set or replace a field"),
    "fields.rename": OperationSpec(("old", "new"), ("where",), "Rename a field"),
    "fields.move": OperationSpec(
        ("old", "new"), ("where",), "Move a field where the target is unset"
    ),
    "fields.append": OperationSpec(("field", "value"), ("where",), "Append to a delimited field"),
    "fields.clear": OperationSpec(("field",), ("where",), "Remove a field"),
    "fields.protect_title": OperationSpec(
        (), ("field", "where", "terms"), "Brace-protect title case"
    ),
    "groups.add_entry": OperationSpec(("key", "group"), (), "Add an entry to a group"),
    "groups.remove_entry": OperationSpec(("key", "group"), (), "Remove an entry from a group"),
    "keys.generate": OperationSpec((), (), "Regenerate every citation key"),
    "keys.repair": OperationSpec((), (), "Make duplicate citation keys unique"),
    "keys.rename": OperationSpec(("old", "new"), (), "Rename one citation key in the .bib"),
    "normalize": OperationSpec(
        (),
        (
            "protect_titles",
            "title_fields",
            "protected_terms",
            "author_style",
            "journal_style",
            "journal_table",
            "ltwa_table",
            "normalize_dois",
            "identifier_case",
            "format_metadata",
        ),
        "Normalize entries (titles, authors, journals, DOIs, identifier case, ordering)",
    ),
    "convert": OperationSpec(("to",), (), "Convert between bibtex and biblatex"),
    "metadata.set": OperationSpec(("key", "value"), ("namespace",), "Set a metadata key"),
    "ref.add": OperationSpec(
        ("key", "entry_type"),
        ("fields", "allow_duplicate"),
        "Append one manually specified entry",
    ),
    "ref.edit": OperationSpec(
        ("key",),
        ("fields", "clear_fields", "entry_type"),
        "Patch fields or type on one uniquely identified entry",
    ),
    "ref.remove": OperationSpec(
        ("key",), (), "Remove entries by citation key (Pinax materials are left on disk)"
    ),
    "dedupe.merge": OperationSpec(
        (), ("keys",), "Merge duplicate clusters, or only those containing the given keys"
    ),
}


def _validate(spec: OperationSpec, params: dict, index: int, op: str) -> None:
    allowed = set(spec.required) | set(spec.optional)
    extra = sorted(set(params) - allowed)
    if extra:
        raise BatchError(index, op, f"unknown parameter(s): {', '.join(extra)}")
    missing = [name for name in spec.required if name not in params]
    if missing:
        raise BatchError(index, op, f"missing parameter(s): {', '.join(missing)}")


#: The field-name rule ``ref edit --field`` enforces, so a field edit means the
#: same thing whether it arrives as a command or as a batch operation.
_FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:-]*")


def _ref_edit_arguments(coll: Bibliography, params: dict) -> tuple[dict[str, str], list[str]]:
    """Validate a ``ref.edit`` operation exactly as ``ref edit`` validates its options.

    Field names must be names, ``key``/``type`` are not fields, values are
    trimmed, a field cannot be both set and cleared, and an unknown citation
    key is an input error rather than an internal one.
    """
    raw_fields = params.get("fields") or {}
    raw_clear = params.get("clear_fields") or []
    if not isinstance(raw_fields, dict):
        raise ValueError("'fields' must be an object of field names to values")
    if not isinstance(raw_clear, list) or not all(isinstance(name, str) for name in raw_clear):
        raise ValueError("'clear_fields' must be an array of field names")
    fields: dict[str, str] = {}
    for raw_name, value in raw_fields.items():
        name = str(raw_name).strip()
        if not _FIELD_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid field name: {name!r}")
        if name.lower() in {"key", "type"}:
            raise ValueError(f"{name!r} is not a field; use the citation key or entry_type")
        if not isinstance(value, str):
            raise ValueError(f"Field {name!r} needs a string value")
        fields[name] = value.strip()
    overlap = {name.lower() for name in fields} & {name.lower() for name in raw_clear}
    if overlap:
        raise ValueError(f"Cannot set and clear the same field(s): {', '.join(sorted(overlap))}")
    if not coll.entries.get_all(params["key"]):
        raise ValueError(f"No entry with citation key {params['key']!r}")
    return fields, list(raw_clear)


def _apply_one(coll: Bibliography, op: str, params: dict) -> dict:
    """Dispatch one validated operation to the bibliography; return a result dict."""
    if op == "fields.set":
        return {"changed": coll.set_field(params["field"], params["value"], params.get("where"))}
    if op == "fields.rename":
        return {"changed": coll.rename_field(params["old"], params["new"], params.get("where"))}
    if op == "fields.move":
        return {"changed": coll.move_field(params["old"], params["new"], params.get("where"))}
    if op == "fields.append":
        return {"changed": coll.append_field(params["field"], params["value"], params.get("where"))}
    if op == "fields.clear":
        return {"changed": coll.clear_field(params["field"], params.get("where"))}
    if op == "fields.protect_title":
        field = params.get("field", "title")
        where = coll._where(params.get("where"))
        selected = [entry for entry in coll.lib.entries.values() if where is None or where(entry)]
        changed = coll.protect_title(field=field, where=where, terms=params.get("terms"))
        result: dict[str, object] = {"changed": changed}
        if selected and not any(field in entry.fields for entry in selected):
            result["warnings"] = [f"No matching entries had field {field!r}"]
        return result
    if op == "groups.add_entry":
        return {"changed": coll.add_to_group(params["key"], params["group"])}
    if op == "groups.remove_entry":
        return {"changed": coll.remove_from_group(params["key"], params["group"])}
    if op == "keys.generate":
        return {"renames": [{"old": o, "new": n} for o, n in coll.generate_keys()]}
    if op == "keys.repair":
        return {"renames": [{"old": o, "new": n} for o, n in coll.repair_keys()]}
    if op == "keys.rename":
        return {"changed": coll.rename_key(params["old"], params["new"])}
    if op == "normalize":
        return {"operations": coll.normalize(NormalizeOptions(**params)).operations}
    if op == "convert":
        report = coll.convert(params["to"])
        return {"entries": report.entries, "fields_renamed": report.fields_renamed}
    if op == "metadata.set":
        update = coll.set_metadata(
            params["key"], params["value"], namespace=params.get("namespace")
        )
        return {"key": update.key, "namespace": update.namespace, "created": update.created}
    if op == "ref.add":
        entry = coll.add_entry(
            params["entry_type"],
            params["key"],
            dict(params.get("fields") or {}),
            allow_duplicate=bool(params.get("allow_duplicate", False)),
        )
        return {"key": entry.key, "entry_type": entry.type}
    if op == "ref.edit":
        fields, clear_fields = _ref_edit_arguments(coll, params)
        return coll.edit_entry(
            params["key"],
            fields=fields,
            clear_fields=clear_fields,
            entry_type=params.get("entry_type"),
        )
    if op == "ref.remove":
        removed = coll.remove_entry(params["key"])
        if not removed:
            raise ValueError(f"No entry with citation key {params['key']!r}")
        return {"removed": removed}
    if op == "dedupe.merge":
        keys = params.get("keys")
        report = coll.dedupe_merge(list(keys) if keys else None)
        return {
            "merged_clusters": report.merged_clusters,
            "removed_entries": report.removed_entry_count,
            "field_changes": report.field_changes,
        }
    raise NotImplementedError(f"unhandled batch operation {op!r}")


def apply_operations(coll: Bibliography, operations: list[dict]) -> list[dict]:
    """Apply ``operations`` to ``coll`` in order, staging them in memory.

    Returns one result dict per operation (``{"op": name, "result": {...}}``).
    Raises :class:`BatchError` for an unknown op or bad parameters (before any
    further op runs); operation-level failures (e.g. an invalid value, or a
    metadata conflict) propagate from the underlying method. The caller commits
    once afterwards, so a raised error leaves nothing written — the batch is
    all-or-nothing.
    """
    if not isinstance(operations, list):
        raise ValueError("batch operations must be a JSON array")
    results: list[dict] = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict) or "op" not in raw:
            raise BatchError(index, "?", "each operation needs an 'op' field")
        op = raw["op"]
        spec = OPERATION_SPECS.get(op)
        if spec is None:
            raise BatchError(index, op, "unknown operation")
        params = {k: v for k, v in raw.items() if k != "op"}
        _validate(spec, params, index, op)
        results.append({"op": op, "result": _apply_one(coll, op, params)})
    return results


def operation_catalog() -> dict:
    """Describe the supported batch operations (for ``capabilities``)."""
    return {
        name: {
            "required": list(spec.required),
            "optional": list(spec.optional),
            "description": spec.description,
        }
        for name, spec in OPERATION_SPECS.items()
    }
