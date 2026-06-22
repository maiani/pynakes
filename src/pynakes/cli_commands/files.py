"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from typing import Optional

import typer

from pynakes import files as files_ops
from pynakes.cli_common import (
    CheckOutcome,
    _run_checks,
    _safe,
)
from pynakes.io import load_bib

# --- files -----------------------------------------------------------------


def _files_check_one(file: str, root: Optional[list[str]]) -> CheckOutcome:
    lib = load_bib(file)
    report = files_ops.check_linked_files(lib, file, root)
    result = {
        "status": "success",
        "action": "files_check",
        "file": file,
        **report.to_dict(),
    }
    human = [
        f"{file}: checked {report.checked} linked file(s); "
        f"ok={report.ok}, missing={report.missing}, "
        f"wrong_type={report.wrong_type}, unresolved={report.unresolved}."
    ]
    human += [
        f"  [{issue.status}] {issue.entry_key}[{issue.index}]: {issue.path}"
        for issue in report.issues
    ]
    bad = report.missing + report.wrong_type + report.unresolved
    return CheckOutcome(
        result=result,
        human=human,
        failed=bad > 0,
        summary={
            "checked": report.checked,
            "ok": report.ok,
            "missing": report.missing,
            "wrong_type": report.wrong_type,
            "unresolved": report.unresolved,
        },
    )


def files_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    root: Optional[list[str]] = typer.Option(
        None,
        "--root",
        help="Additional directory to resolve relative linked-file paths; can be repeated",
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if any linked file is missing or wrong-type"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate JabRef linked files (accepts multiple files for CI gating)."""
    _run_checks(files, "files_check", lambda f: _files_check_one(f, root), json_output, strict)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(files_check))
