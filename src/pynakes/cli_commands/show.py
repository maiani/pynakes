"""CLI command registration for ``pynakes ref show``."""

import json

import typer

from pynakes.cli_commands._reference import unique_entry
from pynakes.cli_common import _resolve_input_bib, _safe, bib_file_argument
from pynakes.engine import Bibliography


def show(
    key: str = typer.Argument(..., help="Citation key to display"),
    file: str | None = bib_file_argument(),
    resolved: bool = typer.Option(
        False, "--resolved", help="Include fields inherited through crossref/xdata"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one uniquely identified reference."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    entry = unique_entry(coll, key, json_output, action="ref_show")
    fields = coll.lib.resolved_fields(entry) if resolved else entry.fields
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "success",
                    "action": "ref_show",
                    "file": file,
                    "key": entry.key,
                    "entry_type": entry.type,
                    "fields": dict(fields),
                    "resolved": resolved,
                },
                indent=2,
            )
        )
        return
    typer.echo(f"@{entry.type}{{{entry.key}}}")
    for name, value in fields.items():
        typer.echo(f"  {name} = {value}")


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("show")(_safe(show))
