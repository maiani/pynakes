"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import normalize as normalize_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography

# --- normalize -------------------------------------------------------------


def _optional_bool(value: str) -> bool | None:
    normalized = value.lower()
    if normalized == "metadata":
        return None
    if normalized in {"on", "true", "yes", "1"}:
        return True
    if normalized in {"off", "false", "no", "0"}:
        return False
    raise ValueError("expected metadata, on, or off")


def normalize(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    title_protection: str = typer.Option(
        "metadata",
        "--title-protection",
        help="metadata, on, or off",
    ),
    title_field: list[str] | None = typer.Option(
        None,
        "--title-field",
        help="Title-like field to brace-protect; can be repeated",
    ),
    term: list[str] | None = typer.Option(
        None,
        "--term",
        help="Additional exact title term to brace-protect; can be repeated",
    ),
    author_style: str = typer.Option(
        "metadata",
        "--author-style",
        help="metadata, jabref, conservative, bibtex, biblatex, or none",
    ),
    journal_style: str = typer.Option(
        "metadata",
        "--journal-style",
        help="metadata, abbreviated, full, or none (default: no change unless metadata sets it)",
    ),
    journal_table: str | None = typer.Option(
        None,
        "--journal-table",
        help="CSV/TSV with title, abbreviation, and optional ISSN mappings",
    ),
    ltwa_table: str | None = typer.Option(
        None,
        "--ltwa-table",
        help="CSV/TSV LTWA word abbreviation table",
    ),
    doi_normalization: str = typer.Option(
        "metadata",
        "--doi-normalization",
        help="metadata, on, or off",
    ),
    identifier_case: str = typer.Option(
        "metadata",
        "--identifier-case",
        help="Lowercase entry types and field names (metadata, on, or off)",
    ),
    metadata_formatting: str = typer.Option(
        "metadata",
        "--metadata-formatting",
        help="Consolidate jabref-meta to the file end, sorted (metadata, on, or off)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Run the standard bibliography normalization routine."""
    file = _resolve_input_bib(file, json_output)
    try:
        options = normalize_ops.NormalizeOptions(
            protect_titles=_optional_bool(title_protection),
            title_fields=title_field,
            protected_terms=term,
            author_style=author_style,
            journal_style=journal_style,
            journal_table=journal_table,
            ltwa_table=ltwa_table,
            normalize_dois=_optional_bool(doi_normalization),
            identifier_case=_optional_bool(identifier_case),
            format_metadata=_optional_bool(metadata_formatting),
        )
        coll = Bibliography.open(file)
        report = coll.normalize(options)
    except ValueError as exc:
        _emit_error(json_output, "InvalidNormalizeOption", str(exc))

    human = [
        f"{_verb('normalize', dry_run)} entries.",
        "  "
        f"titles={sum(report.title_fields.values())}, "
        f"authors={report.authors}, journals={report.journals}, dois={report.dois}, "
        f"months={report.months}, "
        f"entry_types={report.entry_types}, field_names={report.field_names}",
    ]
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "normalize",
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
    app.command()(_safe(normalize))
