"""CLI commands for whole-file set operations: ``corpus combine`` and ``corpus split``.

``combine`` unions several ``.bib`` files into one; ``split`` routes the entries
of one or more inputs into several outputs selected by per-bucket predicates.
Both read their inputs read-only and create new files, so they use their own
result envelope rather than the single-file ``_finish_mod`` one.

(``combine`` unions whole files; merging two records of the *same* work is a
distinct operation living under ``dedupe merge``.)
"""

from pathlib import Path

import typer

from pynakes._text_utils import strip_meta_terminator
from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit,
    _emit_conflict,
    _entries,
    _finish_create,
    _safe,
    _verb,
)
from pynakes.diff import generate_diff
from pynakes.filestore import FILES_DIR_KEY, FileStore
from pynakes.io import load_bib, save_text
from pynakes.metadata import metadata_value, set_metadata
from pynakes.model import BibFile
from pynakes.setops import PartitionRule, merge_libraries, partition_library, strip_metadata_blocks
from pynakes.usage import collect_cited_keys


def _load_inputs(paths: list[str]) -> list[tuple[str, BibFile]]:
    return [(path, load_bib(path)) for path in paths]


def _entry_sources(named_libs: list[tuple[str, BibFile]]) -> dict[int, FileStore]:
    sources: dict[int, FileStore] = {}
    for path, lib in named_libs:
        store = FileStore.from_metadata(lib, path)
        if store is None:
            continue
        for entry in lib.entries.values():
            sources[id(entry)] = store
    return sources


def _ensure_pinax_output(lib: BibFile, out: str, *, preserve_files_dir: bool = False) -> FileStore:
    # Deriving files-dir from the --out basename is right for a fresh output
    # (keeps inputs read-only), but a self-combine (--out is also an input) must
    # keep that library's own files-dir so a custom value isn't silently renamed.
    if not (preserve_files_dir and metadata_value(lib, FILES_DIR_KEY) is not None):
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
    preserve_files_dir: bool = False,
) -> list[dict[str, str]]:
    if not sources:
        return []
    duplicates = lib.entries.duplicate_keys()
    if duplicates:
        keys = ", ".join(sorted(duplicates))
        raise ValueError(f"Pinax output requires unique citation keys: {keys}")
    target = _ensure_pinax_output(lib, out, preserve_files_dir=preserve_files_dir)
    copied: list[dict[str, str]] = []
    if dry_run:
        return copied
    for entry in lib.entries.values():
        source = sources.get(id(entry))
        if source is not None:
            copied.extend(target.copy_materials_from(source, entry.key))
    return copied


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
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    named_inputs = _load_inputs(inputs)
    pinax_sources = _entry_sources(named_inputs)
    merged = merge_libraries(named_inputs, dedupe=dedupe)
    if merged.conflicts:
        _emit_conflict(
            params.json_output,
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

    self_output = Path(out).resolve() in {Path(p).resolve() for p in inputs}
    primary_files_dir = metadata_value(merged.lib, FILES_DIR_KEY)
    pinax_materials = _copy_pinax_materials(
        merged.lib, out, pinax_sources, dry_run=params.dry_run, preserve_files_dir=self_output
    )
    content = write_bib(merged.lib)
    entries = len(merged.lib.entries)

    previous_content = ""
    if params.diff:
        try:
            previous_content = Path(out).read_text(encoding="utf-8")
        except FileNotFoundError:
            pass

    warnings: list[dict[str, object]] = []
    if merged.duplicate_keys:
        warnings.append({"type": "duplicate_keys", "keys": merged.duplicate_keys})
    output_files_dir = metadata_value(merged.lib, FILES_DIR_KEY)
    if (
        pinax_sources
        and not self_output
        and primary_files_dir is not None
        and output_files_dir is not None
        and strip_meta_terminator(primary_files_dir) != strip_meta_terminator(output_files_dir)
    ):
        warnings.append(
            {
                "type": "files_dir_changed",
                "from": strip_meta_terminator(primary_files_dir),
                "to": strip_meta_terminator(output_files_dir),
                "message": (
                    "Output files-dir derived from --out differs from the primary "
                    "input's; materials were copied into the output's files-dir."
                ),
            }
        )

    human = [f"Combined {len(merged.inputs)} file(s) → {entries} {_entries(entries)}."]
    if pinax_sources:
        human.append(f"  pinax materials copied: {len(pinax_materials)}")
    if merged.duplicate_keys:
        human.append(f"  duplicate key(s): {', '.join(merged.duplicate_keys)}")
    human.append(f"{_verb('write', params, 'Wrote')} {out}.")

    _finish_create(
        params=params,
        path=out,
        action="combine",
        content=content,
        human=human,
        previous_content=previous_content,
        backup=backup,
        warnings=warnings,
        inputs=merged.inputs,
        dedupe=dedupe,
        entries=entries,
        pinax_materials=pinax_materials,
    )


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
    minimal: bool = typer.Option(
        False,
        "--minimal",
        help="Drop jabref-meta/pynakes-meta blocks and skip Pinax materials in "
        "outputs, for standalone single-entry or few-entry snippets",
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
    """Combine inputs, then route entries into several outputs by predicate.

    Each output carries the source library's jabref-meta/pynakes-meta blocks
    (groups, save-order config, Pinax fetch settings) and copies any linked
    Pinax materials, since a bucket is usually still a working library. Pass
    ``--minimal`` for a bucket that's meant as a standalone snippet instead
    (e.g. one entry pulled out to hand to a collaborator): it drops those
    metadata blocks entirely and skips materials copying.
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    rules = _parse_rules(to)

    named_inputs = _load_inputs(inputs)
    pinax_sources = _entry_sources(named_inputs)
    merged = merge_libraries(named_inputs, dedupe=dedupe)
    if merged.conflicts:
        _emit_conflict(
            params.json_output,
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
        if minimal:
            strip_metadata_blocks(bucket)
            pinax_materials: list[dict[str, str]] = []
        else:
            pinax_materials = _copy_pinax_materials(
                bucket, rule.label, pinax_sources, dry_run=params.dry_run
            )
        content = write_bib(bucket)
        count = result.counts[rule.label]

        previous_content = ""
        if params.diff:
            try:
                previous_content = Path(rule.label).read_text(encoding="utf-8")
            except FileNotFoundError:
                pass

        chunk_diff = generate_diff(previous_content, content, rule.label) if params.diff else ""
        if chunk_diff:
            diff_chunks.append(chunk_diff)

        written = False
        if not params.dry_run:
            save_result = save_text(content, rule.label, backup=backup)
            written = save_result.success

        outputs.append(
            {
                "file": rule.label,
                "predicate": rule.predicate,
                "entries": count,
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

    payload = {
        "status": "success",
        "action": "split",
        "inputs": merged.inputs,
        "dry_run": params.dry_run,
        "copy": copy,
        "minimal": minimal,
        "outputs": outputs,
        "unrouted": result.unrouted,
        "warnings": warnings,
    }
    human = [f"Split {len(merged.inputs)} input(s) into {len(rules)} output(s):"]
    for entry in outputs:
        count = entry["entries"]
        human.append(
            f"  {_verb('write', params, 'Wrote')} {count} {_entries(count)} → {entry['file']}  [{entry['predicate']}]"
        )
    if result.unrouted:
        human.append(f"  {result.unrouted} {_entries(result.unrouted)} matched no output.")
    if merged.duplicate_keys:
        human.append(f"  duplicate key(s): {', '.join(merged.duplicate_keys)}")
    _emit(params.json_output, payload, human, diff_text, params.diff)


def register(app: typer.Typer) -> None:
    """Register the ``combine`` and ``split`` commands."""
    app.command()(_safe(combine))
    app.command()(_safe(split))
