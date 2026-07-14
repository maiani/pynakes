"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import fields as fields_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography

# --- fields ----------------------------------------------------------------


def _build_filter(where: str | None) -> fields_ops.QueryFilter:
    # A bad expression raises ValueError, which @_safe renders as a structured
    # exit-1 error (honoring --json), so no local handling is needed here.
    if where is None:
        return None
    return fields_ops.parse_query(where)


def _run_field_op(
    file: str,
    action: str,
    op: object,
    params: RunParams,
    details: dict,
    verb: str,
) -> None:
    coll = Bibliography.open(file)
    count = op(coll)
    _finish_mod(
        file,
        action,
        coll,
        params,
        [f"{verb} ({count} {_entries(count)} changed)."],
        **details,
    )


def fields_rename(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_rename",
        lambda coll: coll.rename_field(old, new, flt),
        params,
        {"old": old, "new": new, "where": where},
        f"{_verb('rename', params)} field {old!r} to {new!r}",
    )


def fields_set(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Replacement value"),
    where: str | None = typer.Option(None, "--where", help="Filter matching references"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Set or replace a field on matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_set",
        lambda coll: coll.set_field(field, value, flt),
        params,
        {"field": field, "value": value, "where": where},
        f"{_verb('set', params, 'Set')} field {field!r}",
    )


def fields_move(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field on matching references, without replacing the target."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_move",
        lambda coll: coll.move_field(old, new, flt),
        params,
        {"old": old, "new": new, "where": where},
        f"{_verb('move', params)} field {old!r} to {new!r}",
    )


def fields_append(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a delimited field on matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_append",
        lambda coll: coll.append_field(field, value, flt),
        params,
        {"field": field, "value": value, "where": where},
        f"{_verb('append', params, 'Appended')} {value!r} to field {field!r}",
    )


def fields_clear(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_clear",
        lambda coll: coll.clear_field(field, flt),
        params,
        {"field": field, "where": where},
        f"{_verb('clear', params, 'Cleared')} field {field!r}",
    )


def fields_protect_title(
    file: str | None = bib_file_argument(),
    field: str = typer.Option("title", "--field", help="Title-like field to protect"),
    term: list[str] | None = typer.Option(
        None, "--term", help="Additional exact term to brace-protect"
    ),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Brace-protect capitalization-sensitive tokens in title-like fields."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    flt = _build_filter(where)
    terms = term or []
    _run_field_op(
        file,
        "fields_protect_title",
        lambda coll: coll.protect_title(field, flt, terms),
        params,
        {"field": field, "terms": terms, "where": where},
        f"{_verb('protect', params, 'Protected')} capitalization in field {field!r}",
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("set")(_safe(fields_set))
    app.command("rename")(_safe(fields_rename))
    app.command("move")(_safe(fields_move))
    app.command("append")(_safe(fields_append))
    app.command("clear")(_safe(fields_clear))
    app.command("protect-title")(_safe(fields_protect_title))
