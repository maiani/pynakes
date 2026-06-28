"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import fields as fields_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
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
    dry_run: bool,
    diff: bool,
    json_output: bool,
    backup: bool,
    details: dict,
    verb: str,
) -> None:
    coll = Bibliography.open(file)
    count = op(coll)
    _finish_mod(
        file,
        action,
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} ({count} {_entries(count)} changed)."],
        backup=backup,
        **details,
    )


def fields_rename(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across entries."""
    file = _resolve_input_bib(file, json_output)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_rename",
        lambda coll: coll.rename_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        backup,
        {"old": old, "new": new, "where": where},
        f"{_verb('rename', dry_run)} field {old!r} to {new!r}",
    )


def fields_move(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field to a new name, skipping entries that already have the target."""
    file = _resolve_input_bib(file, json_output)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_move",
        lambda coll: coll.move_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        backup,
        {"old": old, "new": new, "where": where},
        f"{_verb('move', dry_run)} field {old!r} to {new!r}",
    )


def fields_append(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a (comma-delimited) field across entries."""
    file = _resolve_input_bib(file, json_output)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_append",
        lambda coll: coll.append_field(field, value, flt),
        dry_run,
        diff,
        json_output,
        backup,
        {"field": field, "value": value, "where": where},
        f"{_verb('append', dry_run, 'Appended')} {value!r} to field {field!r}",
    )


def fields_clear(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from entries."""
    file = _resolve_input_bib(file, json_output)
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_clear",
        lambda coll: coll.clear_field(field, flt),
        dry_run,
        diff,
        json_output,
        backup,
        {"field": field, "where": where},
        f"{_verb('clear', dry_run, 'Cleared')} field {field!r}",
    )


def fields_protect_title(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
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
    flt = _build_filter(where)
    terms = term or []
    _run_field_op(
        file,
        "fields_protect_title",
        lambda coll: coll.protect_title(field, flt, terms),
        dry_run,
        diff,
        json_output,
        backup,
        {"field": field, "terms": terms, "where": where},
        f"{_verb('protect', dry_run, 'Protected')} capitalization in field {field!r}",
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("rename")(_safe(fields_rename))
    app.command("move")(_safe(fields_move))
    app.command("append")(_safe(fields_append))
    app.command("clear")(_safe(fields_clear))
    app.command("protect-title")(_safe(fields_protect_title))
