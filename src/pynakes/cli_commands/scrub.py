"""CLI command for ``scrub``: write a public copy without private content.

The input is read-only and the result is a new file, so this uses the
file-creation envelope (``_finish_create``) rather than the in-place modifying
one. ``--check`` reports instead of writing and gates on the finding, which is
what a submission or pre-commit check needs.
"""

import typer

from pynakes import scrub as scrub_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _FORCE_OPTION,
    RunParams,
    _emit,
    _emit_error,
    _entries,
    _finish_create,
    _refuse_existing_output,
    _resolve_input_bib,
    _safe,
    _same_file,
    _source_sha256,
    _verb,
    bib_file_argument,
    bind_where_filter,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.engine import Bibliography

# --- scrub -----------------------------------------------------------------


def _summary_lines(report: scrub_ops.ScrubReport) -> list[str]:
    """Render the per-kind breakdown shared by the write and check outputs."""
    lines: list[str] = []
    if report.fields:
        named = ", ".join(f"{name} ({count})" for name, count in report.fields.items())
        lines.append(f"  fields:   {named} — {report.entries} {_entries(report.entries)} touched")
    elif not report.patterns:
        lines.append("  fields:   off")
    if report.metadata_blocks:
        keys = ", ".join(report.metadata_keys)
        lines.append(f"  metadata: {report.metadata_blocks} block(s) — {keys}")
    if report.comments:
        lines.append(f"  comments: {report.comments} block(s)")
    return lines


def scrub(
    file: str | None = bib_file_argument(),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Path to write the scrubbed copy (required unless --check). Give the "
        "input path to scrub it in place",
    ),
    force: bool = _FORCE_OPTION,
    drop_field: list[str] | None = typer.Option(
        None,
        "--drop-field",
        help="Additional field to remove, beyond the default private set: "
        "comma-separated, repeatable, '*' glob allowed (e.g. --drop-field abstract)",
    ),
    keep_field: list[str] | None = typer.Option(
        None,
        "--keep-field",
        help="Field to keep despite the default private set: comma-separated, "
        "repeatable, '*' glob allowed; --keep-field '*' keeps every entry field "
        "and scrubs only blocks and comments",
    ),
    keep_comments: bool = typer.Option(
        False, "--keep-comments", help="Keep free @comment blocks and % comment lines"
    ),
    keep_metadata: bool = typer.Option(
        False, "--keep-metadata", help="Keep jabref-meta and pynakes-meta blocks"
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Write nothing; exit 1 if any private content is found",
    ),
    where: str | None = where_option(
        "Keep only the entries this selector matches (the shared --where grammar): "
        "--where used releases just the entries the linked TeX sources cite"
    ),
    key: list[str] | None = key_option(
        "Keep only these citation keys: comma-separated, repeatable. Narrows --where"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of what was removed"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Write a copy of a library with its private content removed.

    Strips the private entry fields (bookkeeping, reading state, personal
    annotation, local file paths, group membership), every jabref-meta and
    pynakes-meta block, and free comments — the content a working library
    carries that does not belong in a `.bib` shipped with a preprint,
    submission bundle, or public repository. What counts as private is the
    library's call: every kind has a `--keep-*` switch, `--drop-field` and
    `--keep-field` adjust the field set, and a library can record its own
    policy in `scrub-fields`, `scrub-keep-fields`, `scrub-comments`, and
    `scrub-metadata` metadata.

    Everything not removed stays byte-for-byte identical, so `--diff` shows
    exactly what left the library. `--where` / `--key` keep only the
    selected entries, chosen before anything is scrubbed: `scrub refs.bib
    --where used --out public.bib` releases just the entries the linked TeX
    sources cite.
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)

    if file == "-":
        _emit_error(json_output, "InvalidInput", "scrub requires a file; stdin is not supported")
    if check and out:
        _emit_error(json_output, "InvalidInput", "--check writes nothing, so it excludes --out")
    if not check and not out:
        _emit_error(
            json_output,
            "InvalidInput",
            "scrub requires --out PATH (give the input path to scrub it in place), "
            "or --check to report without writing",
        )

    resolved = _resolve_input_bib(file, json_output)
    if out is not None and not _same_file(out, resolved):
        _refuse_existing_output(json_output, out, force)
    keep = [name for value in keep_field or () for name in value.split(",")]
    options = scrub_ops.ScrubOptions(
        extra_fields=tuple(drop_field or ()),
        keep_fields=tuple(keep_field or ()),
        # Keeping every field is turning field scrubbing off, and reported so.
        fields=False if "*" in (name.strip() for name in keep) else None,
        comments=False if keep_comments else None,
        metadata=False if keep_metadata else None,
    )

    coll = Bibliography.open(resolved)
    source_text = coll.preview()
    selection_warnings: list[dict] = []
    # Select before scrubbing: the selector may read metadata scrubbing removes
    # (used/unused read tex-sources; query "name" reads saved queries).
    selector = bind_where_filter(coll, where, keys=key, warnings=selection_warnings)
    dropped = 0
    if selector is not None:
        dropped = coll.remove_entries(
            [entry for entry in coll.lib.entries.values() if not selector(entry)]
        )
    report = coll.scrub(options)
    report.warnings[:0] = selection_warnings

    if check:
        _check_result(resolved, coll, report, params)
        return

    content = coll.preview()
    human = [
        f"{_verb('scrub', params, 'Scrubbed')} {resolved} → {out}.",
        *_summary_lines(report),
    ]
    if selector is not None:
        human.append(
            f"  kept {len(coll.lib.entries)} selected {_entries(len(coll.lib.entries))}; "
            f"left out {dropped}."
        )
    elif report.clean:
        human.append("  nothing private found; the copy is identical to the source.")
    _finish_create(
        params,
        str(out),
        "scrub",
        content,
        human,
        file=resolved,
        previous_content=source_text,
        backup=backup,
        diff_label=resolved,
        encoding=coll.lib.encoding,
        warnings=report.warnings,
        check=False,
        source_sha256=_source_sha256(coll),
        removed=report.to_dict(),
        where=where,
        keys=parse_key_selector(key),
        selected=None if selector is None else len(coll.lib.entries),
        left_out=dropped,
    )


def _check_result(
    resolved: str, coll: Bibliography, report: scrub_ops.ScrubReport, params: RunParams
) -> None:
    """Emit the read-only ``--check`` result and gate on the finding."""
    message = (
        "no private content found"
        if report.clean
        else "private content found; scrub before releasing this file"
    )
    payload = {
        "status": "success",
        "action": "scrub",
        "check": True,
        "file": resolved,
        "source_sha256": _source_sha256(coll),
        "out": None,
        "dry_run": True,
        "written": False,
        "warnings": report.warnings,
        "clean": report.clean,
        "removed": report.to_dict(),
        "message": message,
    }
    human = [f"{resolved}: {message}", *_summary_lines(report)]
    _emit(params.json_output, payload, human)
    if not report.clean:
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(scrub))
