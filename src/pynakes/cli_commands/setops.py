"""CLI commands for whole-file set operations: ``combine`` and ``split``.

``combine`` unions several ``.bib`` files into one; ``split`` routes the entries
of one or more inputs into several outputs selected by per-bucket predicates.
Both read their inputs read-only and create new files, so they use their own
result envelope rather than the single-file ``_finish_mod`` one.

(``combine`` unions whole files; merging two records of the *same* work is a
distinct operation living under ``dedupe merge``.)
"""

import json as _json
import os
from pathlib import Path

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import _BACKUP_OPTION, _emit_conflict, _entries, _safe, _verb
from pynakes.diff import generate_diff
from pynakes.filestore import FILES_DIR_KEY, FileStore
from pynakes.io import load_bib, save_bib
from pynakes.metadata import set_metadata
from pynakes.model import BibFile
from pynakes.setops import PartitionRule, merge_libraries, partition_library
from pynakes.usage import collect_cited_keys


def _load_inputs(paths: list[str]) -> list[tuple[str, BibFile]]:
    return [(path, load_bib(path)) for path in paths]


def _file_diff(path: str, new_content: str) -> str:
    """Unified diff from the file's current content (or empty) to ``new_content``."""
    original = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            original = handle.read()
    return generate_diff(original, new_content, path)


def _entry_sources(named_libs: list[tuple[str, BibFile]]) -> dict[int, FileStore]:
    sources: dict[int, FileStore] = {}
    for path, lib in named_libs:
        store = FileStore.from_metadata(lib, path)
        if store is None:
            continue
        for entry in lib.entries.values():
            sources[id(entry)] = store
    return sources


def _ensure_pinax_output(lib: BibFile, out: str) -> FileStore:
    set_metadata(lib, FILES_DIR_KEY, f"{Path(out).stem}.files")
    store = FileStore.from_metadata(lib, out)
    if store is None:
        raise ValueError("could not resolve output files-dir")
    return store


def _copy_pinax_materials(
    lib: BibFile,
    out: str,
    sources: dict[int, FileStore],
    *,
    dry_run: bool,
) -> list[dict[str, str]]:
    if not sources:
        return []
    duplicates = lib.entries.duplicate_keys()
    if duplicates:
        keys = ", ".join(sorted(duplicates))
        raise ValueError(f"Pinax output requires unique citation keys: {keys}")
    target = _ensure_pinax_output(lib, out)
    copied: list[dict[str, str]] = []
    if dry_run:
        return copied
    for entry in lib.entries.values():
        source = sources.get(id(entry))
        if source is not None:
            copied.extend(target.copy_materials_from(source, entry.key))
    return copied


def _merge_and_check(
    named_inputs: list[tuple[str, BibFile]],
    dedupe: bool,
    json_output: bool,
    *,
    extra_conflict_note: str = "",
) -> BibFile:
    """Merge inputs and emit conflict if --dedupe reveals differing same-key entries."""
    result = merge_libraries(named_inputs, dedupe=dedupe)
    if result.conflicts:
        _emit_conflict(
            json_output,
            "DuplicateMergeKey",
            f"{len(result.conflicts)} citation key(s) differ across inputs under --dedupe",
            conflicts=result.conflicts,
            options=[
                {
                    "id": "keep_all",
                    "description": f"Re-run without --dedupe to keep every entry{extra_conflict_note}",
                },
                {
                    "id": "manual_resolve",
                    "description": "Reconcile the differing entries in the inputs, then retry",
                },
            ],
        )
        return
    return result.lib


def _write_bib_file(
    lib: BibFile,
    path: str,
    content: str,
    backup: bool,
    dry_run: bool,
    *,
    diff: bool = False,
) -> tuple[bool, str]:
    """Write *content* to *path* (unless dry-run), returning (written, diff_text)."""
    diff_text = _file_diff(path, content) if diff else ""
    written = False
    if not dry_run:
        save_bib(lib, path, backup=backup)
        written = True
    return written, diff_text


# --- combine ---------------------------------------------------------------


def combine(
    inputs: list[str] = typer.Argument(..., help="Two or more .bib files to combine"),
    out: str = typer.Option(..., "--out", help="Path to write the combined .bib"),
    dedupe: bool = typer.Option(
        False,
        "--dedupe",
        help="Collapse entries that share a citation key; differing same-key "
        "entries are reported as a conflict instead of guessing",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of the output"),
    backup: bool = _BACKUP_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Combine several .bib files into one (optionally deduping by citation key)."""
    named_inputs = _load_inputs(inputs)
    pinax_sources = _entry_sources(named_inputs)
    merged = merge_libraries(named_inputs, dedupe=dedupe)
    if merged.conflicts:
        _emit_conflict(
            json_output,
            "DuplicateMergeKey",
            f"{len(merged.conflicts)} citation key(s) differ across inputs under --dedupe",
            conflicts=merged.conflicts,
            options=[
                {
                    "id": "keep_all",
                    "description": "Re-run without --dedupe to keep every entry (duplicate keys tolerated)",
                },
                {
                    "id": "manual_resolve",
                    "description": "Reconcile the differing entries in the inputs, then retry",
                },
            ],
        )
        return

    pinax_materials = _copy_pinax_materials(merged.lib, out, pinax_sources, dry_run=dry_run)
    content = write_bib(merged.lib)
    entries = len(merged.lib.entries)
    written, diff_text = _write_bib_file(merged.lib, out, content, backup, dry_run, diff=diff)

    warnings: list[dict[str, object]] = []
    if merged.duplicate_keys:
        warnings.append({"type": "duplicate_keys", "keys": merged.duplicate_keys})

    if json_output:
        payload = {
            "status": "success",
            "action": "combine",
            "inputs": merged.inputs,
            "out": out,
            "dedupe": dedupe,
            "dry_run": dry_run,
            "written": written,
            "entries": entries,
            "warnings": warnings,
            "pinax_materials": pinax_materials,
        }
        if diff and diff_text:
            payload["diff"] = diff_text
        typer.echo(_json.dumps(payload, indent=2))
        return

    typer.echo(f"Combined {len(merged.inputs)} file(s) → {entries} {_entries(entries)}.")
    if pinax_sources:
        typer.echo(f"  pinax materials copied: {len(pinax_materials)}")
    if merged.duplicate_keys:
        typer.echo(f"  duplicate key(s): {', '.join(merged.duplicate_keys)}")
    typer.echo(f"{_verb('write', dry_run, 'Wrote')} {out}.")
    if diff and diff_text:
        typer.echo("")
        typer.echo(diff_text)


# --- split -----------------------------------------------------------------


def _parse_rules(specs: list[str]) -> list[PartitionRule]:
    rules: list[PartitionRule] = []
    seen: set[str] = set()
    for spec in specs:
        label, sep, predicate = spec.partition("=")
        label = label.strip()
        predicate = predicate.strip()
        if not sep or not label or not predicate:
            raise ValueError(f"Invalid --to {spec!r}; expected FILE='predicate'")
        if label in seen:
            raise ValueError(f"Duplicate output file in --to: {label!r}")
        seen.add(label)
        rules.append(PartitionRule(label=label, predicate=predicate))
    return rules


def split(
    inputs: list[str] = typer.Argument(..., help="One or more .bib files (merged in memory)"),
    to: list[str] = typer.Option(
        ...,
        "--to",
        help="Output rule FILE='predicate' (repeatable). Predicate: a --where "
        'expression, or one of * / used / unused / group "Name".',
    ),
    copy: bool = typer.Option(
        False,
        "--copy",
        help="Send an entry to every matching bucket (default: first match only)",
    ),
    tex: list[str] | None = typer.Option(
        None, "--tex", help="TeX file(s)/dir(s) feeding the used/unused predicates"
    ),
    aux: list[str] | None = typer.Option(
        None, "--aux", help="AUX file(s)/dir(s) feeding the used/unused predicates"
    ),
    dedupe: bool = typer.Option(
        False, "--dedupe", help="Dedupe by citation key while merging the inputs"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of each output"),
    backup: bool = _BACKUP_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Combine inputs, then route entries into several outputs by predicate."""
    rules = _parse_rules(to)

    named_inputs = _load_inputs(inputs)
    pinax_sources = _entry_sources(named_inputs)
    merged = merge_libraries(named_inputs, dedupe=dedupe)
    if merged.conflicts:
        _emit_conflict(
            json_output,
            "DuplicateMergeKey",
            f"{len(merged.conflicts)} citation key(s) differ across inputs under --dedupe",
            conflicts=merged.conflicts,
            options=[
                {
                    "id": "keep_all",
                    "description": "Re-run without --dedupe to keep every entry",
                },
                {
                    "id": "manual_resolve",
                    "description": "Reconcile the differing entries in the inputs, then retry",
                },
            ],
        )
        return

    sources = [*(tex or []), *(aux or [])]
    cited_keys: set[str] | None = None
    if sources:
        cited, include_all, _scanned = collect_cited_keys(sources)
        cited_keys = set(merged.lib.entries.keys()) if include_all else cited

    result = partition_library(merged.lib, rules, copy=copy, cited_keys=cited_keys)

    outputs: list[dict[str, object]] = []
    diff_chunks: list[str] = []
    for rule in rules:
        bucket = result.buckets[rule.label]
        pinax_materials = _copy_pinax_materials(bucket, rule.label, pinax_sources, dry_run=dry_run)
        content = write_bib(bucket)
        written, chunk_diff = _write_bib_file(
            bucket, rule.label, content, backup, dry_run, diff=diff
        )
        if chunk_diff:
            diff_chunks.append(chunk_diff)
        outputs.append(
            {
                "file": rule.label,
                "predicate": rule.predicate,
                "entries": result.counts[rule.label],
                "written": written,
                "pinax_materials": pinax_materials,
            }
        )

    warnings: list[dict[str, object]] = []
    if merged.duplicate_keys:
        warnings.append({"type": "duplicate_keys", "keys": merged.duplicate_keys})
    if result.unrouted:
        warnings.append({"type": "unrouted_entries", "count": result.unrouted})

    diff_text = "\n".join(chunk for chunk in diff_chunks if chunk)

    if json_output:
        payload = {
            "status": "success",
            "action": "split",
            "inputs": merged.inputs,
            "dry_run": dry_run,
            "copy": copy,
            "outputs": outputs,
            "unrouted": result.unrouted,
            "warnings": warnings,
        }
        if diff and diff_text:
            payload["diff"] = diff_text
        typer.echo(_json.dumps(payload, indent=2))
        return

    typer.echo(f"Split {len(merged.inputs)} input(s) into {len(rules)} output(s):")
    for entry in outputs:
        count = entry["entries"]
        typer.echo(
            f"  {_verb('write', dry_run, 'Wrote')} {count} {_entries(count)} → {entry['file']}  [{entry['predicate']}]"
        )
    if result.unrouted:
        typer.echo(f"  {result.unrouted} {_entries(result.unrouted)} matched no output.")
    if merged.duplicate_keys:
        typer.echo(f"  duplicate key(s): {', '.join(merged.duplicate_keys)}")
    if diff and diff_text:
        typer.echo("")
        typer.echo(diff_text)


def register(app: typer.Typer) -> None:
    """Register the ``combine`` and ``split`` commands."""
    app.command()(_safe(combine))
    app.command()(_safe(split))
