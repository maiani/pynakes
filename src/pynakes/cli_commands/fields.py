"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from collections.abc import Callable

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
    bind_where_filter,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.model import QueryFilter

# --- fields ----------------------------------------------------------------


def _run_field_op(
    file: str,
    action: str,
    op: Callable[[Bibliography, QueryFilter], int],
    params: RunParams,
    details: dict,
    verb: str,
    *,
    where: str | None,
    key: list[str] | None,
    list_values: str | None = None,
) -> None:
    """Run one field operation on the ``--where``/``--key`` selection and report it.

    ``list_values`` names a field whose new value is listed per changed entry,
    for an operation whose result cannot be predicted from the command line
    alone (title protection decides token by token).
    """
    coll = Bibliography.open(file)
    warnings: list[dict] = []
    count = op(coll, bind_where_filter(coll, where, keys=key, warnings=warnings))
    human = [f"{verb} ({count} {_entries(count)} changed)."]
    if list_values is not None:
        for change in coll.change_plan()["entries"]:
            value = change.get("fields", {}).get(list_values)
            if change["change"] == "modified" and value is not None:
                human.append(f"  {change['key']}: {value['new']}")
    _finish_mod(file, action, coll, params, human, warnings=warnings, **details)


def fields_rename(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _run_field_op(
        file,
        "fields_rename",
        lambda coll, flt: coll.rename_field(old, new, flt),
        params,
        {"old": old, "new": new, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('rename', params)} field {old!r} to {new!r}",
        where=where,
        key=key,
    )


def fields_set(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Replacement value"),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Set or replace a field on matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _run_field_op(
        file,
        "fields_set",
        lambda coll, flt: coll.set_field(field, value, flt),
        params,
        {"field": field, "value": value, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('set', params, 'Set')} field {field!r}",
        where=where,
        key=key,
    )


def fields_move(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field on matching references, without replacing the target."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _run_field_op(
        file,
        "fields_move",
        lambda coll, flt: coll.move_field(old, new, flt),
        params,
        {"old": old, "new": new, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('move', params)} field {old!r} to {new!r}",
        where=where,
        key=key,
    )


def fields_append(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a delimited field on matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _run_field_op(
        file,
        "fields_append",
        lambda coll, flt: coll.append_field(field, value, flt),
        params,
        {"field": field, "value": value, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('append', params, 'Appended')} {value!r} to field {field!r}",
        where=where,
        key=key,
    )


def fields_clear(
    file: str | None = bib_file_argument(),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from matching references."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _run_field_op(
        file,
        "fields_clear",
        lambda coll, flt: coll.clear_field(field, flt),
        params,
        {"field": field, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('clear', params, 'Cleared')} field {field!r}",
        where=where,
        key=key,
    )


def fields_protect_title(
    file: str | None = bib_file_argument(),
    title_field: str = typer.Option("title", "--title-field", help="Title-like field to protect"),
    term: list[str] | None = typer.Option(
        None, "--term", help="Additional exact term to brace-protect"
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Brace-protect capitalization-sensitive tokens in title-like fields."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    terms = term or []
    _run_field_op(
        file,
        "fields_protect_title",
        lambda coll, flt: coll.protect_title(title_field, flt, terms),
        params,
        {"field": title_field, "terms": terms, "where": where, "keys": parse_key_selector(key)},
        f"{_verb('protect', params, 'Protected')} capitalization in field {title_field!r}",
        where=where,
        key=key,
        list_values=title_field,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("set")(_safe(fields_set))
    app.command("rename")(_safe(fields_rename))
    app.command("move")(_safe(fields_move))
    app.command("append")(_safe(fields_append))
    app.command("clear")(_safe(fields_clear))
    app.command("protect-title")(_safe(fields_protect_title))
