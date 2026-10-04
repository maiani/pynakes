"""CLI command registration for ``pynakes ref remove``.

Removes entries by citation key through the standard lifecycle. In a pinax,
removes the entry's materials from ``pinax-files-dir`` by default (``--keep-files``
opts out).
"""

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography


def remove(
    file: str | None = bib_file_argument(),
    citekeys: list[str] = typer.Argument(..., help="One or more citation keys to remove"),
    keep_files: bool = typer.Option(
        False, "--keep-files", help="Keep Pinax materials on disk (default: remove them)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
) -> None:
    """Remove entries by citation key."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )

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
        store = coll.files
        for key in removed_keys:
            planned = store._materials_paths_for(key)
            if planned:
                material_removals[key] = planned
                # Deleted only once the entry's removal is on disk: a failed
                # commit must not cost the materials.
                coll.after_commit(lambda key=key: store.remove_materials(key))

    label = ", ".join(removed_keys)
    human = [f"{_verb('remove', params)} {total} {_entries(total)}: {label}."]
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

    _finish_mod(file, "remove", coll, params, human, warnings=warnings, **details)


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("remove")(_safe(remove))
