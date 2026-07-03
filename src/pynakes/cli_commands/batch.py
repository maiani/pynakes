"""CLI command for transactional multi-operation edits: ``corpus batch``.

Applies a JSON list of operations to one `.bib` file in memory, previews a single
combined diff/plan, and commits them atomically (all-or-nothing).
"""

import json

import typer

from pynakes.batch import BatchError, apply_operations
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.metadata import DuplicateMetadataError


def batch(
    file: str | None = bib_file_argument(),
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
    if ops is not None and ops_file is not None:
        _emit_error(
            json_output, "InvalidInput", "Provide only one of --ops or --ops-file, not both"
        )
        return
    if ops is None and ops_file is None:
        _emit_error(json_output, "InvalidInput", "Provide either --ops or --ops-file")
        return
    raw = ops
    if ops_file is not None:
        with open(ops_file, encoding="utf-8") as handle:
            raw = handle.read()
    try:
        operations = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_error(json_output, "InvalidInput", f"operations are not valid JSON: {exc}")
        return

    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    try:
        op_results = apply_operations(coll, operations)
    except BatchError as exc:
        _emit_error(json_output, "InvalidInput", str(exc), index=exc.index)
        return
    except DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            options=[{"id": "manual_edit", "description": "Resolve duplicate blocks, then retry"}],
        )
        return

    _finish_mod(
        file,
        "batch",
        coll,
        params,
        [f"{_verb('apply', params, 'Applied')} {len(op_results)} operation(s);"],
        operations=op_results,
    )


def register(app: typer.Typer) -> None:
    """Register the ``batch`` command."""
    app.command()(_safe(batch))
