"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import normalize as normalize_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.normalize import skipped_step_flag
from pynakes.usage import MissingTexSourcesError

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
    file: str | None = bib_file_argument(),
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
    drop_field: list[str] | None = typer.Option(
        None,
        "--drop-field",
        help="Field to remove from every entry (e.g. abstract); can be repeated. "
        "Off by default; combines with any normalize-drop-fields metadata key",
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
    journal_source: str = typer.Option(
        "metadata",
        "--journal-source",
        help="metadata, jabref, or none (base exact-mapping table before "
        "--journal-table; default: jabref)",
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
    page_normalization: str = typer.Option(
        "metadata",
        "--pages",
        help="Rewrite page ranges to start--end (metadata, on, or off)",
    ),
    key_normalization: str = typer.Option(
        "metadata",
        "--keys",
        help="Regenerate citation keys from pattern (metadata, on, or off)",
    ),
    identifier_case: str = typer.Option(
        "metadata",
        "--identifier-case",
        help="Lowercase entry types and field names (metadata, on, or off)",
    ),
    metadata_formatting: str = typer.Option(
        "metadata",
        "--metadata-formatting",
        help="Consolidate metadata layout: pynakes-meta top, jabref-meta bottom (metadata, on, or off)",
    ),
    sort_by: list[str] | None = typer.Option(
        None,
        "--sort-by",
        help="Sort entries by a BibTeX field name; repeat for secondary keys "
        '(e.g. --sort-by author --sort-by year:desc). Use "citationkey" (or "key") '
        'for the citation key and append ":desc" for descending. "original" keeps '
        "the current order. Omit to follow the file's configured sort order.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate keys despite missing linked TeX sources; those sources are not rewritten",
    ),
) -> None:
    """Normalize entries: titles, authors, journals, DOIs, identifier case, and ordering.

    Each step follows the library's configured settings (its normalization
    metadata) unless overridden by a flag.
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)

    if file == "-":
        _emit_error(
            json_output,
            "InvalidInput",
            "normalize requires a file; stdin is supported by format --stdout",
        )

    file = _resolve_input_bib(file, json_output)

    try:
        options = _build_normalize_options(
            title_protection,
            title_field,
            term,
            drop_field,
            author_style,
            journal_style,
            journal_source,
            journal_table,
            ltwa_table,
            doi_normalization,
            page_normalization,
            key_normalization,
            identifier_case,
            metadata_formatting,
            sort_by,
        )
        coll = Bibliography.open(file)
        report = coll.normalize(options, force_key_renames=force)
    except MissingTexSourcesError as exc:
        _emit_error(
            json_output,
            "MissingTexSource",
            str(exc),
            sources=exc.sources,
            hint="Restore/remove the declared sources, or rerun with --force.",
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidNormalizeOption", str(exc))

    if report.sort_criteria:
        order = ", ".join(
            f"{field}{':desc' if descending else ''}" for field, descending in report.sort_criteria
        )
        sort_detail = f", sorted_by=[{order}]"
    else:
        sort_detail = ""
    # A step that never ran reports ``off`` rather than ``0``: the two are not
    # the same claim, and the steps that are off by default (journal style, key
    # regeneration) are precisely the ones a reader would otherwise take as
    # "checked, nothing to do".
    counts = [
        ("titles", sum(report.title_fields.values()), "titles"),
        ("authors", report.authors, "authors"),
        ("journals", report.journals, "journals"),
        ("dois", report.dois, "dois"),
        ("pages", report.pages, "pages"),
        ("months", report.months, None),
        ("entry_types", report.entry_types, "identifier_case"),
        ("field_names", report.field_names, "identifier_case"),
        ("keys", report.keys, "keys"),
    ]
    summary = ", ".join(
        f"{label}={'off' if step in report.skipped else count}" for label, count, step in counts
    )
    human = [
        f"{_verb('normalize', params)} entries.",
        f"  {summary}{sort_detail}",
    ]
    if report.skipped:
        off = ", ".join(f"{step} ({skipped_step_flag(step)})" for step in report.skipped)
        human.append(f'  not run: {off}. Those read "off" above, not zero.')
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "normalize",
        coll,
        params,
        human,
        warnings=report.warnings,
        operations=report.operations,
    )


def _build_normalize_options(
    title_protection: str,
    title_field: list[str] | None,
    term: list[str] | None,
    drop_field: list[str] | None,
    author_style: str,
    journal_style: str,
    journal_source: str,
    journal_table: str | None,
    ltwa_table: str | None,
    doi_normalization: str,
    page_normalization: str,
    key_normalization: str,
    identifier_case: str,
    metadata_formatting: str,
    sort_by: list[str] | None,
) -> normalize_ops.NormalizeOptions:
    """Build NormalizeOptions from CLI arguments."""
    return normalize_ops.NormalizeOptions(
        protect_titles=_optional_bool(title_protection),
        title_fields=title_field,
        protected_terms=term,
        drop_fields=drop_field,
        author_style=author_style,
        journal_style=journal_style,
        journal_source=journal_source,
        journal_table=journal_table,
        ltwa_table=ltwa_table,
        normalize_dois=_optional_bool(doi_normalization),
        normalize_pages=_optional_bool(page_normalization),
        normalize_keys=_optional_bool(key_normalization),
        identifier_case=_optional_bool(identifier_case),
        format_metadata=_optional_bool(metadata_formatting),
        sort_by=sort_by,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(normalize))
