"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_commands._rich_progress import RichProgressBase
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    _CONCURRENCY_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.progress import EntryProgressEvent

# --- integrity / enrichment -------------------------------------------------


class _RichIntegrityProgress(RichProgressBase):
    """Render an online verify/enrich pass's entry-by-entry progress to stderr.

    Mirrors ``asset fetch``'s ``_RichFetchProgress``, scaled down to one task
    (there is no per-artifact byte count to track here): a spinner, a bar over
    the whole entry queue, and the current key in the description.
    """

    def __init__(self, description: str) -> None:
        super().__init__(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        self._description = description
        self._task_id: object = None

    def __call__(self, event: EntryProgressEvent) -> None:
        description = f"{self._description}: {event.key}"
        if self._task_id is None:
            self._task_id = self._progress.add_task(description, total=event.entry_total)
        self._progress.update(self._task_id, completed=event.entry_index, description=description)


def _verify_one(
    file: str,
    online: bool,
    cache_file: str | None,
    published: bool,
    json_output: bool,
    concurrency: int,
) -> CheckOutcome:
    coll = Bibliography.open(file)
    if online and not json_output:
        with _RichIntegrityProgress("Verifying") as progress:
            report = coll.verify(
                online=online, cache_file=cache_file, progress=progress, concurrency=concurrency
            )
    else:
        report = coll.verify(online=online, cache_file=cache_file, concurrency=concurrency)
    result = {
        "status": "success",
        "action": "verify",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [],
        "online": online,
        "summary": {
            "checked": report.checked,
            "errors": report.errors,
            "warnings": report.warnings,
            "info": report.infos,
        },
        "issues": [issue.to_dict() for issue in report.issues],
    }
    if report.errors and report.checked == 0:
        result["note"] = "No DOIs could be verified — all lookups failed."
    human = [
        f"{file}: verified {report.checked} DOI-backed {_entries(report.checked)}.",
        f"  errors={report.errors}, warnings={report.warnings}, info={report.infos}",
    ]
    if report.errors and report.checked == 0:
        human.append("  No DOIs could be verified — all lookups failed.")
    human += [f"  [{issue.severity}] {issue.key}: {issue.message}" for issue in report.issues]
    if published:
        # Read-only preprint check, folded in from the former `published` command.
        # Informational only: it never affects the --strict gate.
        if online and not json_output:
            with _RichIntegrityProgress("Checking preprints") as progress:
                preprints = coll.published_check(
                    online=online,
                    cache_file=cache_file,
                    progress=progress,
                    concurrency=concurrency,
                )
        else:
            preprints = coll.published_check(
                online=online, cache_file=cache_file, concurrency=concurrency
            )
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
            "info": report.infos,
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
    cache_file: str | None = _CACHE_FILE_OPTION,
    concurrency: int = _CONCURRENCY_OPTION,
    strict: bool = strict_option("verification finds warnings or errors"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Verify entries against authoritative metadata (read-only).

    Checks DOI-backed entries against provider metadata; with ``--published`` it
    also reports preprints that now have a published version available.
    """
    _run_checks(
        files,
        "verify",
        lambda f: _verify_one(f, online, cache_file, published, json_output, concurrency),
        json_output,
        strict,
    )


def enrich(
    file: str | None = bib_file_argument(),
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
    cache_file: str | None = _CACHE_FILE_OPTION,
    concurrency: int = _CONCURRENCY_OPTION,
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively fill missing metadata (modifies the file).

    Fills missing DOI/date/identifier fields; with ``--published`` it also
    promotes preprints to their published version (writing the published
    DOI/journal), folding in the former ``published --apply`` operation.
    """
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    # Before any provider is asked: a stale precondition should cost no lookup.
    _check_expected_sha256(file, coll, params)
    if online and not json_output:
        with _RichIntegrityProgress("Enriching") as progress:
            report = coll.enrich(
                online=online, cache_file=cache_file, progress=progress, concurrency=concurrency
            )
    else:
        report = coll.enrich(online=online, cache_file=cache_file, concurrency=concurrency)
    updates = list(report.updates)
    warnings = list(report.warnings)
    extra: dict[str, object] = {}
    detail: list[str] = []
    if published:
        if online and not json_output:
            with _RichIntegrityProgress("Checking preprints") as progress:
                preprints = coll.apply_published(
                    online=online,
                    cache_file=cache_file,
                    progress=progress,
                    concurrency=concurrency,
                )
        else:
            preprints = coll.apply_published(
                online=online, cache_file=cache_file, concurrency=concurrency
            )
        updates += preprints.updates
        warnings += preprints.warnings
        extra["preprints"] = {
            "checked": preprints.checked,
            "published": preprints.published,
            "promoted": preprints.promoted,
            "linked": preprints.linked,
            "updates": [update.to_dict() for update in preprints.updates],
        }
        # Two opposite directions of travel, counted apart. Reporting the
        # backfill as a promotion described the reverse of what it does.
        if preprints.promoted:
            detail.append(
                f"  promoted {preprints.promoted} "
                f"{_entries(preprints.promoted)} from preprint to published"
            )
        if preprints.linked:
            detail.append(
                f"  added arXiv preprint provenance to {preprints.linked} published "
                f"{_entries(preprints.linked)}"
            )
    # Counted over every update this command applied, preprint work included, so
    # the dry-run summary matches both the diff below it and the JSON envelope.
    changed_entries = len({update.key for update in updates})
    human = [
        f"{_verb('enrich', params, 'Enriched')} {changed_entries} {_entries(changed_entries)}.",
        f"  field_updates={len(updates)}",
        *detail,
    ]
    _finish_mod(
        file,
        "enrich",
        coll,
        params,
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
