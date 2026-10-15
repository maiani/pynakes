"""`tex scan`: report which entries the TeX sources cite.

Its write options (`--out`, `--group`, `--keyword`) are deprecated: the
`used` predicate now works in every `--where`, so exporting or tagging the
cited entries is the job of the commands that export and tag.
"""

from pathlib import Path

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    _FORCE_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit,
    _emit_error,
    _entries,
    _preview_or_commit,
    _refuse_existing_output,
    _refuse_input_as_output,
    _require_written,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
    deprecation_warning,
)
from pynakes.engine import Bibliography
from pynakes.io import save_text
from pynakes.usage import (
    analyze_usage,
    collect_citation_occurrences,
    resolve_existing_tex_sources,
    subset_library,
    tag_with_group,
    tag_with_keyword,
    tex_sources_from_metadata,
)

# --- tex scan --------------------------------------------------------------


def scan(
    file: str | None = bib_file_argument(),
    sources: list[str] | None = typer.Argument(
        None,
        help="One or more .tex/.aux files or directories to scan "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Deprecated (removed in 0.9.0): use corpus combine FILE --where used --out OUT",
    ),
    force: bool = _FORCE_OPTION,
    group: str | None = typer.Option(
        None,
        "--group",
        help="Deprecated (removed in 0.9.0): use fields append FILE groups NAME --where used",
    ),
    keyword: str | None = typer.Option(
        None,
        "--keyword",
        help="Deprecated (removed in 0.9.0): use fields append FILE keywords WORD --where used",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources, and which citations are missing.

    The report reads the given sources, else the library's linked
    `tex-sources`. To act on the cited entries, select them with
    `--where used` wherever entries are selected: `corpus combine FILE
    --where used --out cited.bib` exports them, and `fields append FILE
    keywords cited --where used` tags them. `--out`, `--group`, and
    `--keyword` still do this here until 0.9.0, with a `deprecated` warning.
    """
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    if group and keyword:
        _emit_error(json_output, "InvalidInput", "Tag with --group or --keyword, not both")
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
    source_sha256 = _source_sha256(coll)
    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(file).parent)
    )
    warnings: list[dict] = []
    if out:
        warnings.append(
            deprecation_warning(
                "tex scan --out",
                "corpus combine FILE --where used --out OUT",
                removal="0.9.0",
                json_output=json_output,
            )
        )
    for flag, value, tag_name in (("--group", group, "groups"), ("--keyword", keyword, "keywords")):
        if value:
            warnings.append(
                deprecation_warning(
                    f"tex scan {flag}",
                    f"fields append FILE {tag_name} VALUE --where used",
                    removal="0.9.0",
                    json_output=json_output,
                )
            )
    if not sources:
        resolved_sources, missing = resolve_existing_tex_sources(resolved_sources)
        warnings.extend(missing)
    if not resolved_sources:
        _emit_error(
            json_output,
            "NoSources",
            "No sources given and no 'tex-sources' metadata to fall back to",
        )
        return
    occurrences, include_all, scanned = collect_citation_occurrences(resolved_sources)
    if out:
        _refuse_input_as_output(json_output, out, [file, *scanned])
        _refuse_existing_output(json_output, out, force)
    report = analyze_usage(
        coll.lib,
        set(occurrences),
        include_all=include_all,
        sources=scanned,
        usages=occurrences,
    )

    tagged = 0
    tag_field = None
    if group:
        tagged = tag_with_group(coll.lib, report.used, group)
        tag_field = "groups"
    elif keyword:
        tagged = tag_with_keyword(coll.lib, report.used, keyword)
        tag_field = "keywords"

    bib_diff = ""
    file_modified = False
    tagged_entries = 0
    plan = coll.change_plan()
    if tag_field:
        if not params.dry_run:
            coll.mark_dirty(tagged)
        bib_diff, file_modified, tagged_entries = _preview_or_commit(coll, params)

    out_written = False
    if out:
        sub = subset_library(coll.lib, report.used)
        content = write_bib(sub)
        if not params.dry_run:
            save_result = save_text(content, out, backup=False)
            _require_written(params.json_output, save_result, out, modified=file_modified)
            out_written = True

    human = [
        f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).",
    ]
    # Deprecation notices already went to stderr; the rest belong in the report.
    for w in warnings:
        if w.get("type") != "deprecated":
            human.append(f"  {w['message']}")
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
            f"{_verb('tag', params, 'Tagged')} {tagged} {_entries(tagged)}"
            f' with {tag_field} = "{group or keyword}".'
        )
    if out:
        human.append(
            f"{_verb('write', params, 'Wrote')} {len(report.used)}"
            f" {_entries(len(report.used))} to {out}."
        )

    result = {
        "status": "success",
        "action": "tex_scan",
        "file": file,
        "dry_run": params.dry_run,
        "modified": file_modified,
        "modified_entries": tagged_entries,
        "warnings": warnings,
        "plan": plan,
        "source_sha256": source_sha256,
        "out": out,
        "written": out_written,
        "report": report.to_dict(),
        "tagged": {"field": tag_field, "value": group or keyword, "count": tagged}
        if tag_field
        else None,
        "exported": len(report.used) if out else None,
    }
    _emit(params.json_output, result, human, bib_diff, params.diff)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("scan")(_safe(scan))
