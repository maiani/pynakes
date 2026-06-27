"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from typing import Optional

import typer

from pynakes.cli_common import (
    CheckOutcome,
    _entries,
    _finish_mod,
    _metadata_cache_dir,
    _run_checks,
    _safe,
)
from pynakes.engine import Bibliography

# --- integrity / enrichment -------------------------------------------------


def _verify_one(
    file: str, online: bool, cache_dir: Optional[str], strict: bool, published: bool
) -> CheckOutcome:
    coll = Bibliography.open(file)
    cache = _metadata_cache_dir(file, cache_dir, online)
    report = coll.verify(online=online, cache_dir=cache)
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
    if published:
        # Read-only preprint check, folded in from the former `published` command.
        # Informational only: it never affects the --strict gate.
        preprints = coll.published_check(online=online, cache_dir=cache)
        result["preprints"] = {
            "checked": preprints.checked,
            "published": preprints.published,
            "candidates": [candidate.to_dict() for candidate in preprints.candidates],
        }
        human.append(
            f"  preprints: {preprints.published} of {preprints.checked} have "
            "published-version metadata available"
        )
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


def verify(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    online: bool = typer.Option(
        False, "--online", help="Fetch DOI provider metadata; otherwise only local checks run"
    ),
    published: bool = typer.Option(
        False,
        "--published",
        help="Also report preprints that now have a published version available "
        "(read-only; informational, does not affect --strict)",
    ),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if warnings or errors are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Verify entries against authoritative metadata (accepts multiple files).

    Checks DOI-backed entries against provider metadata; with ``--published`` it
    also reports preprints that now have a published version available.
    """
    _run_checks(
        files,
        "verify",
        lambda f: _verify_one(f, online, cache_dir, strict, published),
        json_output,
        strict,
    )


def enrich(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    online: bool = typer.Option(
        False,
        "--online",
        help="Fetch DOI provider metadata; otherwise only local DOI URLs are used",
    ),
    published: bool = typer.Option(
        False,
        "--published",
        help="Also promote preprints to their published version, writing the "
        "published DOI/journal when one is available (use with --online)",
    ),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively fill missing metadata.

    Fills missing DOI/date/identifier fields; with ``--published`` it also
    promotes preprints to their published version (writing the published
    DOI/journal), folding in the former ``published --apply`` operation.
    """
    coll = Bibliography.open(file)
    cache = _metadata_cache_dir(file, cache_dir, online)
    report = coll.enrich(online=online, cache_dir=cache)
    updates = list(report.updates)
    warnings = list(report.warnings)
    extra: dict[str, object] = {}
    verb = "Would enrich" if dry_run else "Enriched"
    human = [
        f"{verb} {report.changed_entries} {_entries(report.changed_entries)}.",
        f"  field_updates={report.changed_fields}",
    ]
    if published:
        preprints = coll.apply_published(online=online, cache_dir=cache)
        updates += preprints.updates
        warnings += preprints.warnings
        extra["preprints"] = {
            "checked": preprints.checked,
            "published": preprints.published,
            "updates": [update.to_dict() for update in preprints.updates],
        }
        human.append(f"  promoted {preprints.changed_entries} preprint(s) to a published version")
    _finish_mod(
        file,
        "enrich",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=warnings,
        changed_entries=len({update.key for update in updates}),
        changed_fields=len(updates),
        updates=[update.to_dict() for update in updates],
        **extra,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(verify))
    app.command()(_safe(enrich))
