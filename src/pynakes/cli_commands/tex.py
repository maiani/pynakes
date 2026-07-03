"""CLI command registration for ``pynakes tex`` (linked LaTeX sources).

Manage the list of LaTeX source files that cite the library, stored as the
``tex-sources`` metadata key. Commands ``list``, ``add``, ``remove``, and
``clear`` let users inspect and edit the source list without reaching for the
generic ``metadata set`` command.
"""

from pathlib import Path

import typer

from pynakes.cli_common import (
    RunParams,
    _emit,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_option,
)
from pynakes.engine import Bibliography
from pynakes.metadata import format_metadata_list, metadata_list_values
from pynakes.usage import TEX_SOURCES_KEY, tex_sources_from_metadata


def _parse_stored_sources(lib) -> list[str]:
    """Return the raw ``tex-sources`` paths as stored (not resolved)."""
    return list(metadata_list_values(lib, TEX_SOURCES_KEY))


def _set_stored_sources(coll: Bibliography, sources: list[str]) -> None:
    """Store linked sources canonically in pynakes-meta and drop stale JabRef copies."""
    coll.set_metadata(TEX_SOURCES_KEY, format_metadata_list(sources), namespace="pynakes")
    coll.remove_metadata(TEX_SOURCES_KEY, namespace="jabref")


def _clear_stored_sources(coll: Bibliography) -> None:
    """Remove linked-source metadata from both namespaces."""
    coll.remove_metadata(TEX_SOURCES_KEY, namespace="pynakes")
    coll.remove_metadata(TEX_SOURCES_KEY, namespace="jabref")


_FILE_OPTION = bib_file_option()


def tex_list(
    file: str | None = _FILE_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List the TeX source files linked to this library."""
    file = _resolve_input_bib(file, json_output)
    lib = Bibliography.open(file).lib
    sources = tex_sources_from_metadata(lib, Path(file).parent)

    if json_output:
        _emit(
            json_output,
            {
                "status": "success",
                "action": "tex_list",
                "file": file,
                "sources": sources,
            },
            [],
        )
        return

    if not sources:
        typer.echo(f"{file}: no TeX sources linked.")
        return
    typer.echo(f"{file}:")
    for s in sources:
        typer.echo(f"  {s}")


def tex_add(
    paths: list[str] = typer.Argument(..., help="One or more .tex files or directories to link"),
    file: str | None = _FILE_OPTION,
    backup: bool = typer.Option(
        False, "--backup", help="Also write a <file>.bak copy before overwriting"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Link one or more TeX source files or directories to this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    current = _parse_stored_sources(coll.lib)

    added: list[str] = []
    for p in paths:
        if p not in current:
            current.append(p)
            added.append(p)

    if not added:
        _emit(
            params.json_output,
            {
                "status": "success",
                "action": "tex_add",
                "file": file,
                "dry_run": params.dry_run,
                "modified": False,
                "modified_entries": 0,
                "warnings": [],
                "added": [],
            },
            ["No new sources to add."],
        )
        return

    _set_stored_sources(coll, current)

    human = [f"{_verb('link', params)} {len(added)} source(s):"] + [f"  + {p}" for p in added]
    _finish_mod(
        file,
        "tex_add",
        coll,
        params,
        human,
        modified_entries=0,
        added=added,
        sources=current,
    )


def tex_remove(
    paths: list[str] = typer.Argument(
        ..., help="One or more TeX source files or directories to unlink"
    ),
    file: str | None = _FILE_OPTION,
    backup: bool = typer.Option(
        False, "--backup", help="Also write a <file>.bak copy before overwriting"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Unlink one or more TeX source files or directories from this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    current = _parse_stored_sources(coll.lib)

    remove_set = set(paths)
    remaining = [s for s in current if s not in remove_set]

    removed = [s for s in current if s in remove_set]
    if not removed:
        _emit(
            params.json_output,
            {
                "status": "success",
                "action": "tex_remove",
                "file": file,
                "dry_run": params.dry_run,
                "modified": False,
                "modified_entries": 0,
                "warnings": [],
                "removed": [],
            },
            ["No matching sources to remove."],
        )
        return

    if remaining:
        _set_stored_sources(coll, remaining)
    else:
        _clear_stored_sources(coll)

    human = [f"{_verb('unlink', params)} {len(removed)} source(s):"] + [f"  - {p}" for p in removed]
    _finish_mod(
        file,
        "tex_remove",
        coll,
        params,
        human,
        modified_entries=0,
        removed=removed,
        sources=remaining,
    )


def tex_clear(
    file: str | None = _FILE_OPTION,
    backup: bool = typer.Option(
        False, "--backup", help="Also write a <file>.bak copy before overwriting"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Unlink all TeX source files from this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    current = tex_sources_from_metadata(coll.lib, Path(file).parent)

    if not current:
        _emit(
            params.json_output,
            {
                "status": "success",
                "action": "tex_clear",
                "file": file,
                "dry_run": params.dry_run,
                "modified": False,
                "modified_entries": 0,
                "warnings": [],
                "cleared": False,
            },
            ["No sources to clear."],
        )
        return

    _clear_stored_sources(coll)
    human = [f"{_verb('clear', params, 'Cleared')} {len(current)} linked source(s)."]
    _finish_mod(
        file,
        "tex_clear",
        coll,
        params,
        human,
        modified_entries=0,
        cleared=True,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(tex_list))
    app.command("add")(_safe(tex_add))
    app.command("remove")(_safe(tex_remove))
    app.command("clear")(_safe(tex_clear))
