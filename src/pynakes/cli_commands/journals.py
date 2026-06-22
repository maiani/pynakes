"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json
from typing import Optional

import typer

from pynakes import journals as journals_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _entries,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection
from pynakes.io import load_bib

# --- journals ----------------------------------------------------


def _run_journal_op(
    file: str,
    style: str,
    journal_table: Optional[str],
    ltwa_table: Optional[str],
    dry_run: bool,
    diff: bool,
    json_output: bool,
    backup: bool = False,
) -> None:
    """Shared body for ``journals abbreviate`` / ``journals expand``."""
    verb_root = "abbreviate" if style == "abbreviated" else "expand"
    coll = Collection.open(file)
    if style == "abbreviated":
        report = coll.abbreviate_journals(journal_table, ltwa_table)
    else:
        report = coll.expand_journals(journal_table, ltwa_table)

    verb = f"Would {verb_root}" if dry_run else f"{verb_root.capitalize()[:-1]}ed"
    human = [f"{verb} {report.changed} journal {_entries(report.changed)}."]
    if report.unknown:
        human.append(f"  {len(report.unknown)} unknown journal name(s).")

    _finish_mod(
        file,
        f"journals_{verb_root}",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=journals_ops.unknown_journal_warnings(report.unknown),
        resolved=report.resolved,
        unknown=report.unknown,
        backup=backup,
    )


def journals_abbreviate(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Abbreviate journal titles (journal/journaltitle)."""
    _run_journal_op(
        file, "abbreviated", journal_table, ltwa_table, dry_run, diff, json_output, backup
    )


def journals_expand(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Expand abbreviated journal titles back to their full form."""
    _run_journal_op(file, "full", journal_table, ltwa_table, dry_run, diff, json_output, backup)


def journals_check(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which journal titles can be resolved (read-only; modifies nothing)."""
    lib = load_bib(file)
    sources = journals_ops.load_sources(journal_table, ltwa_table)

    seen: dict[str, str] = {}
    for entry in lib.entries.values():
        for jfield in journals_ops.JOURNAL_FIELDS:
            title = entry.fields.get(jfield)
            if not title or title in seen:
                continue
            seen[title] = journals_ops.classify_journal(title, entry, sources)

    journals = [{"journal": title, "status": status} for title, status in seen.items()]
    unknown = [j["journal"] for j in journals if j["status"] == "unknown"]

    if json_output:
        result = {
            "status": "success",
            "action": "journals_check",
            "file": file,
            "journals": journals,
            "unknown": unknown,
            "known": len(journals) - len(unknown),
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    typer.echo(f"{file}: {len(journals)} distinct journal {_entries(len(journals))}")
    for item in journals:
        typer.echo(f"  [{item['status']:>7}] {item['journal']}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("abbreviate")(_safe(journals_abbreviate))
    app.command("expand")(_safe(journals_expand))
    app.command("check")(_safe(journals_check))
