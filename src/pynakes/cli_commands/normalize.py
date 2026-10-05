"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import normalize as normalize_ops
from pynakes.cli_choices import AuthorStyle, JournalSource, JournalStyle, Switch
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
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
    """Map a ``metadata``/``on``/``off`` switch to defer, true, or false."""
    normalized = value.lower()
    if normalized == "metadata":
        return None
    return normalized == "on"


def normalize(
    file: str | None = bib_file_argument(),
    title_protection: Switch = typer.Option(
        Switch.METADATA,
        "--title-protection",
        case_sensitive=False,
        help="Brace-protect capitalization-sensitive title words",
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
    author_style: AuthorStyle = typer.Option(
        AuthorStyle.METADATA,
        "--author-style",
        case_sensitive=False,
        help="Author-list style",
    ),
    journal_style: JournalStyle = typer.Option(
        JournalStyle.METADATA,
        "--journal-style",
        case_sensitive=False,
        help="Journal-name style (default: no change unless metadata sets it)",
    ),
    journal_source: JournalSource = typer.Option(
        JournalSource.METADATA,
        "--journal-source",
        case_sensitive=False,
        help="Base exact-mapping journal table, applied before --journal-table (default: jabref)",
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
    doi_normalization: Switch = typer.Option(
        Switch.METADATA,
        "--doi-normalization",
        case_sensitive=False,
        help="Strip DOI URL prefixes and labels down to the bare DOI",
    ),
    page_normalization: Switch = typer.Option(
        Switch.METADATA,
        "--pages",
        case_sensitive=False,
        help="Rewrite page ranges to start--end",
    ),
    key_normalization: Switch = typer.Option(
        Switch.METADATA,
        "--key-generation",
        case_sensitive=False,
        help="Regenerate citation keys from the library's key pattern",
    ),
    identifier_case: Switch = typer.Option(
        Switch.METADATA,
        "--identifier-case",
        case_sensitive=False,
        help="Lowercase entry types and field names",
    ),
    metadata_formatting: Switch = typer.Option(
        Switch.METADATA,
        "--metadata-formatting",
        case_sensitive=False,
        help="Consolidate metadata layout: pynakes-meta top, jabref-meta bottom",
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
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    ignore_missing_tex: bool = typer.Option(
        False,
        "--ignore-missing-tex",
        help="Regenerate keys despite missing linked TeX sources; those sources are not rewritten",
    ),
) -> None:
    """Normalize entries: titles, authors, journals, DOIs, identifier case, and ordering.

    Each step follows the library's configured settings (its normalization
    metadata) unless overridden by a flag.
    """
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )

    if file == "-":
        _emit_error(
            json_output,
            "InvalidInput",
            "normalize requires a file; stdin is supported by format - --out -",
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
        report = coll.normalize(options, force_key_renames=ignore_missing_tex)
    except MissingTexSourcesError as exc:
        _emit_error(
            json_output,
            "MissingTexSource",
            str(exc),
            sources=exc.sources,
            hint="Restore/remove the declared sources, or rerun with --ignore-missing-tex.",
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
