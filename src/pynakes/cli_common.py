"""Shared CLI output, error handling, and check orchestration."""

import functools
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import typer
from click.shell_completion import CompletionItem

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.io import save_text
from pynakes.model import QueryFilter
from pynakes.query import And, InSet, parse_query

_F = TypeVar("_F", bound=Callable)

# --- shared helpers --------------------------------------------------------

BIB_FILE_HELP = "Path to the .bib file (default: auto-detect single .bib in cwd)"


def is_auxiliary_bib_file(path: Path) -> bool:
    """Return whether *path* is a generated auxiliary bibliography."""
    return path.name.lower().endswith("notes.bib")


def bib_file_argument(help: str = BIB_FILE_HELP) -> typer.Argument:
    """Return the standard optional ``.bib`` positional argument."""
    return typer.Argument(None, help=help)


def bib_file_option(help: str = BIB_FILE_HELP) -> typer.Option:
    """Return the standard optional ``--file`` option for commands with other positionals."""
    return typer.Option(None, "--file", "-f", help=help)


def bib_candidates(directory: Path) -> list[Path]:
    """Return regular user-library ``.bib`` files in *directory*, name-sorted."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".bib" and not is_auxiliary_bib_file(path)
        ),
        key=lambda path: path.name.casefold(),
    )


def single_bib_file(directory: Path) -> Path | None:
    """Return the only regular ``.bib`` file in *directory*, if there is one."""
    candidates = bib_candidates(directory)
    return candidates[0] if len(candidates) == 1 else None


def missing_bib_message(candidates: list[Path]) -> str:
    """Return the standard omitted-library error message for *candidates*."""
    if not candidates:
        return "No *.bib file found in current directory; specify one as an argument"
    names = "  ".join(path.name for path in candidates)
    return f"Multiple *.bib files found; specify one as an argument:\n{names}"


def _resolve_input_bib(file: str | None, json_output: bool) -> str:
    """Return the input ``file`` path, auto-detecting when ``None``.

    When ``file`` is ``None``, scans the current directory for regular
    ``*.bib`` files. If exactly one is found, returns it. If none or multiple
    are found, emits an error (never returns).
    """
    if file is not None:
        return file
    candidates = bib_candidates(Path("."))
    if len(candidates) != 1:
        _emit_error(json_output, "InvalidInput", missing_bib_message(candidates))
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
        typer.echo(json.dumps(result, indent=2))
        return
    for line in human:
        typer.echo(line)
    if show_diff and diff_text:
        typer.echo("")
        typer.echo(diff_text)


def _entries(count: int) -> str:
    return "entry" if count == 1 else "entries"


# --- shared entry selection ------------------------------------------------

#: Brackets are escaped for Typer's Rich help renderer, which would otherwise
#: read them as console markup and drop them from the text.
WHERE_HELP = (
    "Select entries with the shared --where grammar: predicates joined by "
    "and/or/not, e.g. 'year >= 2025 and type in \\[article, inproceedings]'. "
    "Operators: contains, =, !=, >, >=, <, <=, in \\[..], matches, ~ (fuzzy), "
    "exists, missing. See `pynakes capabilities` for the full grammar."
)


KEY_HELP = (
    "Select entries by citation key: comma-separated, repeatable. Shorthand for "
    "--where 'key in \\[..]', and narrows a --where given alongside it."
)


def where_option(help: str = WHERE_HELP) -> typer.Option:
    """Return the shared ``--where`` entry-selector option.

    Every entry-addressable command takes the same option with the same grammar
    (:func:`pynakes.query.parse_query`), so a selector written for one command
    is valid for the others.
    """
    return typer.Option(None, "--where", help=help)


def key_option(help: str = KEY_HELP) -> typer.Option:
    """Return the shared ``--key`` citation-key selector option.

    Selecting one known reference is the common case, and spelling it
    ``--where 'key = smith2020'`` makes the grammar a toll on the simplest
    request. Every command that accepts ``--where`` accepts this too, so
    ``--key`` means "the citation key" across the whole CLI — naming the key to
    assign on the commands that create an entry (``ref add``, ``ref import``),
    and naming the keys to act on everywhere else.
    """
    return typer.Option(None, "--key", help=help)


def parse_key_selector(keys: list[str] | None) -> list[str]:
    """Split a repeated/comma-separated ``--key`` option into citation keys."""
    return [key for value in keys or [] for raw in value.split(",") if (key := raw.strip())]


def build_where_filter(
    where: str | None,
    *,
    keys: list[str] | None = None,
    cited_keys: Iterable[str] | None = None,
) -> QueryFilter:
    """Compile the ``--where`` / ``--key`` selectors, or ``None`` when both are unset.

    The two compose: ``--key`` contributes a ``key in [...]`` membership test
    that is ANDed with ``--where``, so passing both narrows rather than
    replaces. A malformed expression raises ``ValueError``, which :func:`_safe`
    renders as a structured exit-1 error (honoring ``--json``), so callers need
    no local handling.
    """
    selected = parse_key_selector(keys)
    if keys and not selected:
        # ``--key ,`` or ``--key ""`` asked for a selection and named nothing;
        # silently selecting every entry would be the worst reading of that.
        raise ValueError("--key needs at least one citation key")
    parsed = parse_query(where, cited_keys=cited_keys) if where is not None else None
    if not selected:
        return parsed
    membership = InSet(field="key", values=tuple(selected))
    return membership if parsed is None else And((parsed, membership))


@dataclass
class RunParams:
    """Consolidated CLI run parameters.

    Every modifying and file-creation command accepts the same four boolean
    flags (``--dry-run``, ``--diff``, ``--json``, ``--backup``).  This
    dataclass eliminates threading them individually through helper functions.
    """

    dry_run: bool = False
    diff: bool = False
    json_output: bool = False
    backup: bool = False


def _verb(action: str, params: RunParams, past: str | None = None) -> str:
    """Return ``"Would <action>"`` in dry-run mode, or the past-tense form otherwise.

    For regular verbs the past tense is derived automatically: a trailing ``e``
    takes ``d`` (``"rename"`` → ``"Renamed"``), otherwise ``ed`` is appended
    (``"add"`` → ``"Added"``, ``"convert"`` → ``"Converted"``). Pass ``past``
    explicitly for irregular forms or ones needing a doubled final consonant
    (e.g. ``past="Wrote"`` for ``"write"``, ``past="Tagged"`` for ``"tag"``).
    """
    if params.dry_run:
        return f"Would {action}"
    if past is not None:
        return past
    stem = action.capitalize()
    return f"{stem}d" if action.endswith("e") else f"{stem}ed"


def stdin_is_interactive() -> bool:
    """Return whether standard input is an interactive terminal.

    Commands that fall back to prompting (``ref add`` / ``ref edit`` with an
    under-specified invocation) use this to refuse rather than block or abort
    when run headless — piped, redirected, or driven by an agent.
    """
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _emit_error(json_output: bool, error: str, message: str, code: int = 1, **extra) -> None:
    if json_output:
        typer.echo(
            json.dumps({"status": "error", "error": error, "message": message, **extra}, indent=2)
        )
    else:
        typer.echo(f"{error}: {message}")
    raise typer.Exit(code=code)


def _emit_conflict(json_output: bool, error: str, message: str, **extra) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {"status": "conflict", "error": error, "message": message, **extra}, indent=2
            )
        )
    else:
        typer.echo(f"{error}: {message}")
    raise typer.Exit(code=2)


class InvalidInputError(ValueError):
    """Raised by operation modules to signal invalid user-supplied input.

    Distinguished from plain ``ValueError`` so that programming bugs (which
    also raise ``ValueError``) are not silently misreported as user-input
    errors by :func:`_safe`.  Operation modules should prefer this type for
    validation errors exposed through the CLI.
    """


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
        except InvalidInputError as exc:
            _emit_error(json_output, "InvalidInput", str(exc))
        except ValueError as exc:
            # By convention, operation modules raise ValueError to signal
            # invalid user-supplied data (bad field name, malformed key, etc.).
            # Programming errors should use InvalidInputError.
            _emit_error(json_output, "InvalidInput", str(exc))
        except OSError as exc:
            _emit_error(json_output, "IOError", str(exc))

    return wrapper


def _preview_or_commit(coll: Bibliography, params: RunParams) -> tuple[str, bool, int]:
    """Return ``(diff, modified, changed_entries)`` for a staged collection.

    In ``--dry-run`` mode this previews without writing; otherwise it commits
    (atomic write + re-parse validation) and reports the committed outcome.
    Use ``params.backup`` to also leave a ``<file>.bak`` copy behind.
    """
    if params.dry_run:
        return coll.diff(), coll.is_modified, coll.changed_entries_count()
    result = coll.commit(backup=params.backup)
    return result.diff, result.modified, result.changed_entries


_BACKUP_OPTION = typer.Option(
    False,
    "--backup",
    help="Also write a <file>.bak copy before overwriting (off by default; "
    "writes are already atomic and re-parse-validated)",
)


def _citekey_completer(ctx, incomplete):
    """Shell-completion callback yielding matching citation keys.

    Intended for use as ``param.shell_complete`` on citekey arguments.
    Auto-detects the ``.bib`` file from ``ctx.params`` or the current directory.

    Click/ShellComplete calls this with ``(ctx, incomplete)`` — see
    ``ShellComplete.get_completions``.
    """
    file = ctx.params.get("file") or ctx.params.get("bib_file")
    if file is None:
        candidate = single_bib_file(Path.cwd())
        if candidate is None:
            return []
        file = str(candidate)
    try:
        lib = parse_bib(Path(file).read_text(encoding="utf-8"))
        return [
            CompletionItem(key)
            for key in sorted(set(lib.entries.keys()))
            if incomplete.lower() in key.lower()
        ]
    except Exception:
        return []


def _bibfile_completer(ctx, incomplete):
    """Shell-completion callback for the ``.bib`` file positional argument.

    When a single ``.bib`` file can be auto-detected, this returns citekeys
    from that library (so the user can Tab complete citekeys without first
    filling in the file argument).  Otherwise it falls back to suggesting
    ``.bib`` filenames.
    """
    candidate = single_bib_file(Path.cwd())
    if candidate is not None:
        name = candidate.name
        items: list[CompletionItem] = []
        if incomplete.lower() in name.lower():
            items.append(CompletionItem(name))
        try:
            lib = parse_bib(candidate.read_text(encoding="utf-8"))
        except Exception:
            return items
        for key in sorted(set(lib.entries.keys())):
            if incomplete.lower() in key.lower():
                items.append(CompletionItem(key))
        return items
    try:
        return [
            CompletionItem(p.name)
            for p in bib_candidates(Path("."))
            if incomplete.lower() in p.name.lower()
        ]
    except Exception:
        return []


def _finish_mod(
    file,
    action,
    coll: Bibliography,
    params: RunParams,
    human,
    diff_text: str | None = None,
    warnings=None,
    modified_entries: int | None = None,
    **details,
) -> None:
    """Preview/commit a bibliography and emit the standard modifying-command result.

    Every modifying command shares this envelope:
    ``status, action, file, dry_run, modified, modified_entries, warnings``, a
    structured ``plan`` (machine-readable per-entry/field changes), plus
    command-specific keys, and an optional ``diff`` when ``--diff`` is set.

    When ``diff_text`` is provided it is used as-is (useful for commands that
    combine multiple diffs, e.g. ``keys rename``). Otherwise the diff is
    generated from the bibliography changes.
    """
    # The plan must be read before commit, which refreshes the pristine baseline.
    plan = coll.change_plan()
    if diff_text is None:
        diff_text, modified, changed = _preview_or_commit(coll, params)
    else:
        _, modified, changed = _preview_or_commit(coll, params)
    if modified_entries is not None:
        changed = modified_entries
    result = {
        "status": "success",
        "action": action,
        "file": file,
        "dry_run": params.dry_run,
        "modified": modified,
        "modified_entries": changed,
        "warnings": warnings or [],
        "plan": plan,
        **details,
    }
    _emit(params.json_output, result, human, diff_text, params.diff)


def _finish_create(
    params: RunParams,
    path: str,
    action: str,
    content: str,
    human: list[str],
    previous_content: str = "",
    backup: bool = False,
    warnings: list | None = None,
    **details,
) -> None:
    """Write a new file and emit the standard creation-command result.

    File-creation commands (``combine``, ``split``, ``used``, ``init``) share
    this envelope: ``status, action, file, dry_run, written, warnings``, plus
    command-specific keys, and an optional ``diff`` when ``--diff`` is set.
    """
    diff_text = generate_diff(previous_content, content, path) if params.diff else ""
    written = False
    if not params.dry_run:
        result = save_text(content, path, backup=backup)
        if not result.success:
            _emit_error(params.json_output, "IOError", result.error or f"Failed to write {path}")
        written = True

    payload = {
        "status": "success",
        "action": action,
        "file": path,
        "dry_run": params.dry_run,
        "written": written,
        "warnings": warnings or [],
        **details,
    }
    _emit(params.json_output, payload, human, diff_text, params.diff)


def _metadata_key_completer(ctx, incomplete):
    """Shell-completion callback yielding known metadata keys.

    Intended for use as ``param.shell_complete`` on the ``key`` argument of
    ``metadata set``. Suggests all keys known to either JabRef or pynakes.
    """
    from pynakes.metadata.jabref import JABREF_EXACT_KEYS, JABREF_PREFIX_KEYS
    from pynakes.metadata.schema import PYNAKES_EXACT_KEYS, PYNAKES_PREFIX_KEYS

    incomplete_lower = incomplete.lower()
    items: list[CompletionItem] = []
    for key in JABREF_EXACT_KEYS:
        if incomplete_lower in key.lower():
            items.append(CompletionItem(key))
    for key in PYNAKES_EXACT_KEYS:
        if incomplete_lower in key.lower():
            items.append(CompletionItem(key))
    for prefix in JABREF_PREFIX_KEYS:
        if incomplete_lower in prefix.lower():
            items.append(CompletionItem(prefix))
    for prefix in PYNAKES_PREFIX_KEYS:
        if incomplete_lower in prefix.lower():
            items.append(CompletionItem(prefix))
    return items


_CACHE_FILE_OPTION = typer.Option(
    None,
    "--cache-file",
    help="Keep provider responses in a reusable cache file at this path (safe to "
    "delete or .gitignore). Omit it and nothing is written to disk: responses "
    "are reused for this run only",
)

_CONCURRENCY_OPTION = typer.Option(
    8,
    "--concurrency",
    "-j",
    min=1,
    help="Number of provider lookups to run at once during an --online pass "
    "(result ordering and applied updates are unaffected)",
)


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
        typer.echo(json.dumps(outcome.result, indent=2))
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
        typer.echo(json.dumps(aggregate, indent=2))
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
