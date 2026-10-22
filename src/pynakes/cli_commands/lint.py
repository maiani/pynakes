"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from pathlib import Path

import typer

from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_choices import LintCategory, LintSeverity
from pynakes.cli_common import _emit_error, _safe, _source_sha256
from pynakes.engine import Bibliography
from pynakes.lint import (
    LintIssue,
    library_lint_severity,
    suppress_findings,
    unknown_ignore_names,
    unknown_issue_types,
)
from pynakes.lint import lint as lint_lib

# --- lint ------------------------------------------------------------------


#: Severities from most to least severe; ``--severity`` keeps a prefix of this.
_SEVERITY_ORDER = ("error", "warning", "info")


def _lint_one(
    file: str,
    categories: set[str] | None = None,
    ignores: frozenset[str] = frozenset(),
    min_severity: str | None = None,
    summary_only: bool = False,
    types: frozenset[str] = frozenset(),
    include_ignored: bool = False,
) -> CheckOutcome:
    return _lint_collection(
        Bibliography.open(file),
        file,
        categories,
        ignores,
        min_severity,
        summary_only,
        types,
        include_ignored=include_ignored,
    )


def _lint_collection(
    coll: Bibliography,
    file: str,
    categories: set[str] | None = None,
    ignores: frozenset[str] = frozenset(),
    min_severity: str | None = None,
    summary_only: bool = False,
    types: frozenset[str] = frozenset(),
    location: str | Path | None = None,
    include_ignored: bool = False,
) -> CheckOutcome:
    """Build the same lint report for an already opened bibliography.

    ``min_severity`` and ``types`` narrow the report as ``categories`` does;
    ``min_severity`` ``None`` reads the library's ``lint-severity`` setting.
    ``include_ignored`` reports what ``lint-ignore`` and ignore directives
    would suppress, for a run that needs to see the library's waivers.
    ``location`` is where the library lives (default ``file``), for the checks
    that resolve paths relative to it. ``summary_only``
    leaves the per-finding list out and says so (``issues_omitted``); every
    count, ``by_type`` included, still covers each finding reported.
    """
    lib = coll.lib
    # The command line adds to the library's own `lint-ignore`; it never
    # re-enables what the library ignores. `ignore` directives above an entry
    # waive that entry's findings.
    base_dir = Path(location if location is not None else file).parent
    found = lint_lib(lib, base_dir=base_dir)
    if include_ignored:
        issues, suppressed = [i for i in found if not i.is_ignored(ignores)], 0
    else:
        issues, suppressed = suppress_findings(lib, found, ignores)
    min_severity = library_lint_severity(lib, min_severity)
    if categories:
        issues = [issue for issue in issues if issue.category in categories]
    if types:
        issues = [issue for issue in issues if issue.type in types]
    kept = set(_SEVERITY_ORDER[: _SEVERITY_ORDER.index(min_severity) + 1])
    issues = [issue for issue in issues if issue.severity in kept]
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
        "source_sha256": _source_sha256(coll),
        "warnings": [],
        "summary": {
            "issues": len(issues),
            "errors": errors,
            "warnings": warnings,
            "info": infos,
            "suppressed": suppressed,
            "by_category": by_category,
            "by_type": {
                issue_type: sum(1 for i in issues if i.type == issue_type)
                for issue_type in sorted({i.type for i in issues})
            },
        },
        "issues": [] if summary_only else [i.to_dict() for i in issues],
    }
    if summary_only:
        result["issues_omitted"] = len(issues)
    if not issues:
        human = [f"{file}: no issues found."]
    else:
        # The counts come first, so a long report opens with its shape.
        human = [
            f"{len(issues)} issue(s): {errors} error(s), {warnings} warning(s), {infos} info.",
            "By category: "
            + ", ".join(f"{category} {count}" for category, count in by_category.items())
            + ".",
        ]
        if not summary_only:
            human.extend(f"  {_format_issue(issue)}" for issue in issues)
        human.extend(_fixer_hints(issues))
    if suppressed:
        human.append(
            f"{suppressed} finding(s) suppressed by lint-ignore, --ignore, or an ignore directive."
        )
    # --strict means clean: any finding left after suppression fails it, as
    # every other gate fails on any finding. A finding the library accepts is
    # suppressed explicitly (lint-ignore, --ignore, an ignore directive).
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(issues),
        summary={
            "issues": len(issues),
            "errors": errors,
            "warnings": warnings,
            "info": infos,
            "suppressed": suppressed,
        },
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
                "normalize --key-generation on"
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
    strict: bool = strict_option(
        "any finding is left after lint-ignore, --ignore, and ignore directives"
    ),
    category: list[LintCategory] = typer.Option(
        [],
        "--category",
        help="Report only these categories (repeatable)",
    ),
    ignore: list[str] = typer.Option(
        [],
        "--ignore",
        metavar="NAME",
        help="Leave out a finding type (missing_doi) or a whole category (consistency); "
        "repeatable, and added to the library's lint-ignore setting",
    ),
    only: list[str] = typer.Option(
        [],
        "--only",
        metavar="TYPE",
        help="Report only these finding types (duplicate_key, missing_doi, ...): "
        "comma-separated, repeatable",
    ),
    severity: LintSeverity | None = typer.Option(
        None,
        "--severity",
        help="Report only findings at least this severe: error, warning, or info (all); "
        "default: the library's lint-severity setting, else info",
    ),
    include_ignored: bool = typer.Option(
        False,
        "--include-ignored",
        help="Also report the findings the library's lint-ignore setting and ignore "
        "directives waive (they then count for --strict)",
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        help="Report counts (by severity, category and type) without listing each finding; "
        "the omitted count is reported as issues_omitted",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues (accepts multiple files for CI gating).

    `--category`, `--only`, and `--severity` narrow what is reported, and
    `--strict` fails on what remains — `lint --only duplicate_key --strict`
    gates on duplicate citation keys alone; `--summary` keeps every count but leaves out the
    per-finding list.
    """
    categories = {item.value for item in category}
    unknown = unknown_ignore_names(ignore)
    if unknown:
        _emit_error(
            json_output,
            "InvalidInput",
            f"--ignore names no finding type or category: {', '.join(unknown)}",
        )
    ignores = frozenset(ignore)
    types = frozenset(name.strip() for value in only for name in value.split(",") if name.strip())
    unknown_types = unknown_issue_types(sorted(types))
    if unknown_types:
        _emit_error(
            json_output,
            "InvalidInput",
            f"--only names no finding type: {', '.join(unknown_types)}",
        )
    _run_checks(
        files,
        "lint",
        lambda file: _lint_one(
            file,
            categories,
            ignores,
            None if severity is None else severity.value,
            summary,
            types,
            include_ignored,
        ),
        json_output,
        strict,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(lint))
