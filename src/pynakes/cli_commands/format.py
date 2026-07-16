"""Layout-only bibliography formatting command."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from pynakes.canonical import CanonicalLayout
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit,
    _emit_error,
    _finish_mod,
    _preview_or_commit,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
    is_auxiliary_bib_file,
)
from pynakes.engine import Bibliography


def _layout(
    indent: str | None,
    tabular: bool | None,
    trailing_comma: bool | None,
    blank_line_entries: bool | None,
    sort_fields: bool | None,
) -> CanonicalLayout:
    defaults = CanonicalLayout()
    if indent == "":
        raise ValueError("format indent must be a non-empty string")
    return CanonicalLayout(
        indent=defaults.indent if indent is None else indent,
        tabular=defaults.tabular if tabular is None else tabular,
        trailing_comma=defaults.trailing_comma if trailing_comma is None else trailing_comma,
        blank_line_entries=(
            defaults.blank_line_entries if blank_line_entries is None else blank_line_entries
        ),
        sort_fields=defaults.sort_fields if sort_fields is None else sort_fields,
    )


def _recursive_files(target: Path) -> list[Path]:
    if target.is_file():
        return [] if is_auxiliary_bib_file(target) else [target]
    return sorted(
        (
            path
            for path in target.rglob("*.bib")
            if not is_auxiliary_bib_file(path)
            and not any(part.startswith(".") for part in path.relative_to(target).parts)
        ),
        key=lambda path: str(path).casefold(),
    )


def _check_payload(file: str, coll: Bibliography) -> dict[str, object]:
    modified = coll.is_modified
    return {
        "status": "success",
        "action": "format-check",
        "file": file,
        "dry_run": True,
        "modified": modified,
        "modified_entries": coll.changed_entries_count() if modified else 0,
        "warnings": [],
        "plan": coll.change_plan(),
        "message": "File needs formatting" if modified else "File is already formatted",
    }


def _run_recursive(
    files: list[Path], layout: CanonicalLayout, params: RunParams, *, check: bool
) -> None:
    results: list[dict[str, object]] = []
    failures = 0
    dirty = 0
    modified_count = 0
    for path in files:
        try:
            coll = Bibliography.open(path)
            coll.format(layout)
            plan = coll.change_plan()
            if check:
                payload = _check_payload(str(path), coll)
                dirty += int(bool(payload["modified"]))
            else:
                diff_text, modified, changed = _preview_or_commit(coll, params)
                modified_count += int(modified)
                payload = {
                    "status": "success",
                    "action": "format",
                    "file": str(path),
                    "dry_run": params.dry_run,
                    "modified": modified,
                    "modified_entries": changed,
                    "warnings": [],
                    "plan": plan,
                }
                if params.diff and diff_text:
                    payload["diff"] = diff_text
            results.append(payload)
        except Exception as exc:
            failures += 1
            results.append(
                {
                    "status": "error",
                    "action": "format-check" if check else "format",
                    "file": str(path),
                    "dry_run": check or params.dry_run,
                    "modified": False,
                    "modified_entries": 0,
                    "warnings": [],
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

    payload = {
        "status": "error" if failures else "success",
        "action": "format-check" if check else "format",
        "file": str(files[0].parent) if files else ".",
        "dry_run": check or params.dry_run,
        "modified": bool(dirty if check else modified_count),
        "modified_entries": sum(int(item.get("modified_entries", 0)) for item in results),
        "warnings": [],
        "files": results,
        "summary": {
            "files": len(files),
            "modified": dirty if check else modified_count,
            "failed": failures,
        },
    }
    if failures:
        payload["error"] = "RecursiveFormatError"
        payload["message"] = f"{failures} file(s) failed"
    human = [
        f"{len(files)} file(s): {dirty if check else modified_count} need/received formatting, "
        f"{failures} failed"
    ]
    _emit(params.json_output, payload, human)
    if failures or (check and dirty):
        raise typer.Exit(code=1)


def format_bibliography(
    file: str | None = bib_file_argument("Path, directory with --recursive, or - for stdin"),
    indent: str | None = typer.Option(None, "--indent", help="Field indentation string"),
    tabular: bool | None = typer.Option(None, "--tabular/--no-tabular", help="Align = signs"),
    trailing_comma: bool | None = typer.Option(
        None, "--trailing-comma/--no-trailing-comma", help="Comma after the last field"
    ),
    blank_line_entries: bool | None = typer.Option(
        None, "--blank-lines/--no-blank-lines", help="Blank line between entries"
    ),
    sort_fields: bool | None = typer.Option(
        None,
        "--sort-fields/--preserve-field-order",
        help="Use pynakes' preferred field order",
    ),
    check: bool = typer.Option(False, "--check", help="Exit 1 when layout changes are needed"),
    to_stdout: bool = typer.Option(
        False, "--stdout", help="Write formatted bibliography to stdout"
    ),
    recursive: bool = typer.Option(False, "--recursive", help="Format .bib files recursively"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Rewrite layout only; never change bibliographic values or conventions."""
    if to_stdout and (json_output or check or recursive):
        _emit_error(
            json_output,
            "InvalidInput",
            "--stdout cannot be combined with --json, --check, or --recursive",
        )
    if file == "-" and not to_stdout:
        _emit_error(json_output, "InvalidInput", "stdin input (-) requires --stdout")
    layout = _layout(indent, tabular, trailing_comma, blank_line_entries, sort_fields)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)

    if recursive:
        target = Path(file or ".")
        files = _recursive_files(target)
        if not files:
            _emit_error(json_output, "FileNotFound", f"No .bib files found under {target}")
        _run_recursive(files, layout, params, check=check)
        return

    if file == "-":
        coll = Bibliography.from_text(sys.stdin.read())
        coll.format(layout)
        sys.stdout.write(coll.preview())
        return

    resolved = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(resolved)
    coll.format(layout)
    if to_stdout:
        sys.stdout.write(coll.preview())
        return
    if check:
        payload = _check_payload(resolved, coll)
        _emit(json_output, payload, [f"{resolved}: {payload['message'].lower()}"])
        if payload["modified"]:
            raise typer.Exit(code=1)
        return
    _finish_mod(resolved, "format", coll, params, ["Formatted bibliography layout."], warnings=[])


def register(app: typer.Typer) -> None:
    app.command("format")(_safe(format_bibliography))
