"""Layout-only bibliography formatting command."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import typer

from pynakes.canonical import CanonicalLayout, FormatLintError, layout_from_metadata
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
from pynakes.model import BibFile


class AlignmentChoice(str, Enum):
    compact = "compact"
    equals = "equals"


class FieldOrderChoice(str, Enum):
    preferred = "preferred"
    preserve = "preserve"
    alphabetical = "alphabetical"


class EntryOrderChoice(str, Enum):
    preserve = "preserve"
    key = "key"
    profile = "profile"


class BlockOrderChoice(str, Enum):
    preserve = "preserve"
    canonical = "canonical"


class WrapValuesChoice(str, Enum):
    off = "off"
    stable = "stable"
    canonical = "canonical"


@dataclass(frozen=True)
class FormatOverrides:
    indent: str | None
    alignment: AlignmentChoice | None
    trailing_comma: bool | None
    blank_line_entries: bool | None
    field_order: FieldOrderChoice | None
    entry_order: EntryOrderChoice | None
    block_order: BlockOrderChoice | None
    wrap_values: WrapValuesChoice | None
    line_width: int | None


def _layout(
    lib: BibFile,
    overrides: FormatOverrides,
) -> CanonicalLayout:
    indent = overrides.indent
    if indent == "":
        raise ValueError("format indent must be a non-empty string")
    return layout_from_metadata(
        lib,
        indent=indent,
        alignment=overrides.alignment.value if overrides.alignment is not None else None,
        trailing_comma=overrides.trailing_comma,
        blank_line_entries=overrides.blank_line_entries,
        field_order=overrides.field_order.value if overrides.field_order is not None else None,
        entry_order=overrides.entry_order.value if overrides.entry_order is not None else None,
        block_order=overrides.block_order.value if overrides.block_order is not None else None,
        wrap_values=overrides.wrap_values.value if overrides.wrap_values is not None else None,
        line_width=overrides.line_width,
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
    files: list[Path], overrides: FormatOverrides, params: RunParams, *, check: bool
) -> None:
    results: list[dict[str, object]] = []
    failures = 0
    dirty = 0
    modified_count = 0
    for path in files:
        try:
            coll = Bibliography.open(path)
            layout = _layout(coll.lib, overrides)
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
            failure = {
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
            if isinstance(exc, FormatLintError):
                failure["issues"] = [issue.to_dict() for issue in exc.issues]
            results.append(failure)

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
    alignment: AlignmentChoice | None = typer.Option(
        None, "--alignment", help="Field/value alignment policy"
    ),
    trailing_comma: bool | None = typer.Option(
        None, "--trailing-comma/--no-trailing-comma", help="Comma after the last field"
    ),
    blank_line_entries: bool | None = typer.Option(
        None, "--blank-lines/--no-blank-lines", help="Blank line between entries"
    ),
    field_order: FieldOrderChoice | None = typer.Option(
        None, "--field-order", help="Field ordering policy"
    ),
    entry_order: EntryOrderChoice | None = typer.Option(
        None, "--entry-order", help="Entry ordering policy"
    ),
    block_order: BlockOrderChoice | None = typer.Option(
        None, "--block-order", help="Top-level block ordering policy"
    ),
    wrap_values: WrapValuesChoice | None = typer.Option(
        None, "--wrap-values", help="Safe field-value wrapping policy"
    ),
    line_width: int | None = typer.Option(
        None, "--line-width", min=20, help="Maximum line width for wrapped values"
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
    overrides = FormatOverrides(
        indent=indent,
        alignment=alignment,
        trailing_comma=trailing_comma,
        blank_line_entries=blank_line_entries,
        field_order=field_order,
        entry_order=entry_order,
        block_order=block_order,
        wrap_values=wrap_values,
        line_width=line_width,
    )
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)

    if recursive:
        target = Path(file or ".")
        files = _recursive_files(target)
        if not files:
            _emit_error(json_output, "FileNotFound", f"No .bib files found under {target}")
        _run_recursive(files, overrides, params, check=check)
        return

    if file == "-":
        coll = Bibliography.from_text(sys.stdin.read())
        try:
            coll.format(_layout(coll.lib, overrides))
        except FormatLintError as exc:
            _emit_error(
                json_output,
                "FormatLintError",
                str(exc),
                issues=[issue.to_dict() for issue in exc.issues],
            )
        sys.stdout.write(coll.preview())
        return

    resolved = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(resolved)
    try:
        coll.format(_layout(coll.lib, overrides))
    except FormatLintError as exc:
        _emit_error(
            json_output,
            "FormatLintError",
            str(exc),
            issues=[issue.to_dict() for issue in exc.issues],
        )
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
