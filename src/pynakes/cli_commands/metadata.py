"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json

import typer

from pynakes import metadata as metadata_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography

# --- metadata --------------------------------------------------------------


def metadata_list(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List top-level metadata blocks (both jabref-meta and pynakes-meta)."""
    file = _resolve_input_bib(file, json_output)
    lib = Bibliography.open(file).lib
    all_blocks = lib.metadata_blocks

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "status": "success",
                    "action": "metadata_list",
                    "file": file,
                    "metadata": {
                        "values": dict(lib.jabref_metadata),
                        "blocks": [b.to_dict() for b in lib.jabref_metadata_blocks],
                    },
                    "pynakes_metadata": {
                        "values": dict(lib.pynakes_metadata),
                        "blocks": [b.to_dict() for b in lib.pynakes_metadata_blocks],
                    },
                    "effective": dict(lib.metadata),
                },
                indent=2,
            )
        )
        return

    if not all_blocks:
        typer.echo(f"{file}: no metadata found.")
        return
    for block in all_blocks:
        marker = "known" if block.known else "unknown"
        typer.echo(
            f"  [{block.namespace}:{marker}:{block.category}] "
            f"{block.key} = {block.normalized_value}"
        )


def metadata_set(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    key: str = typer.Argument(..., help="Metadata key"),
    value: str = typer.Argument(..., help="Metadata value"),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Target comment: jabref or pynakes. Default: auto (JabRef-native keys "
        "→ jabref-meta, everything else → pynakes-meta)",
    ),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="Allow writing an unrecognized key into jabref-meta"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Set one top-level metadata block (jabref-meta or pynakes-meta)."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    if namespace is not None and namespace not in {"jabref", "pynakes"}:
        _emit_error(
            json_output,
            "InvalidNamespace",
            f"Invalid namespace {namespace!r}; expected jabref or pynakes",
        )
    coll = Bibliography.open(file)
    try:
        update = coll.set_metadata(key, value, namespace=namespace, allow_unknown=allow_unknown)
    except metadata_ops.DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=[
                {
                    "id": "manual_edit",
                    "description": "Resolve duplicate metadata blocks manually, then retry",
                }
            ],
        )

    _finish_mod(
        file,
        "metadata_set",
        coll,
        params,
        [f"{_verb('set', params, 'Set')} {update.namespace}-meta {update.key!r}."],
        modified_entries=0,
        key=update.key,
        value=update.value.rstrip(";").strip(),
        created=update.created,
        namespace=update.namespace,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(metadata_list))
    app.command("set")(_safe(metadata_set))
