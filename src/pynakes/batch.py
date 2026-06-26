"""Apply a sequence of operations to one :class:`~pynakes.engine.Collection`.

A *batch* lets an agent stage several edits and commit them in one atomic,
reviewable step: the operations mutate the in-memory collection, the caller
previews a single combined diff/plan, and one commit writes them together (or
nothing, if any operation fails). This exposes the engine's existing
stage-then-commit lifecycle to multi-operation callers.

Each operation is a dict ``{"op": "<name>", ...params}``. The supported names and
their parameters are in :data:`OPERATION_SPECS` (also surfaced in
``capabilities``). Operations map to the deterministic, in-memory
``Collection`` methods; network and conflict-prone operations (``add``,
``dedupe merge``) are intentionally excluded.
"""

from dataclasses import dataclass

from pynakes.engine import Collection
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
# Collection method. Keep this the single source of truth for the batch surface.
OPERATION_SPECS: dict[str, OperationSpec] = {
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
        "Run the standard normalization routine",
    ),
    "convert": OperationSpec(("to",), (), "Convert between bibtex and biblatex"),
    "metadata.set": OperationSpec(("key", "value"), ("namespace",), "Set a metadata key"),
}


def _validate(spec: OperationSpec, params: dict, index: int, op: str) -> None:
    allowed = set(spec.required) | set(spec.optional)
    extra = sorted(set(params) - allowed)
    if extra:
        raise BatchError(index, op, f"unknown parameter(s): {', '.join(extra)}")
    missing = [name for name in spec.required if name not in params]
    if missing:
        raise BatchError(index, op, f"missing parameter(s): {', '.join(missing)}")


def _apply_one(coll: Collection, op: str, params: dict) -> dict:
    """Dispatch one validated operation to the collection; return a result dict."""
    if op == "fields.rename":
        return {"changed": coll.rename_field(params["old"], params["new"], params.get("where"))}
    if op == "fields.move":
        return {"changed": coll.move_field(params["old"], params["new"], params.get("where"))}
    if op == "fields.append":
        return {"changed": coll.append_field(params["field"], params["value"], params.get("where"))}
    if op == "fields.clear":
        return {"changed": coll.clear_field(params["field"], params.get("where"))}
    if op == "fields.protect_title":
        return {
            "changed": coll.protect_title(
                field=params.get("field", "title"),
                where=params.get("where"),
                terms=params.get("terms"),
            )
        }
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
    raise AssertionError(f"unhandled op {op!r}")  # pragma: no cover


def apply_operations(coll: Collection, operations: list[dict]) -> list[dict]:
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
