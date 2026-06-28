"""Shared CLI output, error handling, and check orchestration."""

import functools
import json as _json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import typer

from pynakes.bibtex_parser import ParseError
from pynakes.engine import Bibliography, ExternalModificationError

_F = TypeVar("_F", bound=Callable)

# --- shared helpers --------------------------------------------------------


def _resolve_input_bib(file: str | None, json_output: bool, *, label: str = ".bib") -> str:
    """Return the input ``file`` path, auto-detecting when ``None``.

    When ``file`` is ``None``, scans the current directory for files matching
    ``*{label}``. If exactly one is found, returns it. If none or multiple
    are found, emits an error (never returns).
    """
    if file is not None:
        return file
    candidates = sorted(Path(".").glob(f"*{label}"))
    if not candidates:
        _emit_error(
            json_output,
            "InvalidInput",
            f"No *{label} file found in current directory; specify one as an argument",
        )
    if len(candidates) > 1:
        names = "  ".join(c.name for c in candidates)
        _emit_error(
            json_output,
            "InvalidInput",
            f"Multiple *{label} files found; specify one as an argument:\n{names}",
        )
    return str(candidates[0])


def _emit(
    json_output: bool,
    result: dict,
    human: list[str],
    diff_text: str = "",
    show_diff: bool = False,
) -> None:
    if json_output:
        if show_diff and diff_text:
            result["diff"] = diff_text
        typer.echo(_json.dumps(result, indent=2))
        return
    for line in human:
        typer.echo(line)
    if show_diff and diff_text:
        typer.echo("")
        typer.echo(diff_text)


def _entries(count: int) -> str:
    return "entry" if count == 1 else "entries"


def _verb(action: str, dry_run: bool, past: str | None = None) -> str:
    """Return ``"Would <action>"`` in dry-run mode, or the past-tense form otherwise.

    For regular verbs the past tense is derived automatically (e.g. ``"rename"``
    → ``"Renamed"``). Pass ``past`` explicitly for irregular or special forms
    (e.g. ``past="Wrote"`` for ``"write"``).
    """
    if dry_run:
        return f"Would {action}"
    return past if past is not None else f"{action.capitalize()}d"


def _emit_error(json_output: bool, error: str, message: str, code: int = 1, **extra) -> None:
    if json_output:
        typer.echo(
            _json.dumps({"status": "error", "error": error, "message": message, **extra}, indent=2)
        )
    else:
        typer.echo(f"{error}: {message}")
    raise typer.Exit(code=code)


def _emit_conflict(json_output: bool, error: str, message: str, **extra) -> None:
    if json_output:
        typer.echo(
            _json.dumps(
                {"status": "conflict", "error": error, "message": message, **extra}, indent=2
            )
        )
    else:
        typer.echo(f"{error}: {message}")
    raise typer.Exit(code=2)


def _safe(fn: _F) -> _F:
    """Turn expected failures into structured exit-1 errors instead of tracebacks.

    Honors the agent contract: a missing/unreadable file, malformed BibTeX, or
    invalid argument is reported as ``{"status":"error",...}`` (or a plain line)
    with exit code 1. ``typer.Exit`` (including the exit-2 conflicts that
    commands raise deliberately) passes through untouched.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        json_output = bool(kwargs.get("json_output", False))
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except FileNotFoundError as exc:
            _emit_error(json_output, "FileNotFound", str(exc))
        except ParseError as exc:
            _emit_error(json_output, "ParseError", exc.message, line=exc.line)
        except ExternalModificationError as exc:
            _emit_conflict(
                json_output,
                "ExternalModification",
                str(exc),
                file=str(exc.path),
                options=[
                    {
                        "id": "reload",
                        "description": "Reload the file and retry the operation",
                    },
                    {
                        "id": "manual_review",
                        "description": "Review the on-disk changes before retrying",
                    },
                ],
            )
        except ValueError as exc:
            # By convention, operation modules raise ValueError to signal
            # invalid user-supplied data (bad field name, malformed key, etc.).
            # Programming errors should use a different exception type.
            _emit_error(json_output, "InvalidInput", str(exc))
        except OSError as exc:
            _emit_error(json_output, "IOError", str(exc))

    return wrapper


def _preview_or_commit(
    coll: Bibliography, dry_run: bool, backup: bool = False
) -> tuple[str, bool, int]:
    """Return ``(diff, modified, changed_entries)`` for a staged collection.

    In ``--dry-run`` mode this previews without writing; otherwise it commits
    (atomic write + re-parse validation) and reports the committed outcome.
    Pass ``backup=True`` to also leave a ``<file>.bak`` copy behind.
    """
    if dry_run:
        return coll.diff(), coll.is_modified, coll.changed_entries_count()
    result = coll.commit(backup=backup)
    return result.diff, result.modified, result.changed_entries


_BACKUP_OPTION = typer.Option(
    False,
    "--backup",
    help="Also write a <file>.bak copy before overwriting (off by default; "
    "writes are already atomic and re-parse-validated)",
)


def _finish_mod(
    file,
    action,
    coll: Bibliography,
    dry_run,
    diff,
    json_output,
    human,
    warnings=None,
    modified_entries: int | None = None,
    backup: bool = False,
    **details,
) -> None:
    """Preview/commit a bibliography and emit the standard modifying-command result.

    Every modifying command shares this envelope:
    ``status, action, file, dry_run, modified, modified_entries, warnings``, a
    structured ``plan`` (machine-readable per-entry/field changes), plus
    command-specific keys, and an optional ``diff`` when ``--diff`` is set.
    """
    # The plan must be read before commit, which refreshes the pristine baseline.
    plan = coll.change_plan()
    diff_text, modified, changed = _preview_or_commit(coll, dry_run, backup)
    if modified_entries is not None:
        changed = modified_entries
    result = {
        "status": "success",
        "action": action,
        "file": file,
        "dry_run": dry_run,
        "modified": modified,
        "modified_entries": changed,
        "warnings": warnings or [],
        "plan": plan,
        **details,
    }
    _emit(json_output, result, human, diff_text, diff)


def _metadata_cache_dir(file: str, cache_dir: str | None, online: bool) -> str | None:
    if cache_dir is not None:
        return cache_dir
    if not online:
        return None
    return str(Path(file).resolve().parent / ".pynakes-cache")


# --- read-only checks (single- or multi-file) ------------------------------


@dataclass
class CheckOutcome:
    """The result of running one read-only check over a single file.

    ``result`` is the historical per-file JSON envelope (emitted unchanged when
    a single file is given). ``human`` are the human-readable lines for that
    file. ``failed`` is whether the file trips a ``--strict`` gate. ``summary``
    contributes integer counters to the multi-file aggregate.
    """

    result: dict
    human: list[str]
    failed: bool = False
    summary: dict = field(default_factory=dict)


def _run_single_check(
    file: str,
    action: str,
    check_one: Callable[[str], CheckOutcome],
    json_output: bool,
    strict: bool,
) -> None:
    """Run a read-only check over a single file."""
    outcome = check_one(file)
    if json_output:
        typer.echo(_json.dumps(outcome.result, indent=2))
    else:
        for line in outcome.human:
            typer.echo(line)
    if strict and outcome.failed:
        raise typer.Exit(code=1)


def _run_multi_checks(
    files: list[str],
    action: str,
    check_one: Callable[[str], CheckOutcome],
    json_output: bool,
    strict: bool,
) -> None:
    """Run a read-only check over multiple files and emit an aggregate result."""
    results: list[dict] = []
    totals: dict = {}
    error_files = 0
    findings_failed = 0
    for path in files:
        try:
            outcome = check_one(path)
        except (FileNotFoundError, ParseError, OSError, ValueError) as exc:
            error_files += 1
            err = {
                "status": "error",
                "file": path,
                "error": type(exc).__name__,
                "message": getattr(exc, "message", str(exc)),
            }
            if isinstance(exc, ParseError):
                err["line"] = exc.line
            results.append(err)
            if not json_output:
                typer.echo(f"# {path}")
                typer.echo(f"  [error] {err['message']}")
        else:
            results.append(outcome.result)
            if outcome.failed:
                findings_failed += 1
            for key, value in outcome.summary.items():
                totals[key] = totals.get(key, 0) + value
            if not json_output:
                typer.echo(f"# {path}")
                for line in outcome.human:
                    typer.echo(line)

    failed_files = error_files + findings_failed
    aggregate = {
        "status": "error" if error_files else "success",
        "action": action,
        "strict": strict,
        "files": results,
        "summary": {"files": len(files), "failed_files": failed_files, **totals},
    }
    if json_output:
        typer.echo(_json.dumps(aggregate, indent=2))
    else:
        typer.echo(
            f"{len(files)} file(s) checked; {failed_files} with findings, {error_files} unreadable."
        )
    if error_files or (strict and findings_failed):
        raise typer.Exit(code=1)


def _run_checks(
    files: list[str],
    action: str,
    check_one: Callable[[str], CheckOutcome],
    json_output: bool,
    strict: bool,
) -> None:
    """Run a read-only check over one or more files and emit the result.

    A single file preserves the exact historical per-file envelope and human
    output (the documented, byte-stable contract). Multiple files emit an
    aggregate ``{status, action, strict, files: [...], summary}`` envelope, with
    each element the same per-file envelope (or a per-file error object).

    Exit code: ``1`` if any file could not be read/parsed, or — when
    ``--strict`` — if any file tripped its gate; otherwise ``0``.
    """
    if len(files) == 1:
        _run_single_check(files[0], action, check_one, json_output, strict)
    else:
        _run_multi_checks(files, action, check_one, json_output, strict)
