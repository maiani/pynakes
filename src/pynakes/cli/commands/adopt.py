"""Local attachment adoption and interrupted transaction recovery."""

import typer

from pynakes.cli._choices import AdoptionMode, MaterialRole
from pynakes.cli._common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.filestore._transaction import retained_warnings


def adopt(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Citation key owning this attachment"),
    source: str = typer.Argument(..., help="Existing local file"),
    mode: AdoptionMode | None = typer.Option(
        None, "--mode", help="Override pinax-adopt-mode (default move)"
    ),
    role: MaterialRole | None = typer.Option(None, "--role", help="Override pinax-adopt-role"),
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without moving any files"),
    diff: bool = typer.Option(False, "--diff", help="Show bibliography changes"),
    backup: bool = _BACKUP_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON envelope"),
) -> None:
    """Move a file into Pinax and link it; --mode copy keeps the original.

    Stored bytes, provenance and bibliography are committed before removing the
    source. Use asset recover after an interrupted adoption.
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
    report = coll.adopt_file(
        key, source, mode=mode.value if mode else None, role=role.value if role else None
    )
    _finish_mod(
        file,
        "asset_adopt",
        coll,
        params,
        [f"{report['mode']}: {source} → {report['target']}"],
        adoption=report,
    )


def recover(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit a JSON envelope"),
) -> None:
    """Complete a journaled material adoption without fetching or inspecting PDFs."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    source_sha256 = _source_sha256(coll)
    report = coll.recover_adoptions()
    _emit(
        json_output,
        {
            "status": "success",
            "action": "asset_recover",
            "source_sha256": source_sha256,
            "file": file,
            "dry_run": False,
            "modified": report["recovered"],
            "modified_entries": 0,
            "warnings": retained_warnings(report),
            **report,
        },
        ["Adoption recovery complete."],
    )


def register(app: typer.Typer) -> None:
    app.command("adopt")(_safe(adopt))
    app.command("recover")(_safe(recover))
