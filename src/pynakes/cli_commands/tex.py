"""CLI command registration for ``pynakes tex`` (linked LaTeX sources).

Manage the list of LaTeX source files that cite the library, stored as the
``tex-sources`` metadata key. Commands ``list``, ``add``, ``remove``, and
``clear`` let users inspect and edit the source list without reaching for the
generic ``metadata set`` command.
"""

from pathlib import Path

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_json,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
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


def tex_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List the TeX source files linked to this library."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    sources = tex_sources_from_metadata(coll.lib, Path(file).parent)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "tex_list",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "sources": sources,
            }
        )
        return

    if not sources:
        typer.echo(f"{file}: no TeX sources linked.")
        return
    typer.echo(f"{file}:")
    for s in sources:
        typer.echo(f"  {s}")


def tex_add(
    file: str | None = bib_file_argument(),
    paths: list[str] = typer.Argument(..., help="One or more .tex files or directories to link"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Link one or more TeX source files or directories to this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    current = _parse_stored_sources(coll.lib)

    added: list[str] = []
    for p in paths:
        if p not in current:
            current.append(p)
            added.append(p)

    if not added:
        _finish_mod(
            file, "tex_add", coll, params, ["No new sources to add."], modified_entries=0, added=[]
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
    file: str | None = bib_file_argument(),
    paths: list[str] = typer.Argument(
        ..., help="One or more TeX source files or directories to unlink"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Unlink one or more TeX source files or directories from this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    current = _parse_stored_sources(coll.lib)

    remove_set = set(paths)
    remaining = [s for s in current if s not in remove_set]

    removed = [s for s in current if s in remove_set]
    if not removed:
        _finish_mod(
            file,
            "tex_remove",
            coll,
            params,
            ["No matching sources to remove."],
            modified_entries=0,
            removed=[],
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
    file: str | None = bib_file_argument(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Unlink all TeX source files from this library."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    current = tex_sources_from_metadata(coll.lib, Path(file).parent)

    if not current:
        _finish_mod(
            file,
            "tex_clear",
            coll,
            params,
            ["No sources to clear."],
            modified_entries=0,
            cleared=False,
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
