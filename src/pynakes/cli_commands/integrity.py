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

from pynakes.cli_commands._rich_progress import RichProgressBase
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    CheckOutcome,
    RunParams,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _run_checks,
    _safe,
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
    strict: bool,
    published: bool,
    json_output: bool,
) -> CheckOutcome:
    coll = Bibliography.open(file)
    if online and not json_output:
        with _RichIntegrityProgress("Verifying") as progress:
            report = coll.verify(online=online, cache_file=cache_file, progress=progress)
    else:
        report = coll.verify(online=online, cache_file=cache_file)
    result = {
        "status": "success",
        "action": "verify",
        "file": file,
        "online": online,
        "strict": strict,
        **report.to_dict(),
    }
    if report.errors and report.checked == 0:
        result["note"] = "No DOIs could be verified — all lookups failed."
    human = [
        f"{file}: verified {report.checked} DOI-backed {_entries(report.checked)}.",
        f"  errors={report.errors}, warnings={report.warnings}, infos={report.infos}",
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
                    online=online, cache_file=cache_file, progress=progress
                )
        else:
            preprints = coll.published_check(online=online, cache_file=cache_file)
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
    cache_file: str | None = _CACHE_FILE_OPTION,
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if warnings or errors are found"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Verify entries against authoritative metadata (read-only).

    Checks DOI-backed entries against provider metadata; with ``--published`` it
    also reports preprints that now have a published version available.
    """
    _run_checks(
        files,
        "verify",
        lambda f: _verify_one(f, online, cache_file, strict, published, json_output),
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
    backup: bool = _BACKUP_OPTION,
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
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    if online and not json_output:
        with _RichIntegrityProgress("Enriching") as progress:
            report = coll.enrich(online=online, cache_file=cache_file, progress=progress)
    else:
        report = coll.enrich(online=online, cache_file=cache_file)
    updates = list(report.updates)
    warnings = list(report.warnings)
    extra: dict[str, object] = {}
    human = [
        f"{_verb('enrich', params, 'Enriched')} {report.changed_entries} {_entries(report.changed_entries)}.",
        f"  field_updates={report.changed_fields}",
    ]
    if published:
        if online and not json_output:
            with _RichIntegrityProgress("Checking preprints") as progress:
                preprints = coll.apply_published(
                    online=online, cache_file=cache_file, progress=progress
                )
        else:
            preprints = coll.apply_published(online=online, cache_file=cache_file)
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
