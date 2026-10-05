"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from pathlib import Path

import typer

from pynakes import _tex_rewrite
from pynakes import keys as keys_ops
from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit,
    _emit_conflict,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
)
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.usage import (
    extract_keys_from_tex,
    find_key_usages,
    iter_tex_files,
    resolve_existing_tex_sources,
    tex_sources_from_metadata,
)

# --- keys ------------------------------------------------------------------


def _params(
    dry_run: bool, diff: bool, json_output: bool, backup: bool, expect_sha256: str | None
) -> RunParams:
    return RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )


def _keys_check_one(file: str) -> CheckOutcome:
    coll = Bibliography.open(file)
    duplicates = coll.lib.entries.duplicate_keys()
    instances = coll.lib.entries.duplicate_key_instances()
    issues = [
        {
            "type": "duplicate_key",
            "severity": "error",
            "message": f"Citation key {key!r} appears {count} times",
            "key": key,
            "instances": instances.get(key, []),
        }
        for key, count in duplicates.items()
    ]
    result = {
        "status": "success",
        "action": "keys_check",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [],
        "has_duplicates": bool(duplicates),
        "duplicate_keys": duplicates,
        "duplicate_key_instances": instances,
        "issues": issues,
    }
    if not duplicates:
        human = [f"{file}: all citation keys are unique."]
    else:
        human = []
        for key, indices in instances.items():
            line_refs = ", ".join(f"#{i}" for i in indices)
            human.append(f"  {key}: appears {len(indices)} times (entry {line_refs})")
        human.append(f"{len(duplicates)} duplicated key(s).")
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(duplicates),
        summary={"duplicate_keys": len(duplicates)},
    )


def keys_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = strict_option("duplicate citation keys are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate citation keys in one or more .bib files."""
    _run_checks(files, "keys_check", _keys_check_one, json_output, strict)


def _rename_payload(renames: list[tuple[str, str]]) -> dict:
    return {"renames": [{"old": o, "new": n} for o, n in renames]}


def _no_tex_sources(json_output: bool) -> None:
    _emit_error(
        json_output,
        "NoSources",
        "No .tex files found in the provided sources or the library's 'tex-sources' metadata",
    )


def _rewrite_tex_sources(
    file: str,
    coll: Bibliography,
    params: RunParams,
    renames: list[tuple[str, str]],
    json_output: bool,
    sources: list[str] | None = None,
) -> tuple[list[dict], list[str], int, list[dict]]:
    """Stage linked TeX citation rewrites for already-staged citation-key renames.

    With no TeX sources configured (no argument and no ``tex-sources`` metadata)
    there is simply nothing to update, so this returns a zero-update success —
    a fresh library with no manuscript linked is a normal case, not an error.
    Explicitly-provided sources that resolve to no ``.tex`` files remain an error.

    Returns ``(source_changes, source_diff_parts, total_source_occurrences, warnings)``.
    """
    if not renames:
        return [], [], 0, []

    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(file).parent)
    )
    if not resolved_sources:
        return [], [], 0, []

    warnings: list[dict] = []
    if not sources:
        resolved_sources, warnings = resolve_existing_tex_sources(resolved_sources)

    tex_files = iter_tex_files(resolved_sources)
    if not tex_files:
        _no_tex_sources(json_output)
    if not sources:
        _tex_rewrite.require_inside_project(tex_files, Path(file))

    if not params.dry_run and coll.externally_changed():
        if coll.path is None:
            raise ValueError("key operation requires a bound .bib file")
        raise ExternalModificationError(coll.path)

    rewrites = [_tex_rewrite.plan_tex_rewrite(path, renames) for path in tex_files]
    source_changes = []
    source_diff_parts = []
    for rewrite in rewrites:
        if rewrite.modified:
            source_diff_parts.append(
                generate_diff(rewrite.before, rewrite.after, rewrite.path.name)
            )
        source_changes.append(
            {
                "path": str(rewrite.path),
                "modified": rewrite.modified,
                "occurrences": rewrite.occurrences,
            }
        )
    # Written by the commit, after the .bib, so a failure cannot split them.
    coll.stage_tex_rewrites(rewrites)
    total_source_occurrences = sum(rewrite.occurrences for rewrite in rewrites)
    return source_changes, source_diff_parts, total_source_occurrences, warnings


def keys_generate(
    file: str | None = bib_file_argument(),
    key: str | None = typer.Argument(None, help="Citation key to regenerate"),
    all_entries: bool = typer.Option(
        False,
        "--all",
        help="Regenerate every citation key instead of one selected key",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Derive citation keys from entry metadata and update linked TeX citations."""
    if all_entries and key is not None:
        _emit_error(json_output, "InvalidInput", "Use either --all or one citation key, not both")
    if not all_entries and key is None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Provide a citation key, or pass --all to regenerate every key",
        )
    file = _resolve_input_bib(file, json_output)
    params = _params(dry_run, diff, json_output, backup, expect_sha256)
    coll = Bibliography.open(file)
    if key is None:
        renames = coll.generate_keys()
    else:
        rename = coll.generate_key(key)
        renames = [rename] if rename is not None else []
    if key is None:
        human = [f"{_verb('rename', params)} {len(renames)} {_entries(len(renames))}."]
    elif renames:
        human = [
            f"{_verb('normalize', params)} citation key {renames[0][0]!r} to {renames[0][1]!r}."
        ]
    else:
        human = [f"Citation key {key!r} already matches the preferred pattern."]
    human += [f"  {old} -> {new}" for old, new in renames]
    source_changes, source_diff_parts, total_source_occurrences, source_warnings = (
        _rewrite_tex_sources(
            file,
            coll,
            params,
            renames,
            json_output,
        )
    )
    for w in source_warnings:
        human.append(f"  {w['message']}")
    if source_changes:
        human.append(f"  TeX citations changed={total_source_occurrences}")
    if params.diff:
        bib_diff = coll.diff()
        diff_text = "\n".join(part for part in [bib_diff, *source_diff_parts] if part)
    else:
        diff_text = None
    _finish_mod(
        file,
        "keys_generate",
        coll,
        params,
        human,
        diff_text=diff_text,
        warnings=source_warnings,
        **({"key": key} if key is not None else {}),
        source_occurrences=total_source_occurrences,
        sources=source_changes,
        **_rename_payload(renames),
    )


def keys_repair(
    file: str | None = bib_file_argument(),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename duplicate citation keys so every key is unique."""
    params = _params(dry_run, diff, json_output, backup, expect_sha256)
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    renames = coll.repair_keys()
    human = [f"{_verb('repair', params)} {len(renames)} duplicate key(s)."]
    human += [f"  {old} -> {new}" for old, new in renames]

    # A repaired key still exists on the first (kept) entry, so a TeX
    # `\cite{key}` is now ambiguous rather than simply renamed — rewriting it
    # would be a guess. Instead, warn when a linked source cites a repaired key.
    warnings = _repaired_citation_warnings(coll.lib, file, renames)
    for w in warnings:
        if w["type"] == "missing_tex_source":
            human.append(f"  {w['message']}")
    ambiguous = [w for w in warnings if w["type"] == "ambiguous_citation"]
    if ambiguous:
        human.append(f"  {len(ambiguous)} citation(s) now ambiguous in linked TeX sources.")

    _finish_mod(
        file,
        "keys_repair",
        coll,
        params,
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
    sources, warnings = resolve_existing_tex_sources(sources)
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


def keys_rename(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Existing citation key"),
    new: str = typer.Argument(..., help="New citation key"),
    sources: list[str] | None = typer.Argument(
        None,
        help="One or more .tex files or directories whose citations should be updated "
        "(defaults to the library's 'tex-sources' metadata)",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename one citation key to an explicit value and update TeX citations."""
    file = _resolve_input_bib(file, json_output)
    params = _params(dry_run, diff, json_output, backup, expect_sha256)
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
    keys_ops.validate_key(old)
    keys_ops.validate_key(new)

    matches = coll.lib.entries.get_all(old)
    if not matches:
        _emit_error(json_output, "KeyNotFound", f"No entry with key {old!r} in the library")
        return
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
        return
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
        return

    coll.rename_key(old, new)
    # Counts the renamed entry and every entry whose crossref/xdata followed it.
    bib_changed = coll.changed_entries_count()
    source_changes, source_diff_parts, total_source_occurrences, source_warnings = (
        _rewrite_tex_sources(
            file,
            coll,
            params,
            [(old, new)],
            json_output,
            list(sources) if sources else None,
        )
    )

    human = [
        f"{_verb('rename', params)} citation key {old!r} to {new!r}.",
        f"  bib entries changed={bib_changed}, TeX citations changed={total_source_occurrences}",
    ]

    # A rename with no TeX sources configured succeeds (a fresh library has no
    # manuscript yet); warn so the caller knows no \cite keys were rewritten.
    warnings: list[dict] = source_warnings
    for w in source_warnings:
        human.append(f"  {w['message']}")
    if bib_changed and not source_changes:
        warnings.append(
            {
                "type": "no_tex_sources",
                "message": (
                    "Renamed the citation key but updated no manuscript citations: no "
                    "TeX sources are configured. Pass a .tex file/dir or set 'tex-sources' "
                    "metadata to rewrite \\cite keys."
                ),
            }
        )
        human.append(f"  {warnings[0]['message']}")

    if params.diff:
        bib_diff = coll.diff()
        diff_text = "\n".join(part for part in [bib_diff, *source_diff_parts] if part)
    else:
        diff_text = None

    _finish_mod(
        file,
        "keys_rename",
        coll,
        params,
        human,
        diff_text=diff_text,
        warnings=warnings,
        old=old,
        new=new,
        source_occurrences=total_source_occurrences,
        sources=source_changes,
    )


def keys_usage(
    key: str = typer.Argument(..., help="Citation key to search for"),
    sources: list[str] = typer.Argument(..., help="One or more .tex files or directories to scan"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Scan TeX sources directly for \\cite-family citations of one key.

    Unlike `tex scan`, this takes no .bib file and never consults
    'tex-sources' metadata: it scans exactly the given directories or files,
    so a rename's blast radius can be checked over sources that were never
    registered with `tex add` — frozen snapshots, generated diffs, or any
    other .tex the library does not track.
    """
    keys_ops.validate_key(key)
    matches, scanned = find_key_usages(key, sources)

    human = [f"Scanned {len(scanned)} .tex file(s) for citations of {key!r}."]
    if matches:
        for m in matches:
            human.append(f"  {m.path}:{m.line}: {m.text}")
    else:
        human.append("  No citations found.")

    result = {
        "status": "success",
        "action": "keys_usage",
        "warnings": [],
        "key": key,
        "sources": list(sources),
        "scanned": scanned,
        "count": len(matches),
        "matches": [m.to_dict() for m in matches],
    }
    _emit(json_output, result, human)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(keys_check))
    app.command("generate")(_safe(keys_generate))
    app.command("repair")(_safe(keys_repair))
    app.command("rename")(_safe(keys_rename))
    app.command("usage")(_safe(keys_usage))
