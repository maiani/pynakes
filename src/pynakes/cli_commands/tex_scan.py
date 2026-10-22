"""`tex scan`: report which entries the TeX sources cite.

The report only reads: the `used` predicate works in every `--where`, so
exporting or tagging the cited entries is the job of the commands that export
and tag.
"""

from pathlib import Path

import typer

from pynakes.cli_common import (
    _emit,
    _emit_error,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.usage import (
    analyze_usage,
    collect_citation_occurrences,
    resolve_existing_tex_sources,
    tex_sources_from_metadata,
)

# --- tex scan --------------------------------------------------------------

_NO_SOURCES = "No sources given and no 'tex-sources' metadata to fall back to"


def linked_scan_result(coll: Bibliography, file: str, location: str | Path) -> dict:
    """Return the `tex scan --json` envelope for the library's linked sources.

    The read-only scan `inspect --insights` reports beside the rest of the
    snapshot. ``location`` is where the library lives, so its relative
    ``tex-sources`` resolve from there even when ``file`` is a copy. A library
    with no linked sources on disk is the ``NoSources`` error envelope.
    """
    linked = tex_sources_from_metadata(coll.lib, Path(location).parent)
    existing, warnings = resolve_existing_tex_sources(linked)
    if not existing:
        return {"status": "error", "error": "NoSources", "message": _NO_SOURCES}
    occurrences, include_all, scanned = collect_citation_occurrences(existing)
    report = analyze_usage(
        coll.lib, set(occurrences), include_all=include_all, sources=scanned, usages=occurrences
    )
    return {
        "status": "success",
        "action": "tex_scan",
        "file": file,
        "warnings": warnings,
        "source_sha256": _source_sha256(coll),
        "report": report.to_dict(),
    }


def scan(
    file: str | None = bib_file_argument(),
    sources: list[str] | None = typer.Argument(
        None,
        help="One or more .tex/.aux files or directories to scan "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources, and which citations are missing.

    The report reads the given sources, else the library's linked
    `tex-sources`, and changes nothing. To act on the cited entries, select
    them with `--where used` wherever entries are selected: `corpus combine
    FILE --where used --out cited.bib` exports them, and `fields append FILE
    keywords cited --where used` tags them.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(file).parent)
    )
    warnings: list[dict] = []
    if not sources:
        resolved_sources, missing = resolve_existing_tex_sources(resolved_sources)
        warnings.extend(missing)
    if not resolved_sources:
        _emit_error(json_output, "NoSources", _NO_SOURCES)
        return
    occurrences, include_all, scanned = collect_citation_occurrences(resolved_sources)
    report = analyze_usage(
        coll.lib,
        set(occurrences),
        include_all=include_all,
        sources=scanned,
        usages=occurrences,
    )

    human = [
        f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).",
    ]
    human.extend(f"  {w['message']}" for w in warnings)
    if report.include_all:
        human.append(r"\nocite{*} found — all entries counted as used.")
    human.append(f"Used:    {len(report.used)}")
    human.append(f"Unused:  {len(report.unused)}")
    human.append(f"Missing: {len(report.missing)}")
    for key in report.missing:
        human.append(f"  - {key}  (cited but not in library)")

    result = {
        "status": "success",
        "action": "tex_scan",
        "file": file,
        "warnings": warnings,
        "source_sha256": _source_sha256(coll),
        "report": report.to_dict(),
    }
    _emit(json_output, result, human)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("scan")(_safe(scan))
