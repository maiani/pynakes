"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from typing import Optional

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _emit_error,
    _entries,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection

# --- convert -----------------------------------------------------


def convert(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Required target format: biblatex or bibtex",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Convert a library between BibTeX and BibLaTeX conventions."""
    if to is None:
        _emit_error(
            json_output,
            "MissingConvertTarget",
            "--to biblatex or --to bibtex is required; pynakes does not infer it from databaseType",
        )
    coll = Collection.open(file)
    report = coll.convert(to)  # raises ValueError on an unknown target

    verb = "Would convert" if dry_run else "Converted"
    human = [
        f"{verb} {report.entries} {_entries(report.entries)} to {report.target}.",
        "  "
        f"fields_renamed={report.fields_renamed}, "
        f"types_changed={report.types_changed}, dates_changed={report.dates_changed}",
    ]
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "convert",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=report.warnings,
        operations=report.operations,
        backup=backup,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(convert))
