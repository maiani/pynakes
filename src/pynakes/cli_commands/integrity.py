"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

from typing import Optional

import typer

from pynakes.cli_common import (
    CheckOutcome,
    _emit,
    _entries,
    _finish_mod,
    _metadata_cache_dir,
    _run_checks,
    _safe,
)
from pynakes.engine import Collection

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


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(verify))
    app.command()(_safe(enrich))
    app.command()(_safe(published))
