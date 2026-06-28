"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json

import typer

from pynakes import groups as groups_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography
from pynakes.io import load_bib

# --- groups ----------------------------------------------------------------


def groups_list(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all groups and their members."""
    file = _resolve_input_bib(file, json_output)
    lib = load_bib(file)
    names = groups_ops.list_groups(lib)
    members = {g: groups_ops.list_entries_in_group(lib, g) for g in names}

    if json_output:
        typer.echo(
            _json.dumps(
                {"status": "success", "action": "groups_list", "file": file, "groups": members},
                indent=2,
            )
        )
        return

    if not names:
        typer.echo(f"{file}: no groups found.")
        return
    for name in names:
        typer.echo(f"{name} ({len(members[name])}): {', '.join(members[name])}")


def _require_key(lib, key: str, json_output: bool) -> None:
    if key not in lib.entries:
        _emit_error(json_output, "KeyNotFound", f"No entry with key {key!r} in the library")


def _group_mod_entry(
    file: str,
    key: str,
    group: str,
    params: RunParams,
    add: bool,
) -> None:
    """Shared implementation for add-entry and remove-entry."""
    coll = Bibliography.open(file)
    _require_key(coll.lib, key, params.json_output)
    if add:
        action, count = "groups_add_entry", coll.add_to_group(key, group)
        msg = (
            f"{_verb('add', params)} {key} to group {group!r} ({count} {_entries(count)} changed)."
        )
    else:
        action, count = "groups_remove_entry", coll.remove_from_group(key, group)
        msg = f"{_verb('remove', params)} {key} from group {group!r} ({count} {_entries(count)} changed)."
    _finish_mod(file, action, coll, params, [msg], key=key, group=group)


def groups_add_entry(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    _group_mod_entry(file, key, group, params, add=True)


def groups_remove_entry(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    key: str = typer.Argument(..., help="Citation key to remove"),
    group: str = typer.Argument(..., help="Group name"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove an entry from a group."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    _group_mod_entry(file, key, group, params, add=False)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(groups_list))
    app.command("add-entry")(_safe(groups_add_entry))
    app.command("remove-entry")(_safe(groups_remove_entry))
