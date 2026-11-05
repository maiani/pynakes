"""PDF acquisition through the engine's normal preview/commit lifecycle."""

import typer

from pynakes.cli._choices import KeySource
from pynakes.cli._common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography


def from_pdf(
    file: str | None = bib_file_argument(),
    paths: list[str] = typer.Argument(..., help="PDF files or directories (immediate PDFs only)"),
    online: bool = typer.Option(
        False,
        "--online",
        help="Resolve DOI/arXiv candidates through metadata providers; never upload PDFs",
    ),
    identifier: str | None = typer.Option(
        None, "--identifier", help="Confirm a DOI/arXiv identifier for one PDF, including scans"
    ),
    key: str | None = typer.Option(None, "--key", help="Citation key for a single PDF"),
    key_source: KeySource | None = typer.Option(
        None, "--key-source", help="Override import-key-source: generated or provider"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Inspect and preview accepted imports without writing"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified bibliography diff"),
    cache_file: str | None = _CACHE_FILE_OPTION,
    json_output: bool = typer.Option(
        False, "--json", help="Emit per-file evidence and outcomes as JSON"
    ),
) -> None:
    """Import references from PDFs and link their unchanged originals.

    Offline by default: use embedded BibTeX/XMP, or --online to resolve
    identifiers corroborated by document titles. Ambiguous and unresolved PDFs
    remain in the report; partial batches import only accepted records.
    Requires pynakes[pdf]. Initialize the destination bibliography first.
    """
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
    report = coll.import_pdfs(
        paths,
        online=online,
        identifier=identifier,
        key=key,
        key_source=key_source.value if key_source else None,
        cache_file=cache_file,
    ).to_dict()
    summary = report["summary"]
    accepted = summary["imported"] + summary["linked"] + summary["existing"]
    warnings = [
        {
            "type": "pdf_import_incomplete",
            "path": row["path"],
            "message": row.get("message", row.get("reason", row["status"])),
        }
        for row in report["results"]
        if row["status"] not in {"imported", "linked", "existing"}
    ]
    if not accepted:
        if summary["ambiguous"]:
            _emit_conflict(
                json_output,
                "PDFImportConflict",
                "PDF evidence needs review; no references were imported",
                options=[
                    {
                        "id": "select_identifier",
                        "description": "Review candidates, then retry one PDF with --identifier and --online",
                    },
                    {
                        "id": "review_existing",
                        "description": "Review existing records and citation keys before retrying",
                    },
                ],
                **report,
            )
        _emit_error(
            json_output,
            "PDFImportError",
            "No PDF could be imported; inspect per-file outcomes",
            **report,
        )
    human = [
        f"PDF import: {summary['imported']} new, {summary['linked']} attached, {summary['existing']} already present; {report['requested'] - accepted} need attention."
    ]
    human.extend(
        f"  {row['path']}: {row['status']}" + (f" ({row['reason']})" if row.get("reason") else "")
        for row in report["results"]
    )
    _finish_mod(file, "ref_from_pdf", coll, params, human, warnings=warnings, **report)


def register(app: typer.Typer) -> None:
    app.command("from-pdf")(_safe(from_pdf))
