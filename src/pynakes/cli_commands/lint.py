"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes.cli_common import (
    CheckOutcome,
    _run_checks,
    _safe,
)
from pynakes.io import load_bib
from pynakes.lint import lint as lint_lib

# --- lint ------------------------------------------------------------------


def _lint_one(file: str) -> CheckOutcome:
    lib = load_bib(file)
    issues = lint_lib(lib)
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    result = {
        "status": "success",
        "action": "lint",
        "file": file,
        "issue_count": len(issues),
        "errors": errors,
        "warnings": warnings,
        "issues": [i.to_dict() for i in issues],
    }
    if not issues:
        human = [f"{file}: no issues found."]
    else:
        human = [
            f"  [{issue.severity}] {f'{issue.key}: ' if issue.key else ''}{issue.message}"
            for issue in issues
        ]
        human.append(f"{len(issues)} issue(s): {errors} error(s), {warnings} warning(s).")
    # Only errors gate a --strict build; lint warnings (e.g. a missing DOI) are
    # advisory. (verify --strict is broader because its warnings flag integrity
    # mismatches against authoritative metadata.)
    return CheckOutcome(
        result=result,
        human=human,
        failed=errors > 0,
        summary={"issues": len(issues), "errors": errors, "warnings": warnings},
    )


def lint(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any errors are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues (accepts multiple files for CI gating)."""
    _run_checks(files, "lint", _lint_one, json_output, strict)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(lint))
