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
from typing import Optional

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import _BACKUP_OPTION, _emit_conflict, _entries, _safe
from pynakes.diff import generate_diff
from pynakes.io import load_bib, save_bib
from pynakes.setops import PartitionRule, merge_libraries, partition_library
from pynakes.usage import collect_cited_keys


def _load_inputs(paths: list[str]) -> list[tuple[str, object]]:
    return [(path, load_bib(path)) for path in paths]


def _file_diff(path: str, new_content: str) -> str:
    """Unified diff from the file's current content (or empty) to ``new_content``."""
    original = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            original = handle.read()
    return generate_diff(original, new_content, path)


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
    result = merge_libraries(_load_inputs(inputs), dedupe=dedupe)
    if result.conflicts:
        _emit_conflict(
            json_output,
            "DuplicateMergeKey",
            f"{len(result.conflicts)} citation key(s) differ across inputs under --dedupe",
            conflicts=result.conflicts,
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

    content = write_bib(result.lib)
    entries = len(result.lib.entries)
    # Diff against the pre-existing file (or empty) before we overwrite it.
    diff_text = _file_diff(out, content) if diff else ""
    written = False
    if not dry_run:
        save_bib(result.lib, out, backup=backup)
        written = True

    warnings: list[dict[str, object]] = []
    if result.duplicate_keys:
        warnings.append({"type": "duplicate_keys", "keys": result.duplicate_keys})

    if json_output:
        payload = {
            "status": "success",
            "action": "combine",
            "inputs": result.inputs,
            "out": out,
            "dedupe": dedupe,
            "dry_run": dry_run,
            "written": written,
            "entries": entries,
            "warnings": warnings,
        }
        if diff and diff_text:
            payload["diff"] = diff_text
        typer.echo(_json.dumps(payload, indent=2))
        return

    verb = "Would write" if dry_run else "Wrote"
    typer.echo(f"Combined {len(result.inputs)} file(s) → {entries} {_entries(entries)}.")
    if result.duplicate_keys:
        typer.echo(f"  duplicate key(s): {', '.join(result.duplicate_keys)}")
    typer.echo(f"{verb} {out}.")
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
    tex: Optional[list[str]] = typer.Option(
        None, "--tex", help="TeX file(s)/dir(s) feeding the used/unused predicates"
    ),
    aux: Optional[list[str]] = typer.Option(
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

    merged = merge_libraries(_load_inputs(inputs), dedupe=dedupe)
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
        content = write_bib(bucket)
        # Diff against the pre-existing file (or empty) before we overwrite it.
        if diff:
            diff_chunks.append(_file_diff(rule.label, content))
        written = False
        if not dry_run:
            save_bib(bucket, rule.label, backup=backup)
            written = True
        outputs.append(
            {
                "file": rule.label,
                "predicate": rule.predicate,
                "entries": result.counts[rule.label],
                "written": written,
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

    verb = "Would write" if dry_run else "Wrote"
    typer.echo(f"Split {len(merged.inputs)} input(s) into {len(rules)} output(s):")
    for entry in outputs:
        count = entry["entries"]
        typer.echo(f"  {verb} {count} {_entries(count)} → {entry['file']}  [{entry['predicate']}]")
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
