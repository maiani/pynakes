"""CLI command registration for ``pynakes ref add``."""

import typer

from pynakes.cli_commands._reference import parse_field_assignments
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography


def add(
    key: str = typer.Argument(..., help="Citation key for the new entry"),
    file: str | None = bib_file_argument(),
    entry_type: str = typer.Option("article", "--type", help="BibTeX/BibLaTeX entry type"),
    field: list[str] = typer.Option(
        [], "--field", "-f", help="Field assignment, repeatable: name=value"
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Append even if the citation key already exists"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a manually specified reference entry."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)
    try:
        fields = parse_field_assignments(field)
        coll = Bibliography.open(file)
        entry = coll.add_entry(
            entry_type,
            key,
            fields,
            allow_duplicate=allow_duplicate,
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))
        return

    human = [f"{_verb('add', params)} {entry.type} {entry.key}."]
    _finish_mod(
        file,
        "add",
        coll,
        params,
        human,
        key=entry.key,
        entry_type=entry.type,
        fields=dict(entry.fields),
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("add")(_safe(add))
