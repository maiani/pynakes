"""Read-only checks over one or more libraries: ``lint``, ``verify``, and the ``check`` commands.

Each check runs over every file it is given and gates on ``--strict``: exit 1
when any file has findings that fail the check. (``--strict`` is the gate of a
command that is read-only anyway; ``--check`` is the check mode of a transform
such as ``format``, which then writes nothing.) A single file emits that file's
envelope; several emit an aggregate whose ``files`` holds one per-file envelope
(or a per-file error object) each.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import typer

from pynakes.bibtex_parser import ParseError
from pynakes.cli_common import _emit_json
from pynakes.cli_errors import ErrorCode


@dataclass
class CheckOutcome:
    """The result of running one read-only check over a single file.

    ``result`` is the per-file JSON envelope (emitted as is when a single file
    is given). ``human`` are the human-readable lines for that file. ``failed``
    is whether the file fails the ``--strict`` gate. ``summary`` contributes
    integer counters to the multi-file aggregate.
    """

    result: dict
    human: list[str]
    failed: bool = False
    summary: dict = field(default_factory=dict)


def error_code_for(exc: Exception) -> ErrorCode:
    """Return the catalogued code for one file's failure in a multi-file run."""
    if isinstance(exc, ParseError):
        return ErrorCode.PARSE_ERROR
    if isinstance(exc, FileNotFoundError):
        return ErrorCode.FILE_NOT_FOUND
    if isinstance(exc, OSError):
        return ErrorCode.IO_ERROR
    return ErrorCode.INVALID_INPUT


def _file_result(outcome: CheckOutcome, strict: bool) -> dict:
    """Complete a per-file envelope with the keys every check result carries."""
    result = dict(outcome.result)
    result.setdefault("warnings", [])
    result["strict"] = strict
    return result


def _run_single_check(
    file: str, check_one: Callable[[str], CheckOutcome], json_output: bool, check: bool
) -> None:
    """Run a read-only check over a single file."""
    outcome = check_one(file)
    if json_output:
        _emit_json(_file_result(outcome, check))
    else:
        for line in outcome.human:
            typer.echo(line)
    if check and outcome.failed:
        raise typer.Exit(code=1)


def _run_multi_checks(
    files: list[str],
    action: str,
    check_one: Callable[[str], CheckOutcome],
    json_output: bool,
    check: bool,
) -> None:
    """Run a read-only check over several files and emit an aggregate result."""
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
                "error": error_code_for(exc).value,
                "message": getattr(exc, "message", str(exc)),
            }
            if isinstance(exc, ParseError):
                err["line"] = exc.line
            results.append(err)
            if not json_output:
                typer.echo(f"# {path}")
                typer.echo(f"  [error] {err['message']}")
        else:
            results.append(_file_result(outcome, check))
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
        "strict": check,
        "warnings": [],
        "files": results,
        "summary": {"files": len(files), "failed_files": failed_files, **totals},
    }
    if json_output:
        _emit_json(aggregate)
    else:
        typer.echo(
            f"{len(files)} file(s) checked; {failed_files} with findings, {error_files} unreadable."
        )
    if error_files or (check and findings_failed):
        raise typer.Exit(code=1)


def _run_checks(
    files: list[str],
    action: str,
    check_one: Callable[[str], CheckOutcome],
    json_output: bool,
    check: bool,
) -> None:
    """Run a read-only check over one or more files and emit the result.

    A single file emits its per-file envelope. Several emit an aggregate
    ``{status, action, strict, warnings, files: [...], summary}`` envelope, with
    each element of ``files`` the same per-file envelope (or a per-file error
    object carrying a catalogued ``error`` code).

    Exit code: ``1`` if any file could not be read or parsed, or — under
    ``--strict`` — if any file failed the check; otherwise ``0``.
    """
    if len(files) == 1:
        _run_single_check(files[0], check_one, json_output, check)
    else:
        _run_multi_checks(files, action, check_one, json_output, check)


#: Help text for the shared gate flag, phrased per command by its caller.
STRICT_HELP = "Exit 1 when {what} (for CI and pre-commit gating)"


def strict_option(what: str) -> Any:
    """Return the shared ``--strict`` gate option: exit 1 when *what*."""
    return typer.Option(False, "--strict", help=STRICT_HELP.format(what=what))
