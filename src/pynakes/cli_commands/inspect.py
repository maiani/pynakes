"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json

import typer

from pynakes.cli_common import (
    _entries,
    _safe,
)
from pynakes.io import load_bib
from pynakes.lint import lint as lint_lib

# --- inspect ---------------------------------------------------------------


def inspect(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a .bib file structure."""
    lib = load_bib(file)
    issues = lint_lib(lib)
    duplicates = lib.entries.duplicate_keys()

    if json_output:
        result = {
            "status": "success",
            "action": "inspect",
            "file": file,
            "encoding": lib.encoding,
            "line_ending": "crlf" if lib.line_ending == "\r\n" else "lf",
            "entry_count": len(lib.entries),
            "entries": [
                {"key": e.key, "type": e.type, "fields": dict(e.fields)}
                for e in lib.entries.values()
            ],
            "jabref_metadata": {
                "values": dict(lib.jabref_metadata),
                "blocks": [block.to_dict() for block in lib.jabref_metadata_blocks],
            },
            "pynakes_metadata": {
                "values": dict(lib.pynakes_metadata),
                "blocks": [block.to_dict() for block in lib.pynakes_metadata_blocks],
            },
            "duplicate_keys": duplicates,
            "issues": [i.to_dict() for i in issues],
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    le = "CRLF" if lib.line_ending == "\r\n" else "LF"
    typer.echo(f"{file}: {len(lib.entries)} {_entries(len(lib.entries))} ({lib.encoding}, {le})")
    for entry in lib.entries.values():
        typer.echo(f"  @{entry.type}{{{entry.key}}}  ({len(entry.fields)} fields)")
    if duplicates:
        typer.echo(f"Duplicate keys: {', '.join(f'{k} ×{n}' for k, n in duplicates.items())}")
    typer.echo(f"Issues: {len(issues)}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(inspect))
