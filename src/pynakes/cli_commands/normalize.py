"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import normalize as normalize_ops
from pynakes._normalize_steps import NOT_IN_ONLY, STEPS, WHOLE_FILE, WHOLE_FILE_STEPS, step_name
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
    key_option,
    parse_key_selector,
    select_keys,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.normalize import SKIPPABLE_STEPS, skipped_step_flag
from pynakes.usage import MissingTexSourcesError

# --- normalize -------------------------------------------------------------

_ONLY_HELP = "Run only these steps, comma-separated and repeatable: " + ", ".join(
    name.replace("_", "-") for name in STEPS
)


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
    only: list[str] | None = typer.Option(
        None,
        "--only",
        help=_ONLY_HELP,
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
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
    metadata) unless overridden by a flag. `--only` runs just the named steps,
    and `--key` / `--where` just the selected entries; a selection leaves the
    whole file alone, so it neither re-sorts entries nor rearranges metadata.
    `normalize --key Newton1687,Euler1748 --only journals` abbreviates two
    journal names and changes nothing else.
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
    steps = _only_steps(only, json_output)
    _refuse_contradictions(
        json_output,
        steps,
        selecting=where is not None or bool(key),
        explicit={
            "--title-protection": title_protection != "metadata",
            "--title-field": bool(title_field),
            "--term": bool(term),
            "--drop-field": bool(drop_field),
            "--author-style": author_style != "metadata",
            "--journal-style": journal_style != "metadata",
            "--journal-source": journal_source != "metadata",
            "--journal-table": journal_table is not None,
            "--ltwa-table": ltwa_table is not None,
            "--doi-normalization": doi_normalization != "metadata",
            "--pages": page_normalization != "metadata",
            "--key-generation": key_normalization != "metadata",
            "--identifier-case": identifier_case != "metadata",
            "--metadata-formatting": metadata_formatting != "metadata",
            "--sort-by": bool(sort_by),
        },
    )

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
        options.only = steps
        coll = Bibliography.open(file)
        selected = select_keys(coll, where, key, json_output, "normalize")
        report = coll.normalize(options, force_key_renames=ignore_missing_tex, keys=selected)
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
        ("title_markup", report.title_markup, "title_markup"),
        ("authors", report.authors, "authors"),
        ("journals", report.journals, "journals"),
        ("dois", report.dois, "dois"),
        ("pages", report.pages, "pages"),
        ("months", report.months, "months"),
        ("entry_types", report.entry_types, "identifier_case"),
        ("field_names", report.field_names, "identifier_case"),
        ("keys", report.keys, "keys"),
    ]
    # Markup conversion belongs to the titles step but runs whether or not
    # title protection is on, so it reads "off" only when the step never ran.
    skipped = dict(report.skipped)
    if skipped.get("titles") in (NOT_IN_ONLY, WHOLE_FILE):
        skipped["title_markup"] = skipped["titles"]
    summary = ", ".join(
        f"{label}={'off' if step in skipped else count}" for label, count, step in counts
    )
    human = [
        f"{_verb('normalize', params)} entries.",
        f"  {summary}{sort_detail}",
    ]
    # Steps left out on request are not the same as steps the library has
    # turned off: only the latter come with the flag that turns them on.
    asked = [step for step, why in report.skipped.items() if why in (NOT_IN_ONLY, WHOLE_FILE)]
    off = [step for step in report.skipped if step not in asked and step in SKIPPABLE_STEPS]
    if off:
        listed = ", ".join(f"{step} ({skipped_step_flag(step)})" for step in off)
        human.append(f'  not run: {listed}. Those read "off" above, not zero.')
    if asked:
        names = ", ".join(step.replace("_", "-") for step in asked)
        human.append(f"  left out as asked: {names}.")
    warnings = list(report.warnings)
    if selected == []:
        warnings.append(
            {"type": "no_entries_selected", "message": "No entry matched the selection"}
        )

    _finish_mod(
        file,
        "normalize",
        coll,
        params,
        human,
        warnings=warnings,
        operations=report.operations,
        where=where,
        keys=parse_key_selector(key),
        selected=None if selected is None else len(selected),
    )


#: The step each step-configuring flag belongs to.
_FLAG_STEPS = {
    "--title-protection": "titles",
    "--title-field": "titles",
    "--term": "titles",
    "--drop-field": "drop_fields",
    "--author-style": "authors",
    "--journal-style": "journals",
    "--journal-source": "journals",
    "--journal-table": "journals",
    "--ltwa-table": "journals",
    "--doi-normalization": "dois",
    "--pages": "pages",
    "--key-generation": "keys",
    "--identifier-case": "identifier_case",
    "--metadata-formatting": "metadata",
    "--sort-by": "sort",
}


def _only_steps(only: list[str] | None, json_output: bool) -> list[str] | None:
    """Parse ``--only`` into step names, or ``None`` when it was not given."""
    if only is None:
        return None
    names = [part for value in only for raw in value.split(",") if (part := raw.strip())]
    if not names:
        _emit_error(json_output, "InvalidInput", "--only needs at least one step")
    try:
        return list(dict.fromkeys(step_name(name) for name in names))
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))


def _refuse_contradictions(
    json_output: bool, steps: list[str] | None, *, selecting: bool, explicit: dict[str, bool]
) -> None:
    """Refuse a flag for a step that cannot run, rather than quietly ignoring it.

    A flag configures one step. When ``--only`` leaves that step out, or a
    selection rules out a whole-file step, the flag would do nothing, which is
    never what whoever typed it meant.
    """
    given = [flag for flag, set_ in explicit.items() if set_]
    if steps is not None:
        excluded = [flag for flag in given if _FLAG_STEPS[flag] not in steps]
        if excluded:
            _emit_error(
                json_output,
                "InvalidInput",
                f"{', '.join(excluded)} "
                f"{'configures a step' if len(excluded) == 1 else 'configure steps'} "
                f"that --only leaves out; add the step to --only or drop the flag",
            )
    if selecting:
        whole = [flag for flag in given if _FLAG_STEPS[flag] in WHOLE_FILE_STEPS]
        if whole:
            _emit_error(
                json_output,
                "InvalidInput",
                f"--key/--where select entries, so they cannot be combined with the "
                f"whole-file option(s) {', '.join(whole)}",
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
