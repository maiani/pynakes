"""Configured offline normalization and formatting in one transaction per file."""

from enum import Enum

import typer

from pynakes.canonical import FormatLintError
from pynakes.cli._common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.cli._multi_mod import run_many
from pynakes.engine import Bibliography
from pynakes.usage import MissingTexSourcesError


class FixMode(str, Enum):
    normalize_and_format = "normalize-and-format"
    layout_only = "layout-only"


def fix(
    file: list[str] | None = bib_file_argument("Paths to .bib files (default: auto-detect one)"),
    mode: FixMode | None = typer.Option(
        None,
        "--mode",
        help="Apply configured normalization and layout, or layout only (setting: fix-mode)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
) -> None:
    """Apply configured normalization, then formatting, offline.

    Both phases are staged before a single commit per bibliography. Key
    regeneration stays off unless normalize-keys explicitly enables it. This
    does not fill missing bibliographic data or apply every lint suggestion.
    Multiple files run independently, preserving each file's own settings.
    """
    if file and len(file) > 1:
        run_many(fix, "fix", locals().copy())
        return
    source = file[0] if file else None
    if source == "-":
        _emit_error(json_output, "InvalidInput", "fix requires bibliography paths")
    resolved = _resolve_input_bib(source, json_output)
    coll = Bibliography.open(resolved)
    try:
        report = coll.fix(mode.value if mode is not None else None)
    except FormatLintError as exc:
        _emit_error(
            json_output, "FormatLintError", str(exc), issues=[i.to_dict() for i in exc.issues]
        )
    except MissingTexSourcesError as exc:
        _emit_error(
            json_output,
            "MissingTexSource",
            str(exc),
            sources=exc.sources,
            hint="Restore/remove the declared sources before regenerating keys.",
        )
    _finish_mod(
        resolved,
        "fix",
        coll,
        RunParams(
            dry_run=dry_run,
            diff=diff,
            json_output=json_output,
            backup=backup,
            expect_sha256=expect_sha256,
        ),
        ["Would apply configured fixes." if dry_run else "Applied configured fixes."],
        warnings=report.warnings if report is not None else [],
        mode="normalize-and-format" if report is not None else "layout-only",
        operations=report.operations if report is not None else {},
    )


def register(app: typer.Typer) -> None:
    app.command()(_safe(fix))
