"""CLI command for transactional multi-operation edits: ``batch``.

Applies a JSON list of operations to one `.bib` file in memory, previews a single
combined diff/plan, and commits them atomically (all-or-nothing).
"""

import json as _json

import typer

from pynakes.batch import BatchError, apply_operations
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _emit,
    _emit_conflict,
    _emit_error,
    _preview_or_commit,
    _safe,
)
from pynakes.engine import Collection
from pynakes.metadata import DuplicateMetadataError


def batch(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    ops: str = typer.Option(None, "--ops", help="JSON array of operations (or use --ops-file)"),
    ops_file: str = typer.Option(
        None, "--ops-file", help="Path to a JSON file with the operations array"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    backup: bool = _BACKUP_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Apply a sequence of operations atomically (one preview, one commit)."""
    if (ops is None) == (ops_file is None):
        _emit_error(json_output, "InvalidInput", "Provide exactly one of --ops or --ops-file")
    raw = ops
    if ops_file is not None:
        with open(ops_file, encoding="utf-8") as handle:
            raw = handle.read()
    try:
        operations = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        _emit_error(json_output, "InvalidInput", f"operations are not valid JSON: {exc}")

    coll = Collection.open(file)
    try:
        op_results = apply_operations(coll, operations)
    except BatchError as exc:
        _emit_error(json_output, "InvalidInput", str(exc), index=exc.index)
    except DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            options=[{"id": "manual_edit", "description": "Resolve duplicate blocks, then retry"}],
        )

    plan = coll.change_plan()  # combined, before commit
    diff_text, modified, changed = _preview_or_commit(coll, dry_run, backup)
    _emit(
        json_output,
        {
            "status": "success",
            "action": "batch",
            "file": file,
            "dry_run": dry_run,
            "modified": modified,
            "modified_entries": changed,
            "warnings": [],
            "operations": op_results,
            "plan": plan,
        },
        [
            f"{'Would apply' if dry_run else 'Applied'} {len(op_results)} operation(s); "
            f"{changed} entry change(s)."
        ],
        diff_text,
        diff,
    )


def register(app: typer.Typer) -> None:
    """Register the ``batch`` command."""
    app.command()(_safe(batch))
