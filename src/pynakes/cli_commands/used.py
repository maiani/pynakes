"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from pathlib import Path

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _emit,
    _emit_error,
    _entries,
    _preview_or_commit,
    _resolve_input_bib,
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
    bib_file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
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
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources; optionally tag or export them."""
    bib_file = _resolve_input_bib(bib_file, json_output)
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
        bib_diff, file_modified, tagged_entries = _preview_or_commit(coll, dry_run, backup=backup)

    out_written = False
    if out:
        sub = subset_library(coll.lib, report.used)
        if not dry_run:
            save_bib(sub, out, backup=False)
            out_written = True

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
    human = [
        f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).",
    ]
    if report.include_all:
        human.append(r"\nocite{*} found — all entries counted as used.")
    human.append(f"Used:    {len(report.used)}")
    human.append(f"Unused:  {len(report.unused)}")
    human.append(f"Missing: {len(report.missing)}")
    if report.missing:
        for key in report.missing:
            human.append(f"  - {key}  (cited but not in library)")
    if tag_field:
        human.append(
            f"{_verb('tag', dry_run, 'Tagged')} {tagged} {_entries(tagged)}"
            f' with {tag_field} = "{group or keyword}".'
        )
    if out:
        human.append(
            f"{_verb('write', dry_run, 'Wrote')} {len(report.used)} {_entries(len(report.used))} to {out}."
        )
    _emit(json_output, result, human, bib_diff, diff)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(used))
