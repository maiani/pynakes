"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from pathlib import Path

import typer

from pynakes import keys as keys_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    CheckOutcome,
    RunParams,
    _emit_conflict,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _run_checks,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.io import save_plain_text
from pynakes.usage import (
    extract_keys_from_tex,
    iter_tex_files,
    rename_citation_keys_in_tex,
    tex_sources_from_metadata,
)

# --- keys ------------------------------------------------------------------


def _keys_check_one(file: str) -> CheckOutcome:
    coll = Bibliography.open(file)
    duplicates = keys_ops.duplicate_key_counts(coll.lib)
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
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if duplicate keys are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate citation keys in one or more .bib files."""
    _run_checks(files, "keys_check", _keys_check_one, json_output, strict)


def _rename_payload(renames: list[tuple[str, str]]) -> dict:
    return {"renames": [{"old": o, "new": n} for o, n in renames]}


def _looks_like_bib_path(value: str) -> bool:
    path = Path(value)
    return path.suffix.lower() == ".bib" or path.is_file()


def _resolve_generate_args(
    first: str | None,
    second: str | None,
    all_entries: bool,
    json_output: bool,
) -> tuple[str, str | None]:
    """Resolve ``keys generate``'s compatible file/key calling forms."""
    if all_entries:
        if second is not None:
            _emit_error(
                json_output,
                "InvalidInput",
                "Use either --all or one citation key, not both",
            )
        if first is not None and not _looks_like_bib_path(first):
            _emit_error(
                json_output,
                "InvalidInput",
                "Use either --all or one citation key, not both",
            )
        return _resolve_input_bib(first, json_output), None

    if first is None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Provide a citation key, or pass --all to regenerate every key",
        )

    if second is None and not _looks_like_bib_path(first):
        return _resolve_input_bib(None, json_output), first

    if second is None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Provide a citation key with the file, or pass --all to regenerate every key",
        )

    first_is_file = _looks_like_bib_path(first or "")
    second_is_file = _looks_like_bib_path(second)
    if first_is_file and not second_is_file:
        return _resolve_input_bib(first, json_output), second
    if second_is_file and not first_is_file:
        return _resolve_input_bib(second, json_output), first

    _emit_error(
        json_output,
        "InvalidInput",
        "When passing both a file and a citation key, exactly one positional argument must be a .bib file",
    )


def _no_tex_sources(json_output: bool) -> None:
    _emit_error(
        json_output,
        "NoTeXSources",
        "No .tex files found in the provided sources or the library's 'tex-sources' metadata",
    )


def _rewrite_tex_sources(
    file: str,
    coll: Bibliography,
    params: RunParams,
    renames: list[tuple[str, str]],
    json_output: bool,
    sources: list[str] | None = None,
) -> tuple[list[dict], list[str], int]:
    """Rewrite linked TeX citations for already-staged citation-key renames.

    With no TeX sources configured (no argument and no ``tex-sources`` metadata)
    there is simply nothing to update, so this returns a zero-update success —
    a fresh library with no manuscript linked is a normal case, not an error.
    Explicitly-provided sources that resolve to no ``.tex`` files remain an error.
    """
    if not renames:
        return [], [], 0

    resolved_sources = (
        list(sources) if sources else tex_sources_from_metadata(coll.lib, Path(file).parent)
    )
    if not resolved_sources:
        return [], [], 0

    tex_files = iter_tex_files(resolved_sources)
    if not tex_files:
        _no_tex_sources(json_output)

    if not params.dry_run and coll.externally_changed():
        if coll.path is None:
            raise ValueError("key operation requires a bound .bib file")
        raise ExternalModificationError(coll.path)

    source_changes = []
    source_diff_parts = []
    total_source_occurrences = 0
    for path in tex_files:
        before = path.read_text(encoding="utf-8", errors="replace")
        after, occurrences = rename_citation_keys_in_tex(before, renames)
        modified = before != after
        total_source_occurrences += occurrences
        if modified:
            source_diff_parts.append(generate_diff(before, after, path.name))
            if not params.dry_run:
                saved = save_plain_text(after, str(path), encoding="utf-8", backup=params.backup)
                if not saved.success:
                    raise OSError(saved.error or f"Could not write {path}")
        source_changes.append(
            {
                "path": str(path),
                "modified": modified,
                "occurrences": occurrences,
            }
        )
    return source_changes, source_diff_parts, total_source_occurrences


def keys_generate(
    file_or_key: str | None = typer.Argument(
        None,
        help=(
            "Path to the .bib file, or a citation key when the file is auto-detected "
            "(also accepts KEY FILE)"
        ),
    ),
    key_or_file: str | None = typer.Argument(
        None,
        help="Optional citation key or .bib file, allowing either FILE KEY or KEY FILE",
    ),
    all_entries: bool = typer.Option(
        False,
        "--all",
        help="Regenerate every citation key instead of one selected key",
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Derive citation keys from entry metadata and update linked TeX citations."""
    file, key = _resolve_generate_args(file_or_key, key_or_file, all_entries, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
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
    source_changes, source_diff_parts, total_source_occurrences = _rewrite_tex_sources(
        file,
        coll,
        params,
        renames,
        json_output,
    )
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
        **({"key": key} if key is not None else {}),
        source_occurrences=total_source_occurrences,
        sources=source_changes,
        **_rename_payload(renames),
    )


def keys_repair(
    file: str | None = bib_file_argument(),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename duplicate citation keys so every key is unique."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    renames = coll.repair_keys()
    human = [f"{_verb('repair', params)} {len(renames)} duplicate key(s)."]
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename one citation key to an explicit value and update TeX citations."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
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

    bib_changed = coll.rename_key(old, new)
    source_changes, source_diff_parts, total_source_occurrences = _rewrite_tex_sources(
        file,
        coll,
        params,
        [(old, new)],
        json_output,
        list(sources) if sources else None,
    )

    human = [
        f"{_verb('rename', params)} citation key {old!r} to {new!r}.",
        f"  bib entries changed={bib_changed}, TeX citations changed={total_source_occurrences}",
    ]

    # A rename with no TeX sources configured succeeds (a fresh library has no
    # manuscript yet); warn so the caller knows no \cite keys were rewritten.
    warnings: list[dict] = []
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


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(keys_check))
    app.command("generate")(_safe(keys_generate))
    app.command("repair")(_safe(keys_repair))
    app.command("rename")(_safe(keys_rename))
