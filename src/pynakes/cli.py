"""Command-line interface for pynakes."""

import functools
import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import typer

from pynakes import dedupe as dedupe_ops
from pynakes import doi as doi_ops
from pynakes import fields as fields_ops
from pynakes import files as files_ops
from pynakes import groups as groups_ops
from pynakes import journals as journals_ops
from pynakes import keys as keys_ops
from pynakes import metadata as metadata_ops
from pynakes import normalize as normalize_ops
from pynakes.bibtex_parser import ParseError
from pynakes.capabilities import get_capabilities
from pynakes.diff import generate_diff
from pynakes.engine import Collection, ExternalModificationError
from pynakes.io import load_bib, save_bib, save_plain_text
from pynakes.lint import lint as lint_lib
from pynakes.usage import (
    analyze_usage,
    collect_cited_keys,
    extract_keys_from_tex,
    iter_tex_files,
    rename_citation_key_in_tex,
    subset_library,
    tag_with_group,
    tag_with_keyword,
    tex_sources_from_metadata,
)

app = typer.Typer(help="Agent-friendly BibTeX library management tool")
groups_app = typer.Typer(help="Manage entry groups")
keys_app = typer.Typer(help="Generate and check citation keys")
fields_app = typer.Typer(help="Edit fields (rename, move, append, clear, protect titles)")
files_app = typer.Typer(help="Validate JabRef linked files")
doi_app = typer.Typer(help="Import references by DOI")
dedupe_app = typer.Typer(help="Detect and merge duplicate works")
journals_app = typer.Typer(help="Abbreviate, expand, and check journal titles")
metadata_app = typer.Typer(help="Inspect and update JabRef library metadata")
app.add_typer(groups_app, name="groups")
app.add_typer(keys_app, name="keys")
app.add_typer(fields_app, name="fields")
app.add_typer(files_app, name="files")
app.add_typer(doi_app, name="doi")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(journals_app, name="journals")
app.add_typer(metadata_app, name="metadata")


# --- shared helpers --------------------------------------------------------


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


def _safe(fn):
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
            _emit_error(json_output, "InvalidInput", str(exc))
        except OSError as exc:
            _emit_error(json_output, "IOError", str(exc))

    return wrapper


def _preview_or_commit(
    coll: Collection, dry_run: bool, backup: bool = False
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
    coll: Collection,
    dry_run,
    diff,
    json_output,
    human,
    warnings=None,
    modified_entries: int | None = None,
    backup: bool = False,
    **details,
) -> None:
    """Preview/commit a collection and emit the standard modifying-command result.

    Every modifying command shares this envelope:
    ``status, action, file, dry_run, modified, modified_entries, warnings`` plus
    command-specific keys, and an optional ``diff`` when ``--diff`` is set.
    """
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
        **details,
    }
    _emit(json_output, result, human, diff_text, diff)


def _metadata_cache_dir(file: str, cache_dir: Optional[str], online: bool) -> str | None:
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
        outcome = check_one(files[0])
        if json_output:
            typer.echo(_json.dumps(outcome.result, indent=2))
        else:
            for line in outcome.human:
                typer.echo(line)
        if strict and outcome.failed:
            raise typer.Exit(code=1)
        return

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


# --- inspect ---------------------------------------------------------------


@app.command()
@_safe
def inspect(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a .bib file structure."""
    lib = load_bib(file)
    issues = lint_lib(lib)
    duplicates = lib.entries.duplicate_keys()

    if json_output:
        result = {
            "status": "success",
            "action": "inspect",
            "file": file,
            "encoding": lib.encoding,
            "line_ending": "crlf" if lib.line_ending == "\r\n" else "lf",
            "entry_count": len(lib.entries),
            "entries": [
                {"key": e.key, "type": e.type, "fields": dict(e.fields)}
                for e in lib.entries.values()
            ],
            "jabref_metadata": {
                "values": dict(lib.jabref_metadata),
                "blocks": [block.to_dict() for block in lib.jabref_metadata_blocks],
            },
            "pynakes_metadata": {
                "values": dict(lib.pynakes_metadata),
                "blocks": [block.to_dict() for block in lib.pynakes_metadata_blocks],
            },
            "duplicate_keys": duplicates,
            "issues": [i.to_dict() for i in issues],
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    le = "CRLF" if lib.line_ending == "\r\n" else "LF"
    typer.echo(f"{file}: {len(lib.entries)} {_entries(len(lib.entries))} ({lib.encoding}, {le})")
    for entry in lib.entries.values():
        typer.echo(f"  @{entry.type}{{{entry.key}}}  ({len(entry.fields)} fields)")
    if duplicates:
        typer.echo(f"Duplicate keys: {', '.join(f'{k} ×{n}' for k, n in duplicates.items())}")
    typer.echo(f"Issues: {len(issues)}")


# --- metadata --------------------------------------------------------------


@metadata_app.command("list")
@_safe
def metadata_list(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List top-level metadata blocks (both jabref-meta and pynakes-meta)."""
    lib = load_bib(file)
    all_blocks = lib.metadata_blocks

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "status": "success",
                    "action": "metadata_list",
                    "file": file,
                    "metadata": {
                        "values": dict(lib.jabref_metadata),
                        "blocks": [b.to_dict() for b in lib.jabref_metadata_blocks],
                    },
                    "pynakes_metadata": {
                        "values": dict(lib.pynakes_metadata),
                        "blocks": [b.to_dict() for b in lib.pynakes_metadata_blocks],
                    },
                    "effective": dict(lib.metadata),
                },
                indent=2,
            )
        )
        return

    if not all_blocks:
        typer.echo(f"{file}: no metadata found.")
        return
    for block in all_blocks:
        marker = "known" if block.known else "unknown"
        typer.echo(
            f"  [{block.namespace}:{marker}:{block.category}] "
            f"{block.key} = {block.normalized_value}"
        )


@metadata_app.command("set")
@_safe
def metadata_set(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Metadata key"),
    value: str = typer.Argument(..., help="Metadata value"),
    namespace: Optional[str] = typer.Option(
        None,
        "--namespace",
        help="Target comment: jabref or pynakes. Default: auto (JabRef-native keys "
        "→ jabref-meta, everything else → pynakes-meta)",
    ),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="Allow writing an unrecognized key into jabref-meta"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Set one top-level metadata block (jabref-meta or pynakes-meta)."""
    if namespace is not None and namespace not in {"jabref", "pynakes"}:
        _emit_error(
            json_output,
            "InvalidNamespace",
            f"Invalid namespace {namespace!r}; expected jabref or pynakes",
        )
    coll = Collection.open(file)
    try:
        update = coll.set_metadata(key, value, namespace=namespace, allow_unknown=allow_unknown)
    except metadata_ops.DuplicateJabRefMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateJabRefMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=[
                {
                    "id": "manual_edit",
                    "description": "Resolve duplicate metadata blocks manually, then retry",
                }
            ],
        )

    verb = "Would set" if dry_run else "Set"
    _finish_mod(
        file,
        "metadata_set",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {update.namespace}-meta {update.key!r}."],
        modified_entries=0,
        key=update.key,
        value=update.value.rstrip(";").strip(),
        created=update.created,
        namespace=update.namespace,
    )


# --- lint ------------------------------------------------------------------


def _lint_one(file: str) -> CheckOutcome:
    lib = load_bib(file)
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
    # Only errors gate a --strict build; lint warnings (e.g. a missing DOI) are
    # advisory. (verify --strict is broader because its warnings flag integrity
    # mismatches against authoritative metadata.)
    return CheckOutcome(
        result=result,
        human=human,
        failed=errors > 0,
        summary={"issues": len(issues), "errors": errors, "warnings": warnings},
    )


@app.command()
@_safe
def lint(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any errors are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues (accepts multiple files for CI gating)."""
    _run_checks(files, "lint", _lint_one, json_output, strict)


# --- files -----------------------------------------------------------------


def _files_check_one(file: str, root: Optional[list[str]]) -> CheckOutcome:
    lib = load_bib(file)
    report = files_ops.check_linked_files(lib, file, root)
    result = {
        "status": "success",
        "action": "files_check",
        "file": file,
        **report.to_dict(),
    }
    human = [
        f"{file}: checked {report.checked} linked file(s); "
        f"ok={report.ok}, missing={report.missing}, "
        f"wrong_type={report.wrong_type}, unresolved={report.unresolved}."
    ]
    human += [
        f"  [{issue.status}] {issue.entry_key}[{issue.index}]: {issue.path}"
        for issue in report.issues
    ]
    bad = report.missing + report.wrong_type + report.unresolved
    return CheckOutcome(
        result=result,
        human=human,
        failed=bad > 0,
        summary={
            "checked": report.checked,
            "ok": report.ok,
            "missing": report.missing,
            "wrong_type": report.wrong_type,
            "unresolved": report.unresolved,
        },
    )


@files_app.command("check")
@_safe
def files_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    root: Optional[list[str]] = typer.Option(
        None,
        "--root",
        help="Additional directory to resolve relative linked-file paths; can be repeated",
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if any linked file is missing or wrong-type"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate JabRef linked files (accepts multiple files for CI gating)."""
    _run_checks(files, "files_check", lambda f: _files_check_one(f, root), json_output, strict)


# --- doi -------------------------------------------------------------------


@doi_app.command("import")
@_safe
def doi_import(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    doi: str = typer.Argument(..., help="DOI or DOI URL to import"),
    key: Optional[str] = typer.Option(None, "--key", help="Citation key to use"),
    key_source: str = typer.Option(
        "generated",
        "--key-source",
        help="Citation key source when --key is absent: generated or provider",
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Import even if the DOI already exists"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Import a reference from a DOI."""
    if key_source not in doi_ops.KEY_SOURCES:
        _emit_error(
            json_output,
            "InvalidKeySource",
            f"Invalid key source {key_source!r}; expected one of: "
            f"{', '.join(sorted(doi_ops.KEY_SOURCES))}",
        )

    try:
        coll = Collection.open(file)
        entry = coll.import_doi(
            doi,
            key=key,
            key_source=key_source,
            allow_duplicate_doi=allow_duplicate,
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidDOI", str(exc))
    except doi_ops.DuplicateDOIError as exc:
        if json_output:
            typer.echo(
                _json.dumps(
                    {
                        "status": "conflict",
                        "error": "DuplicateDOI",
                        "message": str(exc),
                        "doi": exc.doi,
                        "existing_keys": exc.keys,
                        "options": [
                            {
                                "id": "keep_existing",
                                "description": "Do not import a duplicate reference",
                            },
                            {
                                "id": "allow_duplicate",
                                "description": "Retry with --allow-duplicate",
                            },
                        ],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(f"DuplicateDOI: {exc}")
            typer.echo("Retry with --allow-duplicate to import another copy.")
        raise typer.Exit(code=2) from exc
    except doi_ops.CitationKeyConflictError as exc:
        _emit_conflict(
            json_output,
            "CitationKeyConflict",
            str(exc),
            key=exc.key,
            options=[
                {"id": "choose_key", "description": "Retry with a different --key"},
                {"id": "auto_key", "description": "Retry without --key"},
            ],
        )
    except doi_ops.DOIImportError as exc:
        _emit_error(json_output, "DOIImportError", str(exc))

    verb = "Would import" if dry_run else "Imported"
    _finish_mod(
        file,
        "doi_import",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} DOI {entry.fields['doi']} as {entry.key}."],
        doi=entry.fields["doi"],
        key=entry.key,
        key_source="user" if key else key_source,
        entry_type=entry.type,
    )


# --- dedupe ----------------------------------------------------------------


def _dedupe_check_one(file: str) -> CheckOutcome:
    coll = Collection.open(file)
    clusters = coll.dedupe_check()
    duplicate_entries = sum(len(cluster.entries) for cluster in clusters)
    result = {
        "status": "success",
        "action": "dedupe_check",
        "file": file,
        "has_duplicates": bool(clusters),
        "cluster_count": len(clusters),
        "duplicate_entries": duplicate_entries,
        "clusters": [cluster.to_dict() for cluster in clusters],
    }
    if not clusters:
        human = [f"{file}: no duplicate works found."]
    else:
        human = [f"{file}: {len(clusters)} duplicate work cluster(s)."]
        for cluster in clusters:
            identity = f"{cluster.identity.kind}:{cluster.identity.value}"
            keys = ", ".join(e.key for e in cluster.entries)
            human.append(f"  [{cluster.reason}] {identity}: {keys}")
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(clusters),
        summary={"clusters": len(clusters), "duplicate_entries": duplicate_entries},
    )


@dedupe_app.command("check")
@_safe
def dedupe_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if duplicate works are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate works by DOI/arXiv/other IDs and fuzzy title matches."""
    _run_checks(files, "dedupe_check", _dedupe_check_one, json_output, strict)


@dedupe_app.command("merge")
@_safe
def dedupe_merge(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively merge duplicate works into their first entry."""
    coll = Collection.open(file)
    try:
        report = coll.dedupe_merge()
    except dedupe_ops.DedupeConflictError as exc:
        _emit_conflict(
            json_output,
            "DedupeConflict",
            str(exc),
            conflicts=[conflict.to_dict() for conflict in exc.conflicts],
            clusters=[cluster.to_dict() for cluster in exc.clusters],
            options=[
                {
                    "id": "manual_edit",
                    "description": "Resolve the conflicting field values manually, then retry",
                },
                {
                    "id": "keep_duplicates",
                    "description": "Leave these entries as separate records",
                },
            ],
        )

    verb = "Would merge" if dry_run else "Merged"
    human = [
        f"{verb} {report.merged_clusters} duplicate work cluster(s).",
        f"  removed_entries={report.removed_entry_count}, field_changes={report.field_changes}",
    ]
    _finish_mod(
        file,
        "dedupe_merge",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        modified_entries=report.modified_entries,
        **report.to_dict(),
    )


# --- integrity / enrichment -------------------------------------------------


def _verify_one(file: str, online: bool, cache_dir: Optional[str], strict: bool) -> CheckOutcome:
    coll = Collection.open(file)
    report = coll.verify(online=online, cache_dir=_metadata_cache_dir(file, cache_dir, online))
    result = {
        "status": "success",
        "action": "verify",
        "file": file,
        "online": online,
        "strict": strict,
        **report.to_dict(),
    }
    human = [
        f"{file}: verified {report.checked} DOI-backed {_entries(report.checked)}.",
        f"  errors={report.errors}, warnings={report.warnings}, infos={report.infos}",
    ]
    human += [f"  [{issue.severity}] {issue.key}: {issue.message}" for issue in report.issues]
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(report.errors or report.warnings),
        summary={
            "checked": report.checked,
            "errors": report.errors,
            "warnings": report.warnings,
            "infos": report.infos,
        },
    )


@app.command()
@_safe
def verify(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    online: bool = typer.Option(
        False, "--online", help="Fetch DOI provider metadata; otherwise only local checks run"
    ),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if warnings or errors are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Verify DOI-backed entries against authoritative metadata (accepts multiple files)."""
    _run_checks(
        files,
        "verify",
        lambda f: _verify_one(f, online, cache_dir, strict),
        json_output,
        strict,
    )


@app.command()
@_safe
def enrich(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    online: bool = typer.Option(
        False,
        "--online",
        help="Fetch DOI provider metadata; otherwise only local DOI URLs are used",
    ),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively fill missing DOI/date/identifier metadata."""
    coll = Collection.open(file)
    report = coll.enrich(online=online, cache_dir=_metadata_cache_dir(file, cache_dir, online))
    verb = "Would enrich" if dry_run else "Enriched"
    human = [
        f"{verb} {report.changed_entries} {_entries(report.changed_entries)}.",
        f"  field_updates={report.changed_fields}",
    ]
    _finish_mod(
        file,
        "enrich",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=report.warnings,
        **report.to_dict(),
    )


@app.command()
@_safe
def published(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    online: bool = typer.Option(
        False, "--online", help="Fetch preprint provider metadata; otherwise only local checks run"
    ),
    apply: bool = typer.Option(False, "--apply", help="Apply safe published DOI/journal updates"),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report preprints that have published-version metadata available."""
    coll = Collection.open(file)
    cache = _metadata_cache_dir(file, cache_dir, online)
    if apply:
        report = coll.apply_published(online=online, cache_dir=cache)
        verb = "Would apply" if dry_run else "Applied"
        human = [
            f"{verb} published metadata to {report.changed_entries} {_entries(report.changed_entries)}.",
            f"  checked={report.checked}, published={report.published}",
        ]
        _finish_mod(
            file,
            "published_apply",
            coll,
            dry_run,
            diff,
            json_output,
            human,
            warnings=report.warnings,
            **report.to_dict(),
        )
        return

    report = coll.published_check(online=online, cache_dir=cache)
    result = {
        "status": "success",
        "action": "published",
        "file": file,
        "online": online,
        "warnings": report.warnings,
        **report.to_dict(),
    }
    human = [
        f"{file}: checked {report.checked} preprint {_entries(report.checked)}.",
        f"  published={report.published}",
    ]
    _emit(json_output, result, human)


# --- groups ----------------------------------------------------------------


@groups_app.command("list")
@_safe
def groups_list(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all groups and their members."""
    lib = load_bib(file)
    names = groups_ops.list_groups(lib)
    members = {g: groups_ops.list_entries_in_group(lib, g) for g in names}

    if json_output:
        typer.echo(
            _json.dumps(
                {"status": "success", "action": "groups_list", "file": file, "groups": members},
                indent=2,
            )
        )
        return

    if not names:
        typer.echo(f"{file}: no groups found.")
        return
    for name in names:
        typer.echo(f"{name} ({len(members[name])}): {', '.join(members[name])}")


def _require_key(lib, key: str, json_output: bool) -> None:
    if key not in lib.entries:
        _emit_error(json_output, "KeyNotFound", f"No entry with key {key!r} in the library")


@groups_app.command("add-entry")
@_safe
def groups_add_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group."""
    coll = Collection.open(file)
    _require_key(coll.lib, key, json_output)
    count = coll.add_to_group(key, group)
    verb = "Would add" if dry_run else "Added"
    _finish_mod(
        file,
        "groups_add_entry",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {key} to group {group!r} ({count} {_entries(count)} changed)."],
        key=key,
        group=group,
    )


@groups_app.command("remove-entry")
@_safe
def groups_remove_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to remove"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove an entry from a group."""
    coll = Collection.open(file)
    _require_key(coll.lib, key, json_output)
    count = coll.remove_from_group(key, group)
    verb = "Would remove" if dry_run else "Removed"
    _finish_mod(
        file,
        "groups_remove_entry",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {key} from group {group!r} ({count} {_entries(count)} changed)."],
        key=key,
        group=group,
    )


# --- keys ------------------------------------------------------------------


def _keys_check_one(file: str) -> CheckOutcome:
    lib = load_bib(file)
    duplicates = keys_ops.duplicate_key_counts(lib)
    result = {
        "status": "success",
        "action": "keys_check",
        "file": file,
        "has_duplicates": bool(duplicates),
        "duplicate_keys": duplicates,
    }
    if not duplicates:
        human = [f"{file}: all citation keys are unique."]
    else:
        human = [f"  {key}: appears {count} times" for key, count in duplicates.items()]
        human.append(f"{len(duplicates)} duplicated key(s).")
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(duplicates),
        summary={"duplicate_keys": len(duplicates)},
    )


@keys_app.command("check")
@_safe
def keys_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if duplicate keys are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate citation keys (accepts multiple files for CI gating)."""
    _run_checks(files, "keys_check", _keys_check_one, json_output, strict)


def _rename_payload(renames: list[tuple[str, str]]) -> dict:
    return {"renames": [{"old": o, "new": n} for o, n in renames]}


@keys_app.command("generate")
@_safe
def keys_generate(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Regenerate all citation keys from entry metadata (AuthorYearTitle)."""
    coll = Collection.open(file)
    renames = coll.generate_keys()
    verb = "Would rename" if dry_run else "Renamed"
    human = [f"{verb} {len(renames)} {_entries(len(renames))}."]
    human += [f"  {old} -> {new}" for old, new in renames]
    _finish_mod(
        file,
        "keys_generate",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        **_rename_payload(renames),
    )


@keys_app.command("repair")
@_safe
def keys_repair(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename duplicate citation keys so every key is unique."""
    coll = Collection.open(file)
    renames = coll.repair_keys()
    verb = "Would repair" if dry_run else "Repaired"
    human = [f"{verb} {len(renames)} duplicate key(s)."]
    human += [f"  {old} -> {new}" for old, new in renames]

    # A repaired key still exists on the first (kept) entry, so a TeX
    # `\cite{key}` is now ambiguous rather than simply renamed — rewriting it
    # would be a guess. Instead, warn when a linked source cites a repaired key.
    warnings = _repaired_citation_warnings(coll.lib, file, renames)
    if warnings:
        human.append(f"  {len(warnings)} citation(s) now ambiguous in linked TeX sources.")

    _finish_mod(
        file,
        "keys_repair",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=warnings,
        **_rename_payload(renames),
    )


def _repaired_citation_warnings(lib, file: str, renames: list[tuple[str, str]]) -> list[dict]:
    """Flag linked-TeX citations of keys that ``keys repair`` made ambiguous."""
    if not renames:
        return []
    sources = tex_sources_from_metadata(lib, Path(file).parent)
    if not sources:
        return []
    repaired = {old for old, _ in renames}
    warnings: list[dict] = []
    for path in iter_tex_files(sources):
        try:
            cited = set(extract_keys_from_tex(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        for key in sorted(repaired & cited):
            warnings.append(
                {
                    "type": "ambiguous_citation",
                    "message": (
                        f"{path.name} cites {key!r}, which was duplicated and repaired; "
                        "review the citation and point it at the intended entry"
                    ),
                    "key": key,
                    "source": str(path),
                }
            )
    return warnings


@keys_app.command("rename")
@_safe
def keys_rename(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    old: str = typer.Argument(..., help="Existing citation key"),
    new: str = typer.Argument(..., help="New citation key"),
    sources: Optional[list[str]] = typer.Argument(
        None,
        help="One or more .tex files or directories whose citations should be updated "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename one citation key in a .bib file and matching TeX citations."""
    coll = Collection.open(file)
    keys_ops.validate_key(old)
    keys_ops.validate_key(new)

    matches = coll.lib.entries.get_all(old)
    if not matches:
        _emit_error(json_output, "KeyNotFound", f"No entry with key {old!r} in the library")
    if len(matches) > 1:
        _emit_conflict(
            json_output,
            "DuplicateCitationKey",
            f"Cannot rename duplicated key {old!r}; repair duplicates first",
            key=old,
            count=len(matches),
            options=[
                {
                    "id": "repair_duplicates",
                    "description": "Run keys repair first, then retry with the unique key",
                }
            ],
        )
    if old != new and new in coll.lib.entries:
        _emit_conflict(
            json_output,
            "CitationKeyConflict",
            f"Cannot rename {old!r} to {new!r}: target key already exists",
            key=new,
            options=[
                {"id": "choose_key", "description": "Retry with a different new key"},
                {
                    "id": "repair_duplicates",
                    "description": "Run keys repair if the target is duplicated",
                },
            ],
        )

    bib_changed = coll.rename_key(old, new)
    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(file).parent)
    )
    tex_files = iter_tex_files(resolved_sources)
    if not tex_files:
        _emit_error(
            json_output,
            "NoTeXSources",
            "No .tex files found in the provided sources or the library's 'tex-sources' metadata",
        )
    if not dry_run and coll.externally_changed():
        if coll.path is None:
            raise ValueError("rename requires a bound .bib file")
        raise ExternalModificationError(coll.path)

    source_changes = []
    source_diff_parts = []
    total_source_occurrences = 0
    for path in tex_files:
        before = path.read_text(encoding="utf-8", errors="replace")
        after, occurrences = rename_citation_key_in_tex(before, old, new)
        modified = before != after
        total_source_occurrences += occurrences
        if modified:
            source_diff_parts.append(generate_diff(before, after, path.name))
            if not dry_run:
                saved = save_plain_text(after, str(path), encoding="utf-8")
                if not saved.success:
                    raise OSError(saved.error or f"Could not write {path}")
        source_changes.append(
            {
                "path": str(path),
                "modified": modified,
                "occurrences": occurrences,
            }
        )

    bib_diff, bib_modified, changed_entries = _preview_or_commit(coll, dry_run)

    diff_text = "\n".join(part for part in [bib_diff, *source_diff_parts] if part)
    source_modified = any(change["modified"] for change in source_changes)
    modified = bib_modified or source_modified

    verb = "Would rename" if dry_run else "Renamed"
    human = [
        f"{verb} citation key {old!r} to {new!r}.",
        f"  bib entries changed={bib_changed}, TeX citations changed={total_source_occurrences}",
    ]
    _emit(
        json_output,
        {
            "status": "success",
            "action": "keys_rename",
            "file": file,
            "dry_run": dry_run,
            "modified": modified,
            "modified_entries": changed_entries,
            "warnings": [],
            "old": old,
            "new": new,
            "source_occurrences": total_source_occurrences,
            "sources": source_changes,
        },
        human,
        diff_text,
        diff,
    )


# --- fields ----------------------------------------------------------------


def _build_filter(where: Optional[str]):
    # A bad expression raises ValueError, which @_safe renders as a structured
    # exit-1 error (honoring --json), so no local handling is needed here.
    if where is None:
        return None
    return fields_ops.parse_query(where)


def _run_field_op(file, action, op, dry_run, diff, json_output, details, verb):
    coll = Collection.open(file)
    count = op(coll)
    _finish_mod(
        file,
        action,
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} ({count} {_entries(count)} changed)."],
        **details,
    )


@fields_app.command("rename")
@_safe
def fields_rename(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_rename",
        lambda coll: coll.rename_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would rename' if dry_run else 'Renamed'} field {old!r} to {new!r}",
    )


@fields_app.command("move")
@_safe
def fields_move(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field to a new name, skipping entries that already have the target."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_move",
        lambda coll: coll.move_field(old, new, flt),
        dry_run,
        diff,
        json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would move' if dry_run else 'Moved'} field {old!r} to {new!r}",
    )


@fields_app.command("append")
@_safe
def fields_append(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a (comma-delimited) field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_append",
        lambda coll: coll.append_field(field, value, flt),
        dry_run,
        diff,
        json_output,
        {"field": field, "value": value, "where": where},
        f"{'Would append' if dry_run else 'Appended'} {value!r} to field {field!r}",
    )


@fields_app.command("clear")
@_safe
def fields_clear(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from entries."""
    flt = _build_filter(where)
    _run_field_op(
        file,
        "fields_clear",
        lambda coll: coll.clear_field(field, flt),
        dry_run,
        diff,
        json_output,
        {"field": field, "where": where},
        f"{'Would clear' if dry_run else 'Cleared'} field {field!r}",
    )


@fields_app.command("protect-title")
@_safe
def fields_protect_title(
    file: str = typer.Argument(...),
    field: str = typer.Option("title", "--field", help="Title-like field to protect"),
    term: Optional[list[str]] = typer.Option(
        None, "--term", help="Additional exact term to brace-protect"
    ),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Brace-protect capitalization-sensitive tokens in title-like fields."""
    flt = _build_filter(where)
    terms = term or []
    _run_field_op(
        file,
        "fields_protect_title",
        lambda coll: coll.protect_title(field, flt, terms),
        dry_run,
        diff,
        json_output,
        {"field": field, "terms": terms, "where": where},
        f"{'Would protect' if dry_run else 'Protected'} capitalization in field {field!r}",
    )


# --- normalize -------------------------------------------------------------


def _optional_bool(value: str) -> bool | None:
    normalized = value.lower()
    if normalized == "metadata":
        return None
    if normalized in {"on", "true", "yes", "1"}:
        return True
    if normalized in {"off", "false", "no", "0"}:
        return False
    raise ValueError("expected metadata, on, or off")


@app.command()
@_safe
def normalize(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    title_protection: str = typer.Option(
        "metadata",
        "--title-protection",
        help="metadata, on, or off",
    ),
    title_field: Optional[list[str]] = typer.Option(
        None,
        "--title-field",
        help="Title-like field to brace-protect; can be repeated",
    ),
    term: Optional[list[str]] = typer.Option(
        None,
        "--term",
        help="Additional exact title term to brace-protect; can be repeated",
    ),
    author_style: str = typer.Option(
        "metadata",
        "--author-style",
        help="metadata, jabref, conservative, bibtex, biblatex, or none",
    ),
    journal_style: str = typer.Option(
        "metadata",
        "--journal-style",
        help="metadata, abbreviated, full, or none (default: no change unless metadata sets it)",
    ),
    journal_table: Optional[str] = typer.Option(
        None,
        "--journal-table",
        help="CSV/TSV with title, abbreviation, and optional ISSN mappings",
    ),
    ltwa_table: Optional[str] = typer.Option(
        None,
        "--ltwa-table",
        help="CSV/TSV LTWA word abbreviation table",
    ),
    doi_normalization: str = typer.Option(
        "metadata",
        "--doi-normalization",
        help="metadata, on, or off",
    ),
    metadata_formatting: str = typer.Option(
        "metadata",
        "--metadata-formatting",
        help="Consolidate jabref-meta to the file end, sorted (metadata, on, or off)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Run the standard bibliography normalization routine."""
    try:
        options = normalize_ops.NormalizeOptions(
            protect_titles=_optional_bool(title_protection),
            title_fields=title_field,
            protected_terms=term,
            author_style=author_style,
            journal_style=journal_style,
            journal_table=journal_table,
            ltwa_table=ltwa_table,
            normalize_dois=_optional_bool(doi_normalization),
            format_metadata=_optional_bool(metadata_formatting),
        )
        coll = Collection.open(file)
        report = coll.normalize(options)
    except ValueError as exc:
        _emit_error(json_output, "InvalidNormalizeOption", str(exc))

    verb = "Would normalize" if dry_run else "Normalized"
    human = [
        f"{verb} entries.",
        "  "
        f"titles={sum(report.title_fields.values())}, "
        f"authors={report.authors}, journals={report.journals}, dois={report.dois}",
    ]
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "normalize",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=report.warnings,
        operations=report.operations,
        backup=backup,
    )


# --- convert -----------------------------------------------------


@app.command()
@_safe
def convert(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    to: str = typer.Option("biblatex", "--to", help="Target format: biblatex or bibtex"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Convert a library between BibTeX and BibLaTeX conventions."""
    coll = Collection.open(file)
    report = coll.convert(to)  # raises ValueError on an unknown target

    verb = "Would convert" if dry_run else "Converted"
    human = [
        f"{verb} {report.entries} {_entries(report.entries)} to {report.target}.",
        "  "
        f"fields_renamed={report.fields_renamed}, "
        f"types_changed={report.types_changed}, dates_changed={report.dates_changed}",
    ]
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "convert",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=report.warnings,
        operations=report.operations,
        backup=backup,
    )


# --- journals ----------------------------------------------------


def _run_journal_op(
    file: str,
    style: str,
    journal_table: Optional[str],
    ltwa_table: Optional[str],
    dry_run: bool,
    diff: bool,
    json_output: bool,
    backup: bool = False,
) -> None:
    """Shared body for ``journals abbreviate`` / ``journals expand``."""
    verb_root = "abbreviate" if style == "abbreviated" else "expand"
    coll = Collection.open(file)
    if style == "abbreviated":
        report = coll.abbreviate_journals(journal_table, ltwa_table)
    else:
        report = coll.expand_journals(journal_table, ltwa_table)

    verb = f"Would {verb_root}" if dry_run else f"{verb_root.capitalize()[:-1]}ed"
    human = [f"{verb} {report.changed} journal {_entries(report.changed)}."]
    if report.unknown:
        human.append(f"  {len(report.unknown)} unknown journal name(s).")

    _finish_mod(
        file,
        f"journals_{verb_root}",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=journals_ops.unknown_journal_warnings(report.unknown),
        resolved=report.resolved,
        unknown=report.unknown,
        backup=backup,
    )


@journals_app.command("abbreviate")
@_safe
def journals_abbreviate(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Abbreviate journal titles (journal/journaltitle)."""
    _run_journal_op(
        file, "abbreviated", journal_table, ltwa_table, dry_run, diff, json_output, backup
    )


@journals_app.command("expand")
@_safe
def journals_expand(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Expand abbreviated journal titles back to their full form."""
    _run_journal_op(file, "full", journal_table, ltwa_table, dry_run, diff, json_output, backup)


@journals_app.command("check")
@_safe
def journals_check(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    journal_table: Optional[str] = typer.Option(
        None, "--journal-table", help="CSV/TSV with title, abbreviation, and optional ISSN mappings"
    ),
    ltwa_table: Optional[str] = typer.Option(
        None, "--ltwa-table", help="CSV/TSV LTWA word abbreviation table"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which journal titles can be resolved (read-only; modifies nothing)."""
    lib = load_bib(file)
    sources = journals_ops.load_sources(journal_table, ltwa_table)

    seen: dict[str, str] = {}
    for entry in lib.entries.values():
        for jfield in journals_ops.JOURNAL_FIELDS:
            title = entry.fields.get(jfield)
            if not title or title in seen:
                continue
            seen[title] = journals_ops.classify_journal(title, entry, sources)

    journals = [{"journal": title, "status": status} for title, status in seen.items()]
    unknown = [j["journal"] for j in journals if j["status"] == "unknown"]

    if json_output:
        result = {
            "status": "success",
            "action": "journals_check",
            "file": file,
            "journals": journals,
            "unknown": unknown,
            "known": len(journals) - len(unknown),
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    typer.echo(f"{file}: {len(journals)} distinct journal {_entries(len(journals))}")
    for item in journals:
        typer.echo(f"  [{item['status']:>7}] {item['journal']}")


# --- capabilities ------------------------------------------------


@app.command()
def capabilities(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show tool capabilities."""
    caps = get_capabilities()
    if json_output:
        typer.echo(_json.dumps(caps, indent=2))
        return
    typer.echo(f"{caps['tool']} v{caps['version']}")
    typer.echo("Commands:")
    for name, desc in caps["commands"].items():
        typer.echo(f"  {name:14} {desc}")


# --- used ------------------------------------------------------------------


@app.command()
@_safe
def used(
    bib_file: str = typer.Argument(..., help="Path to the .bib library"),
    sources: Optional[list[str]] = typer.Argument(
        None,
        help="One or more .tex/.aux files or directories to scan "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    out: Optional[str] = typer.Option(
        None, "--out", help="Write a subset .bib containing only the used entries"
    ),
    group: Optional[str] = typer.Option(
        None, "--group", help="Tag used entries into this JabRef group"
    ),
    keyword: Optional[str] = typer.Option(
        None, "--keyword", help="Tag used entries with this keyword"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources; optionally tag or export them."""
    coll = Collection.open(bib_file)
    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(bib_file).parent)
    )
    if not resolved_sources:
        _emit_error(
            json_output,
            "NoSources",
            "No sources given and no 'tex-sources' metadata to fall back to",
        )
    cited, include_all, scanned = collect_cited_keys(resolved_sources)
    report = analyze_usage(coll.lib, cited, include_all=include_all, sources=scanned)

    tagged = 0
    tag_field = None
    if group:
        tagged = tag_with_group(coll.lib, report.used, group)
        tag_field = "groups"
    elif keyword:
        tagged = tag_with_keyword(coll.lib, report.used, keyword)
        tag_field = "keywords"
    coll.mark_dirty(tagged)

    bib_diff = ""
    tagged_entries = 0
    file_modified = False
    if tag_field:
        bib_diff, file_modified, tagged_entries = _preview_or_commit(coll, dry_run)

    out_written = False
    if out:
        sub = subset_library(coll.lib, report.used)
        if not dry_run:
            save_bib(sub, out, backup=False)
            out_written = True

    if json_output:
        result = {
            "status": "success",
            "action": "used",
            "file": bib_file,
            "dry_run": dry_run,
            "modified": file_modified,
            "modified_entries": tagged_entries,
            "warnings": [],
            "report": report.to_dict(),
            "tagged": {"field": tag_field, "value": group or keyword, "count": tagged}
            if tag_field
            else None,
            "exported": {"path": out, "written": out_written, "count": len(report.used)}
            if out
            else None,
        }
        if diff and bib_diff:
            result["diff"] = bib_diff
        typer.echo(_json.dumps(result, indent=2))
        return

    # Human-readable output
    typer.echo(f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).")
    if report.include_all:
        typer.echo(r"\nocite{*} found — all entries counted as used.")
    typer.echo(f"Used:    {len(report.used)}")
    typer.echo(f"Unused:  {len(report.unused)}")
    typer.echo(f"Missing: {len(report.missing)}")
    if report.missing:
        for key in report.missing:
            typer.echo(f"  - {key}  (cited but not in library)")

    if tag_field:
        verb = "Would tag" if dry_run else "Tagged"
        typer.echo(f'{verb} {tagged} {_entries(tagged)} with {tag_field} = "{group or keyword}".')
    if out:
        verb = "Would write" if dry_run else "Wrote"
        typer.echo(f"{verb} {len(report.used)} {_entries(len(report.used))} to {out}.")
    if diff and bib_diff:
        typer.echo("")
        typer.echo(bib_diff)


if __name__ == "__main__":
    app()
