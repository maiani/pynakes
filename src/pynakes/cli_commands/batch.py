"""CLI command for transactional multi-operation edits: ``corpus batch``.

Applies a JSON list of operations to one `.bib` file in memory, previews a single
combined diff/plan, and commits them atomically (all-or-nothing).
"""

import json

import typer

from pynakes.batch import BatchError, apply_operations
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
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

#: What a caller can do about an operation that refused with a conflict.
_CONFLICT_OPTIONS = {
    "DuplicateCitationKey": [
        {
            "id": "repair_duplicates",
            "description": "Run keys repair first, then retry with the unique key",
        }
    ],
    "CitationKeyConflict": [
        {"id": "choose_key", "description": "Revise the operation to use a different key"}
    ],
}


def batch(
    file: str | None = bib_file_argument(),
    ops: str = typer.Option(None, "--ops", help="JSON array of operations (or use --ops-file)"),
    ops_file: str = typer.Option(
        None, "--ops-file", help="Path to a JSON file with the operations array"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
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
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    # Before the operations run: against a file that moved, one of them could
    # fail with an error that hides the real reason, which is the precondition.
    _check_expected_sha256(file, coll, params)
    try:
        op_results = apply_operations(coll, operations)
    except BatchError as exc:
        extra: dict = {"index": exc.index, "op": exc.op}
        if exc.code in _CONFLICT_OPTIONS:
            extra["options"] = _CONFLICT_OPTIONS[exc.code]
        _emit_error(json_output, exc.code, str(exc), **extra)
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
        "corpus_batch",
        coll,
        params,
        [f"{_verb('apply', params, 'Applied')} {len(op_results)} operation(s);"],
        operations=op_results,
    )


def register(app: typer.Typer) -> None:
    """Register the ``batch`` command."""
    app.command()(_safe(batch))
