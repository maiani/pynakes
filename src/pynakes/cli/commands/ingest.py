"""Native Library acquisition, durable pending review and recovery."""

import json
from pathlib import Path

import typer

from pynakes.cli._choices import AdoptionMode, MaterialRole
from pynakes.cli._common import _CACHE_FILE_OPTION, _emit, _emit_conflict, _safe
from pynakes.library import Library


def ingest(
    manifest: str = typer.Argument(..., help="Library manifest"),
    paths: list[str] = typer.Argument(
        ..., help="Files or directories (all immediate inputs are accounted for)"
    ),
    online: bool = typer.Option(
        False, "--online", help="Allow requested metadata provider lookups"
    ),
    decisions: str | None = typer.Option(
        None, "--decisions", help="Private JSON mapping source paths to hash-bound decisions"
    ),
    destination: str | None = typer.Option(
        None, "--destination", help="Override placement with a member path"
    ),
    mode: AdoptionMode | None = typer.Option(
        None, "--mode", help="Override pinax-adopt-mode (default move)"
    ),
    role: MaterialRole | None = typer.Option(None, "--role", help="Override pinax-adopt-role"),
    expect_plan: str | None = typer.Option(
        None, "--expect-plan", help="Require the full plan hash from a reviewed preview"
    ),
    cache_file: str | None = _CACHE_FILE_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview without writing ledger, materials or bibliographies"
    ),
    diff: bool = typer.Option(False, "--diff", help="Include member bibliography diffs"),
    json_output: bool = typer.Option(False, "--json", help="Emit per-source evidence and outcomes"),
) -> None:
    """Recover PDFs into member-owned Pinax stores; keep unresolved sources pending.

    Move is the default. Every input receives a durable receipt or pending reason
    on apply. Exit success does not imply all references were recovered: inspect
    complete and pending. A preview creates nothing.
    """
    choices = json.loads(Path(decisions).read_text(encoding="utf-8")) if decisions else None
    lib = Library.open(manifest)
    plan = lib.prepare_ingestion(
        paths,
        online=online,
        decisions=choices,
        destination=destination,
        mode=mode.value if mode else None,
        role=role.value if role else None,
        cache_file=cache_file,
    )
    if expect_plan is not None and expect_plan != plan.sha256:
        _emit_conflict(
            json_output,
            "ExternalModification",
            "Ingestion plan changed since review",
            options=[
                {"id": "preview", "description": "Preview the changed inputs and review a new plan"}
            ],
        )
    report = plan.to_dict() if dry_run else plan.commit(expect_sha256=expect_plan)
    if not diff:
        report.pop("diffs", None)
    _emit(
        json_output,
        {
            "status": "success",
            "action": "library_ingest",
            "file": manifest,
            "dry_run": dry_run,
            "modified": bool(plan.outputs),
            "source_sha256": lib.source_sha256,
            "modified_entries": report["modified_entries"],
            "warnings": [],
            **report,
        },
        [f"{report['accepted_records']} accepted records; {report['pending']} pending review."],
    )


def review(
    manifest: str = typer.Argument(..., help="Library manifest"),
    json_output: bool = typer.Option(False, "--json", help="Emit private ledger records"),
) -> None:
    """Read source receipts and pending review reasons; includes private paths."""
    lib = Library.open(manifest)
    ledger = lib.ingestion_ledger()
    _emit(
        json_output,
        {
            "status": "success",
            "action": "library_review",
            "file": manifest,
            "warnings": [],
            "source_sha256": lib.source_sha256,
            **ledger,
        },
        [
            f"{row['path']}: {row['status']} — {row.get('reason', '')}"
            for row in ledger["sources"].values()
        ],
    )


def recover(
    manifest: str = typer.Argument(..., help="Library manifest"),
    json_output: bool = typer.Option(False, "--json", help="Emit recovery report"),
) -> None:
    """Complete an interrupted ingestion from verified journal payloads."""
    lib = Library.open(manifest)
    report = lib.recover_ingestion()
    _emit(
        json_output,
        {
            "status": "success",
            "action": "library_recover",
            "source_sha256": lib.source_sha256,
            "file": manifest,
            "dry_run": False,
            "modified": report["recovered"],
            "modified_entries": 0,
            "warnings": [],
            **report,
        },
        ["Ingestion recovery complete."],
    )


def register(app: typer.Typer) -> None:
    app.command("ingest")(_safe(ingest))
    app.command("review")(_safe(review))
    app.command("recover")(_safe(recover))
