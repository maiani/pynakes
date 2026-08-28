"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from pathlib import Path

import typer

from pynakes.cli_common import (
    CheckOutcome,
    _emit_error,
    _run_checks,
    _safe,
)
from pynakes.engine import Bibliography
from pynakes.lint import CATEGORY_FIXERS, LintIssue, is_profile_issue
from pynakes.lint import lint as lint_lib

# --- lint ------------------------------------------------------------------


def _lint_one(file: str, categories: set[str] | None = None) -> CheckOutcome:
    lib = Bibliography.open(file).lib
    issues = lint_lib(lib, base_dir=Path(file).parent)
    if categories:
        issues = [issue for issue in issues if issue.category in categories]
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    infos = sum(1 for i in issues if i.severity == "info")
    by_category = {
        category: sum(1 for i in issues if i.category == category)
        for category in sorted({i.category for i in issues})
    }
    result = {
        "status": "success",
        "action": "lint",
        "file": file,
        "issue_count": len(issues),
        "errors": errors,
        "warnings": warnings,
        "info": infos,
        "by_category": by_category,
        "issues": [i.to_dict() for i in issues],
    }
    if not issues:
        human = [f"{file}: no issues found."]
    else:
        human = [f"  {_format_issue(issue)}" for issue in issues]
        human.append(
            f"{len(issues)} issue(s): {errors} error(s), {warnings} warning(s), {infos} info."
        )
        human.extend(_fixer_hints(issues))
    # Structural errors and declared-profile deviations gate a strict build.
    # Other findings (a missing DOI, layout drift) remain advisory.
    return CheckOutcome(
        result=result,
        human=human,
        failed=errors > 0 or any(is_profile_issue(issue) for issue in issues),
        summary={"issues": len(issues), "errors": errors, "warnings": warnings, "info": infos},
    )


def _format_issue(issue: LintIssue) -> str:
    """Render one finding for human output: ``[sev] key (line N): message``."""
    location = issue.key or ""
    if issue.line is not None:
        location = f"{location} (line {issue.line})" if location else f"line {issue.line}"
    prefix = f"[{issue.severity}] "
    return f"{prefix}{location}: {issue.message}" if location else f"{prefix}{issue.message}"


def _fixer_hints(issues: list) -> list[str]:
    """Return one line per command that would resolve some of ``issues``."""
    counts: dict[str, int] = {}
    for issue in issues:
        if issue.fixer is not None:
            command = (
                "normalize --keys on"
                if issue.type == "citation_key_pattern_mismatch"
                else issue.fixer
            )
            counts[command] = counts.get(command, 0) + 1
    return [
        f"Run `pynakes {command}` to resolve {count} of them."
        for command, count in sorted(counts.items())
    ]


def lint(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit 1 on errors or metadata-profile deviations",
    ),
    category: list[str] = typer.Option(
        [],
        "--category",
        help=(f"Report only these categories (repeatable): {', '.join(sorted(CATEGORY_FIXERS))}"),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues (accepts multiple files for CI gating)."""
    unknown = sorted(set(category) - set(CATEGORY_FIXERS))
    if unknown:
        _emit_error(
            json_output,
            "InvalidCategory",
            f"Unknown lint category: {', '.join(unknown)}; "
            f"expected one of: {', '.join(sorted(CATEGORY_FIXERS))}",
        )
        return
    categories = set(category)
    _run_checks(
        files,
        "lint",
        lambda file: _lint_one(file, categories),
        json_output,
        strict,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(lint))
