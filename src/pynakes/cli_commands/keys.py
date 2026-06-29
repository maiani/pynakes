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
    _emit,
    _emit_conflict,
    _emit_error,
    _entries,
    _finish_mod,
    _preview_or_commit,
    _resolve_input_bib,
    _run_checks,
    _safe,
    _verb,
)
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.io import save_plain_text
from pynakes.usage import (
    extract_keys_from_tex,
    iter_tex_files,
    rename_citation_key_in_tex,
    tex_sources_from_metadata,
)

# --- keys ------------------------------------------------------------------


def _keys_check_one(file: str) -> CheckOutcome:
    coll = Bibliography.open(file)
    duplicates = keys_ops.duplicate_key_counts(coll.lib)
    instances = coll.lib.entries.duplicate_key_instances()
    result = {
        "status": "success",
        "action": "keys_check",
        "file": file,
        "has_duplicates": bool(duplicates),
        "duplicate_keys": duplicates,
        "duplicate_key_instances": instances,
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
    """Report duplicate citation keys (accepts multiple files for CI gating)."""
    _run_checks(files, "keys_check", _keys_check_one, json_output, strict)


def _rename_payload(renames: list[tuple[str, str]]) -> dict:
    return {"renames": [{"old": o, "new": n} for o, n in renames]}


def keys_generate(
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="Regenerate only this citation key instead of every key",
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Regenerate citation keys from entry metadata (AuthorYearTitle)."""
    file = _resolve_input_bib(file, json_output)
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
    _finish_mod(
        file,
        "keys_generate",
        coll,
        params,
        human,
        **({"key": key} if key is not None else {}),
        **_rename_payload(renames),
    )


def keys_repair(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename duplicate citation keys so every key is unique."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
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
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
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
    """Rename one citation key in a .bib file and matching TeX citations."""
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
        return
    if not params.dry_run and coll.externally_changed():
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
            if not params.dry_run:
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

    plan = coll.change_plan()  # before commit, which refreshes the baseline
    bib_diff, bib_modified, changed_entries = _preview_or_commit(coll, params)

    diff_text = "\n".join(part for part in [bib_diff, *source_diff_parts] if part)
    source_modified = any(change["modified"] for change in source_changes)
    modified = bib_modified or source_modified

    human = [
        f"{_verb('rename', params)} citation key {old!r} to {new!r}.",
        f"  bib entries changed={bib_changed}, TeX citations changed={total_source_occurrences}",
    ]
    _emit(
        params.json_output,
        {
            "status": "success",
            "action": "keys_rename",
            "file": file,
            "dry_run": params.dry_run,
            "modified": modified,
            "modified_entries": changed_entries,
            "warnings": [],
            "plan": plan,
            "old": old,
            "new": new,
            "source_occurrences": total_source_occurrences,
            "sources": source_changes,
        },
        human,
        diff_text,
        params.diff,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(keys_check))
    app.command("generate")(_safe(keys_generate))
    app.command("repair")(_safe(keys_repair))
    app.command("rename")(_safe(keys_rename))
