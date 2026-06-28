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
from pynakes.engine import Bibliography
from pynakes.lint import is_profile_issue
from pynakes.lint import lint as lint_lib

# --- lint ------------------------------------------------------------------


def _lint_one(file: str) -> CheckOutcome:
    lib = Bibliography.open(file).lib
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
    # Structural errors and declared-profile deviations gate a strict build.
    # Other lint warnings (e.g. a missing DOI) remain advisory.
    return CheckOutcome(
        result=result,
        human=human,
        failed=errors > 0 or any(is_profile_issue(issue) for issue in issues),
        summary={"issues": len(issues), "errors": errors, "warnings": warnings},
    )


def lint(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit 1 on errors or metadata-profile deviations",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues (accepts multiple files for CI gating)."""
    _run_checks(files, "lint", _lint_one, json_output, strict)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(lint))
