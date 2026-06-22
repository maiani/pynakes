"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json

import typer

from pynakes import groups as groups_ops
from pynakes.cli_common import (
    _emit_error,
    _entries,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection
from pynakes.io import load_bib

# --- groups ----------------------------------------------------------------


def groups_list(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all groups and their members."""
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


def groups_add_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group."""
    coll = Collection.open(file)
    _require_key(coll.lib, key, json_output)
    count = coll.add_to_group(key, group)
    verb = "Would add" if dry_run else "Added"
    _finish_mod(
        file,
        "groups_add_entry",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {key} to group {group!r} ({count} {_entries(count)} changed)."],
        key=key,
        group=group,
    )


def groups_remove_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to remove"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove an entry from a group."""
    coll = Collection.open(file)
    _require_key(coll.lib, key, json_output)
    count = coll.remove_from_group(key, group)
    verb = "Would remove" if dry_run else "Removed"
    _finish_mod(
        file,
        "groups_remove_entry",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {key} from group {group!r} ({count} {_entries(count)} changed)."],
        key=key,
        group=group,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(groups_list))
    app.command("add-entry")(_safe(groups_add_entry))
    app.command("remove-entry")(_safe(groups_remove_entry))
