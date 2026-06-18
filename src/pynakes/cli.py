"""Command-line interface for pynakes."""

import json as _json
from pathlib import Path
from typing import Optional

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.diff import generate_diff
from pynakes.io import load_bib, save_bib, save_text
from pynakes.usage import (
    analyze_usage,
    collect_cited_keys,
    splice_into_text,
    subset_library,
    tag_with_group,
    tag_with_keyword,
)

app = typer.Typer(help="Agent-friendly BibTeX library management tool")


@app.command()
def inspect(file: str) -> None:
    """Inspect a .bib file structure."""
    typer.echo(f"inspect: {file}")


@app.command()
def groups() -> None:
    """Manage entry groups."""
    typer.echo("groups")


@app.command()
def keys() -> None:
    """Generate and check citation keys."""
    typer.echo("keys")


@app.command()
def fields() -> None:
    """Edit fields (rename, move, append, clear)."""
    typer.echo("fields")


@app.command()
def lint(file: str) -> None:
    """Validate entries."""
    typer.echo(f"lint: {file}")


@app.command()
def capabilities() -> None:
    """Show tool capabilities."""
    typer.echo("capabilities")


@app.command()
def used(
    bib_file: str = typer.Argument(..., help="Path to the .bib library"),
    sources: list[str] = typer.Argument(
        ..., help="One or more .tex/.aux files or directories to scan"
    ),
    out: Optional[str] = typer.Option(
        None, "--out", help="Write a subset .bib containing only the used entries"
    ),
    group: Optional[str] = typer.Option(
        None, "--group", help="Tag used entries into this JabRef group"
    ),
    keyword: Optional[str] = typer.Option(
        None, "--keyword", help="Tag used entries with this keyword"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without writing"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources; optionally tag or export them."""
    lib = load_bib(bib_file)
    cited, include_all, scanned = collect_cited_keys(sources)
    report = analyze_usage(lib, cited, include_all=include_all, sources=scanned)

    # Capture original text and per-entry raw blocks so in-place edits can be
    # spliced back for a minimal diff (preserving all untouched formatting).
    original_text = Path(bib_file).read_text(encoding=lib.encoding, errors="replace")
    used_entries = [e for e in lib.entries.values() if e.key in set(report.used)]
    pre_raw = {id(e): e.raw_content for e in used_entries}

    tagged = 0
    tag_field = None
    if group:
        tagged = tag_with_group(lib, report.used, group)
        tag_field = "groups"
    elif keyword:
        tagged = tag_with_keyword(lib, report.used, keyword)
        tag_field = "keywords"

    bib_diff = ""
    if tag_field:
        edits = [(pre_raw[id(e)], e.raw_content) for e in used_entries]
        new_text = splice_into_text(original_text, edits)
        if new_text is None:
            # Some entry block couldn't be located; fall back to re-serialization.
            new_text = write_bib(lib)
        bib_diff = generate_diff(original_text, new_text, Path(bib_file).name)
        if not dry_run:
            save_text(new_text, bib_file, encoding=lib.encoding)

    out_written = False
    if out:
        sub = subset_library(lib, report.used)
        if not dry_run:
            save_bib(sub, out, backup=False)
            out_written = True

    if json_output:
        result = {
            "status": "success",
            "action": "used",
            "input_path": bib_file,
            "dry_run": dry_run,
            "report": report.to_dict(),
            "tagged": {"field": tag_field, "value": group or keyword, "count": tagged}
            if tag_field
            else None,
            "exported": {"path": out, "written": out_written, "count": len(report.used)}
            if out
            else None,
            "would_modify_file": bool(tag_field) and dry_run,
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
        verb = "Would tag" if dry_run else "Tagged"
        typer.echo(f'{verb} {tagged} entr{"y" if tagged == 1 else "ies"} '
                   f'with {tag_field} = "{group or keyword}".')
    if out:
        verb = "Would write" if dry_run else "Wrote"
        typer.echo(f"{verb} {len(report.used)} entr"
                   f'{"y" if len(report.used) == 1 else "ies"} to {out}.')
    if diff and bib_diff:
        typer.echo("")
        typer.echo(bib_diff)


if __name__ == "__main__":
    app()
