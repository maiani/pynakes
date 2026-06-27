"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from typing import Optional

import typer

from pynakes import fields as fields_ops
from pynakes.cli_common import (
    _entries,
    _finish_mod,
    _safe,
)
from pynakes.engine import Bibliography

# --- fields ----------------------------------------------------------------


def _build_filter(where: Optional[str]):
    # A bad expression raises ValueError, which @_safe renders as a structured
    # exit-1 error (honoring --json), so no local handling is needed here.
    if where is None:
        return None
    return fields_ops.parse_query(where)


def _run_field_op(file, action, op, dry_run, diff, json_output, details, verb):
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
        **details,
    )


def fields_rename(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_rename",
        lambda coll: coll.rename_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would rename' if dry_run else 'Renamed'} field {old!r} to {new!r}",
    )


def fields_move(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field to a new name, skipping entries that already have the target."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_move",
        lambda coll: coll.move_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would move' if dry_run else 'Moved'} field {old!r} to {new!r}",
    )


def fields_append(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a (comma-delimited) field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_append",
        lambda coll: coll.append_field(field, value, flt),
        dry_run,
        diff,
        json_output,
        {"field": field, "value": value, "where": where},
        f"{'Would append' if dry_run else 'Appended'} {value!r} to field {field!r}",
    )


def fields_clear(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_clear",
        lambda coll: coll.clear_field(field, flt),
        dry_run,
        diff,
        json_output,
        {"field": field, "where": where},
        f"{'Would clear' if dry_run else 'Cleared'} field {field!r}",
    )


def fields_protect_title(
    file: str = typer.Argument(...),
    field: str = typer.Option("title", "--field", help="Title-like field to protect"),
    term: Optional[list[str]] = typer.Option(
        None, "--term", help="Additional exact term to brace-protect"
    ),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Brace-protect capitalization-sensitive tokens in title-like fields."""
    flt = _build_filter(where)
    terms = term or []
    _run_field_op(
        file,
        "fields_protect_title",
        lambda coll: coll.protect_title(field, flt, terms),
        dry_run,
        diff,
        json_output,
        {"field": field, "terms": terms, "where": where},
        f"{'Would protect' if dry_run else 'Protected'} capitalization in field {field!r}",
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("rename")(_safe(fields_rename))
    app.command("move")(_safe(fields_move))
    app.command("append")(_safe(fields_append))
    app.command("clear")(_safe(fields_clear))
    app.command("protect-title")(_safe(fields_protect_title))
