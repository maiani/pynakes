"""CLI command registration for ``pynakes ref edit``."""

import typer

from pynakes.cli_commands._reference import parse_field_assignments, unique_entry
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography


def edit(
    key: str = typer.Argument(..., help="Citation key to edit"),
    file: str | None = bib_file_argument(),
    field: list[str] = typer.Option(
        [], "--field", "-f", help="Set or replace a field; repeatable: name=value"
    ),
    clear_field: list[str] = typer.Option([], "--clear-field", help="Remove a field; repeatable"),
    entry_type: str | None = typer.Option(None, "--type", help="Set the entry type"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Patch fields or type on one uniquely identified reference."""
    if not field and not clear_field and entry_type is None:
        _emit_error(json_output, "InvalidInput", "ref edit requires a change option")
    fields = parse_field_assignments(field)
    overlap = {name.lower() for name in fields} & {name.lower() for name in clear_field}
    if overlap:
        _emit_error(
            json_output,
            "InvalidInput",
            f"Cannot set and clear the same field(s): {', '.join(sorted(overlap))}",
        )
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    unique_entry(coll, key, json_output, action="ref_edit")
    operations = coll.edit_entry(
        key,
        fields=fields,
        clear_fields=clear_field,
        entry_type=entry_type,
    )
    _finish_mod(
        file,
        "ref_edit",
        coll,
        params,
        [f"Edited reference {key}."],
        key=key,
        fields=dict(fields),
        cleared_fields=list(clear_field),
        entry_type=entry_type,
        operations=operations,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("edit")(_safe(edit))
