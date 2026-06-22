"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json
from typing import Optional

import typer

from pynakes import metadata as metadata_ops
from pynakes.cli_common import (
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection
from pynakes.io import load_bib

# --- metadata --------------------------------------------------------------


def metadata_list(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List top-level metadata blocks (both jabref-meta and pynakes-meta)."""
    lib = load_bib(file)
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
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Metadata key"),
    value: str = typer.Argument(..., help="Metadata value"),
    namespace: Optional[str] = typer.Option(
        None,
        "--namespace",
        help="Target comment: jabref or pynakes. Default: auto (JabRef-native keys "
        "→ jabref-meta, everything else → pynakes-meta)",
    ),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="Allow writing an unrecognized key into jabref-meta"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Set one top-level metadata block (jabref-meta or pynakes-meta)."""
    if namespace is not None and namespace not in {"jabref", "pynakes"}:
        _emit_error(
            json_output,
            "InvalidNamespace",
            f"Invalid namespace {namespace!r}; expected jabref or pynakes",
        )
    coll = Collection.open(file)
    try:
        update = coll.set_metadata(key, value, namespace=namespace, allow_unknown=allow_unknown)
    except metadata_ops.DuplicateJabRefMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateJabRefMetadata",
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

    verb = "Would set" if dry_run else "Set"
    _finish_mod(
        file,
        "metadata_set",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {update.namespace}-meta {update.key!r}."],
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
