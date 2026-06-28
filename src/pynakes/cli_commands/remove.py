"""CLI command registration for ``pynakes remove``.

Removes entries by citation key through the standard lifecycle. In a pinax,
removes the entry's materials from ``files-dir`` by default (``--keep-files``
opts out).
"""

import typer

from pynakes.cli_common import _emit_error, _finish_mod, _resolve_input_bib, _safe, _verb
from pynakes.engine import Bibliography


def remove(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    citekeys: list[str] = typer.Argument(..., help="One or more citation keys to remove"),
    keep_files: bool = typer.Option(
        False, "--keep-files", help="Keep Pinax materials on disk (default: remove them)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="Back up the file before writing"
    ),
) -> None:
    """Remove entries by citation key."""
    file = _resolve_input_bib(file, json_output)

    coll = Bibliography.open(file)

    total = 0
    removed_keys: list[str] = []
    warnings: list[str] = []
    for key in citekeys:
        count = coll.remove_entry(key)
        if count:
            total += count
            removed_keys.append(key)
        else:
            warnings.append(f"Citation key {key!r} not found; skipped.")

    if not total:
        _emit_error(json_output, "KeyNotFound", "No matching citation keys found to remove.")
        return

    material_removals: dict[str, list[str]] = {}
    if not keep_files and coll.files is not None:
        for key in removed_keys:
            if dry_run:
                removed = coll.files._materials_paths_for(key)
            else:
                removed = coll.files.remove_materials(key)
            if removed:
                material_removals[key] = removed

    label = ", ".join(removed_keys)
    human = [f"{_verb('remove', dry_run)} {total} entry/entries: {label}."]
    if not keep_files and material_removals:
        human.append("Removed Pinax materials.")
    elif keep_files:
        human.append("Kept Pinax materials on disk (--keep-files).")

    details = {
        "removed_keys": removed_keys,
        "removed_count": total,
        "keep_files": keep_files,
    }
    if material_removals:
        details["material_removals"] = material_removals

    _finish_mod(
        file, "remove", coll, dry_run, diff, json_output, human, warnings, backup=backup, **details
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("remove")(_safe(remove))
