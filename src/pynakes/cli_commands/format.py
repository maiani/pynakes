"""Layout-only bibliography formatting command."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import typer

from pynakes.canonical import CanonicalLayout, FormatLintError, layout_from_metadata
from pynakes.cli_checks import error_code_for
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    _FORCE_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit,
    _emit_error,
    _entries,
    _finish_create,
    _finish_mod,
    _preview_or_commit,
    _refuse_existing_output,
    _refuse_input_as_output,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
    build_where_filter,
    is_auxiliary_bib_file,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.model import BibFile, QueryFilter


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


class EntryTypeCaseChoice(str, Enum):
    lower = "lower"
    preserve = "preserve"


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
    entry_type_case: EntryTypeCaseChoice | None = None


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
        entry_type_case=(
            overrides.entry_type_case.value if overrides.entry_type_case is not None else None
        ),
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


def _check_payload(
    file: str,
    coll: Bibliography,
    where: str | None = None,
    keys: list[str] | None = None,
) -> dict[str, object]:
    modified = coll.is_modified
    if where is None and not keys:
        message = "File needs formatting" if modified else "File is already formatted"
    else:
        message = (
            "Selected entries need formatting"
            if modified
            else "Selected entries are already formatted"
        )
    return {
        "status": "success",
        "action": "format",
        "check": True,
        "file": file,
        "source_sha256": _source_sha256(coll),
        "dry_run": True,
        "modified": modified,
        "modified_entries": coll.changed_entries_count() if modified else 0,
        "warnings": [],
        "where": where,
        "keys": list(keys or []),
        "plan": coll.change_plan(),
        "message": message,
    }


def _failure_code(exc: Exception) -> str:
    """Return the catalogued code for one file's failure in a recursive run."""
    if isinstance(exc, FormatLintError):
        return "FormatLintError"
    return error_code_for(exc).value


def _run_recursive(
    files: list[Path],
    overrides: FormatOverrides,
    params: RunParams,
    *,
    check: bool,
    where: str | None = None,
    keys: list[str] | None = None,
    selector: QueryFilter = None,
) -> None:
    results: list[dict[str, object]] = []
    failures = 0
    dirty = 0
    modified_count = 0
    for path in files:
        try:
            coll = Bibliography.open(path)
            layout = _layout(coll.lib, overrides)
            coll.format(layout, selector)
            plan = coll.change_plan()
            if check:
                payload = _check_payload(str(path), coll, where, keys)
                dirty += int(bool(payload["modified"]))
            else:
                diff_text, modified, changed = _preview_or_commit(coll, params)
                modified_count += int(modified)
                payload = {
                    "status": "success",
                    "action": "format",
                    "check": False,
                    "file": str(path),
                    "source_sha256": _source_sha256(coll),
                    "dry_run": params.dry_run,
                    "modified": modified,
                    "modified_entries": changed,
                    "warnings": [],
                    "where": where,
                    "keys": list(keys or []),
                    "plan": plan,
                }
                if params.diff and diff_text:
                    payload["diff"] = diff_text
            results.append(payload)
        except Exception as exc:
            failures += 1
            failure = {
                "status": "error",
                "action": "format",
                "check": check,
                "file": str(path),
                "dry_run": check or params.dry_run,
                "modified": False,
                "modified_entries": 0,
                "warnings": [],
                "error": _failure_code(exc),
                "message": getattr(exc, "message", str(exc)),
            }
            if isinstance(exc, FormatLintError):
                failure["issues"] = [issue.to_dict() for issue in exc.issues]
            results.append(failure)

    payload = {
        "status": "error" if failures else "success",
        "action": "format",
        "check": check,
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
    entry_type_case: EntryTypeCaseChoice | None = typer.Option(
        None,
        "--entry-type-case",
        help="Entry-type spelling: lowercase, or keep each entry's own (e.g. @Article)",
    ),
    where: str | None = where_option(
        "Reformat only the entries matching this selector; the rest of the file "
        "stays byte-for-byte identical"
    ),
    key: list[str] | None = key_option(
        "Reformat only these citation keys: comma-separated, repeatable. Narrows "
        "--where when both are given"
    ),
    check: bool = typer.Option(
        False, "--check", help="Write nothing; exit 1 when layout changes are needed"
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Write the formatted library here instead of in place; - for stdout",
    ),
    force: bool = _FORCE_OPTION,
    recursive: bool = typer.Option(False, "--recursive", help="Format .bib files recursively"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
) -> None:
    """Rewrite layout only; never change bibliographic values or conventions.

    ``--where`` restricts the rewrite to the matching entries. A selection owns
    the layout inside each entry it matches, not the layout of the file, so
    ``--entry-order``, ``--block-order``, and ``--blank-lines`` are whole-file
    policies that cannot be combined with it.
    """
    to_stdout = out == "-"
    if out is not None and (check or recursive):
        _emit_error(
            json_output, "InvalidInput", "--out cannot be combined with --check or --recursive"
        )
    if to_stdout and json_output:
        _emit_error(json_output, "InvalidInput", "--out - writes the library itself, not JSON")
    if file == "-" and not to_stdout:
        _emit_error(json_output, "InvalidInput", "stdin input (-) requires --out -")
    if recursive and expect_sha256 is not None:
        _emit_error(json_output, "InvalidInput", "--expect-sha256 names one file's digest")
    selected_keys = parse_key_selector(key)
    selector = build_where_filter(where, keys=key)
    if selector is not None:
        whole_file = {
            "--entry-order": entry_order,
            "--block-order": block_order,
            "--blank-lines/--no-blank-lines": blank_line_entries,
        }
        conflicting = [name for name, value in whole_file.items() if value is not None]
        if conflicting:
            _emit_error(
                json_output,
                "InvalidInput",
                f"{'--where' if where is not None else '--key'} selects entries, so "
                f"it cannot be combined with the whole-file option(s) "
                f"{', '.join(conflicting)}",
            )
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
        entry_type_case=entry_type_case,
    )
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )

    if recursive:
        target = Path(file or ".")
        files = _recursive_files(target)
        if not files:
            _emit_error(json_output, "FileNotFound", f"No .bib files found under {target}")
        _run_recursive(
            files,
            overrides,
            params,
            check=check,
            where=where,
            keys=selected_keys,
            selector=selector,
        )
        return

    if file == "-":
        coll = Bibliography.from_text(sys.stdin.read())
        try:
            coll.format(_layout(coll.lib, overrides), selector)
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
    if out is not None and not to_stdout:
        _refuse_input_as_output(json_output, out, [resolved])
        _refuse_existing_output(json_output, out, force)
    coll = Bibliography.open(resolved)
    _check_expected_sha256(resolved, coll, params)
    source_text = coll.preview()
    try:
        selected = coll.format(_layout(coll.lib, overrides), selector)
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
    if out is not None:
        _write_copy(resolved, out, coll, params, source_text, where, selected_keys)
        return
    if check:
        payload = _check_payload(resolved, coll, where, selected_keys)
        _emit(json_output, payload, [f"{resolved}: {payload['message'].lower()}"])
        if payload["modified"]:
            raise typer.Exit(code=1)
        return
    human = (
        f"Formatted the layout of {selected} selected {_entries(selected)}."
        if selector is not None
        else "Formatted bibliography layout."
    )
    _finish_mod(
        resolved,
        "format",
        coll,
        params,
        [human],
        warnings=[],
        check=False,
        where=where,
        keys=selected_keys,
    )


def _write_copy(
    resolved: str,
    out: str,
    coll: Bibliography,
    params: RunParams,
    source_text: str,
    where: str | None,
    keys: list[str],
) -> None:
    """Write the formatted library to ``--out``, leaving the input untouched."""
    _finish_create(
        params,
        out,
        "format",
        coll.preview(),
        [f"{_verb('write', params, 'Wrote')} the formatted library to {out}."],
        file=resolved,
        previous_content=source_text,
        diff_label=resolved,
        encoding=coll.lib.encoding,
        check=False,
        source_sha256=_source_sha256(coll),
        modified=False,
        modified_entries=0,
        where=where,
        keys=keys,
    )


def register(app: typer.Typer) -> None:
    app.command("format")(_safe(format_bibliography))
