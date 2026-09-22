"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import dedupe as dedupe_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    CheckOutcome,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _run_checks,
    _safe,
    _verb,
    bib_file_argument,
    key_option,
    parse_key_selector,
)
from pynakes.engine import Bibliography

# --- dedupe ----------------------------------------------------------------


def _dedupe_check_one(file: str) -> CheckOutcome:
    coll = Bibliography.open(file)
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


def dedupe_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if duplicate works are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate works by DOI/arXiv/other IDs and fuzzy title matches."""
    _run_checks(files, "dedupe_check", _dedupe_check_one, json_output, strict)


def dedupe_merge(
    file: str | None = bib_file_argument(),
    key: list[str] | None = key_option(
        "Merge only the duplicate clusters containing these citation keys: "
        "comma-separated, repeatable. Omit to merge every cluster in the file"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively merge duplicate works into their first entry.

    Without ``--key`` every duplicate cluster in the file is merged. With it,
    only the clusters containing a named key are, so one pair can be resolved
    after looking at it without accepting every other merge the file invites.
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)
    selected = parse_key_selector(key)
    coll = Bibliography.open(file)
    try:
        report = coll.dedupe_merge(selected or None)
    except ValueError as exc:
        _emit_error(json_output, "NoSuchDuplicate", str(exc))
        return
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
        return

    scope = f" selected by {len(selected)} key(s)" if selected else ""
    human = [
        f"{_verb('merge', params)} {report.merged_clusters} duplicate work cluster(s){scope}.",
        f"  removed_entries={report.removed_entry_count}, field_changes={report.field_changes}",
    ]
    _finish_mod(
        file,
        "dedupe_merge",
        coll,
        params,
        human,
        modified_entries=report.modified_entries,
        keys=selected,
        **report.to_dict(),
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(dedupe_check))
    app.command("merge")(_safe(dedupe_merge))
