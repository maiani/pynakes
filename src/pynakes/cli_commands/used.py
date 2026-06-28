"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json
from pathlib import Path

import typer

from pynakes.cli_common import (
    _emit_error,
    _entries,
    _preview_or_commit,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography
from pynakes.io import save_bib
from pynakes.usage import (
    analyze_usage,
    collect_cited_keys,
    subset_library,
    tag_with_group,
    tag_with_keyword,
    tex_sources_from_metadata,
)

# --- used ------------------------------------------------------------------


def used(
    bib_file: str = typer.Argument(..., help="Path to the .bib library"),
    sources: list[str] | None = typer.Argument(
        None,
        help="One or more .tex/.aux files or directories to scan "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    out: str | None = typer.Option(
        None, "--out", help="Write a subset .bib containing only the used entries"
    ),
    group: str | None = typer.Option(None, "--group", help="Tag used entries into this group"),
    keyword: str | None = typer.Option(
        None, "--keyword", help="Tag used entries with this keyword"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources; optionally tag or export them."""
    coll = Bibliography.open(bib_file)
    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(bib_file).parent)
    )
    if not resolved_sources:
        _emit_error(
            json_output,
            "NoSources",
            "No sources given and no 'tex-sources' metadata to fall back to",
        )
        return
    cited, include_all, scanned = collect_cited_keys(resolved_sources)
    report = analyze_usage(coll.lib, cited, include_all=include_all, sources=scanned)

    tagged = 0
    tag_field = None
    if group:
        tagged = tag_with_group(coll.lib, report.used, group)
        tag_field = "groups"
    elif keyword:
        tagged = tag_with_keyword(coll.lib, report.used, keyword)
        tag_field = "keywords"

    bib_diff = ""
    tagged_entries = 0
    file_modified = False
    if tag_field:
        if not dry_run:
            coll.mark_dirty(tagged)
        bib_diff, file_modified, tagged_entries = _preview_or_commit(coll, dry_run)

    out_written = False
    if out:
        sub = subset_library(coll.lib, report.used)
        if not dry_run:
            save_bib(sub, out, backup=False)
            out_written = True

    if json_output:
        result = {
            "status": "success",
            "action": "used",
            "file": bib_file,
            "dry_run": dry_run,
            "modified": file_modified,
            "modified_entries": tagged_entries,
            "warnings": [],
            "report": report.to_dict(),
            "tagged": {"field": tag_field, "value": group or keyword, "count": tagged}
            if tag_field
            else None,
            "exported": {"path": out, "written": out_written, "count": len(report.used)}
            if out
            else None,
        }
        if diff and bib_diff:
            result["diff"] = bib_diff
        typer.echo(_json.dumps(result, indent=2))
        return

    # Human-readable output
    typer.echo(f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).")
    if report.include_all:
        typer.echo(r"\nocite{*} found — all entries counted as used.")
    typer.echo(f"Used:    {len(report.used)}")
    typer.echo(f"Unused:  {len(report.unused)}")
    typer.echo(f"Missing: {len(report.missing)}")
    if report.missing:
        for key in report.missing:
            typer.echo(f"  - {key}  (cited but not in library)")

    if tag_field:
        typer.echo(
            f"{_verb('tag', dry_run, 'Tagged')} {tagged} {_entries(tagged)}"
            f' with {tag_field} = "{group or keyword}".'
        )
    if out:
        typer.echo(
            f"{_verb('write', dry_run, 'Wrote')} {len(report.used)} {_entries(len(report.used))} to {out}."
        )
    if diff and bib_diff:
        typer.echo("")
        typer.echo(bib_diff)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(used))
