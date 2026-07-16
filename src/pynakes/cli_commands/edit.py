"""CLI command registration for ``pynakes ref edit``."""

import typer

from pynakes.cli_commands._reference import (
    parse_field_assignments,
    prompt_entry_type,
    prompt_required_fields,
    unique_entry,
)
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
    stdin_is_interactive,
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
    """Patch fields or type on one uniquely identified reference.

    Supplying no change options (``--field`` / ``--clear-field`` / ``--type``)
    starts an interactive prompt for the type and required fields, using the
    current values as defaults. That path needs an interactive terminal: with
    ``--json`` or headless stdin it errors instead.
    """
    interactive = not field and not clear_field and entry_type is None
    if interactive:
        if json_output:
            _emit_error(
                json_output,
                "InvalidInput",
                "No change options given; pass --field/--clear-field/--type — "
                "prompting is unavailable with --json",
            )
        if not stdin_is_interactive():
            _emit_error(
                json_output,
                "InvalidInput",
                "No change options given and stdin is not an interactive terminal; "
                "pass --field/--clear-field/--type to edit non-interactively",
            )
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
    entry = unique_entry(coll, key, json_output, action="ref_edit")
    if interactive:
        selected_type = entry_type or prompt_entry_type(entry.type)
        fields = prompt_required_fields(
            coll,
            selected_type,
            fields,
            existing=entry,
            clear_fields=clear_field,
        )
        if entry_type is None and selected_type != entry.type:
            entry_type = selected_type
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
