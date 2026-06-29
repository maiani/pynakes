"""CLI command registration for ``pynakes asset fetch``.

Downloads arXiv materials (PDF and source) for entries into the Pinax files-dir.
"""

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
)
from pynakes.engine import Bibliography


def fetch(
    target: str | None = typer.Argument(
        None, help="Citation key to fetch (default: all entries with arXiv ids)"
    ),
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be fetched without downloading"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Download arXiv materials (PDF and source) for entries into the Pinax files-dir."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)

    try:
        coll = Bibliography.open(file)
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))

    report = coll.fetch_materials(target=target, dry_run=params.dry_run)

    warnings: list[str] = []
    for f in report["fetched"]:
        parts = []
        if f["pdf_path"]:
            parts.append("PDF")
        if f["source_path"]:
            parts.append("source")
        label = "+".join(parts) if parts else "materials"
        warnings.append(f"Fetched {label} for {f['key']} (arXiv:{f['arxiv_id']}).")
    for s in report["skipped"]:
        warnings.append(f"Skipped {s['key']} ({s['reason']}).")
    for f in report["failed"]:
        warnings.append(f"Failed {f['key']} ({f['error']}).")

    _finish_mod(
        file,
        "fetch",
        coll,
        params,
        warnings,
        fetch_preprint=report["fetch_preprint"],
        fetch_source=report["fetch_source"],
        fetch_published=report["fetch_published"],
        fetched=report["fetched"],
        skipped=report["skipped"],
        failed=report["failed"],
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("fetch")(_safe(fetch))
