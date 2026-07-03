"""CLI command registration for ``pynakes asset fetch``.

Downloads arXiv materials (PDF and source) for entries into the Pinax files-dir.
"""

from types import TracebackType

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)

from pynakes.cli_commands._fetch_report import fetch_report_lines
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _metadata_cache_dir,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.fetch_progress import FetchArtifact, FetchProgressEvent

_ARTIFACT_LABELS: dict[FetchArtifact, str] = {
    "preprint_pdf": "preprint PDF",
    "preprint_source": "preprint source",
    "published_pdf": "published PDF",
}


class _RichFetchProgress:
    """Render Pinax fetch progress to stderr for human CLI runs."""

    def __init__(self) -> None:
        console = Console(stderr=True)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            disable=not console.is_terminal,
        )
        self._tasks: dict[tuple[str, FetchArtifact], object] = {}

    def __enter__(self) -> "_RichFetchProgress":
        self._progress.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._progress.__exit__(exc_type, exc, traceback)

    def __call__(self, event: FetchProgressEvent) -> None:
        if event.kind == "fail" and event.artifact is None:
            self._remove_key_tasks(event.key)
            return
        if event.artifact is None:
            return
        ident = (event.key, event.artifact)
        if event.kind == "artifact_start":
            label = _ARTIFACT_LABELS[event.artifact]
            self._tasks[ident] = self._progress.add_task(
                f"{event.key}: {label}", total=event.total_bytes
            )
        elif event.kind == "artifact_progress":
            task_id = self._tasks.get(ident)
            if task_id is None:
                return
            update: dict[str, object] = {"advance": event.advance}
            if event.total_bytes is not None:
                update["total"] = event.total_bytes
            self._progress.update(task_id, **update)
        elif event.kind in {"artifact_done", "fail"}:
            task_id = self._tasks.pop(ident, None)
            if task_id is not None:
                if event.total_bytes is not None:
                    self._progress.update(
                        task_id, total=event.total_bytes, completed=event.total_bytes
                    )
                self._progress.remove_task(task_id)

    def _remove_key_tasks(self, key: str) -> None:
        for ident, task_id in list(self._tasks.items()):
            if ident[0] == key:
                self._tasks.pop(ident, None)
                self._progress.remove_task(task_id)


def fetch(
    target: str | None = typer.Argument(
        None, help="Citation key to fetch (default: all entries with configured missing materials)"
    ),
    file: str | None = bib_file_argument(),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be fetched without downloading"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    cache_dir: str | None = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Download materials (arXiv PDF/source and/or open-access published PDFs)."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)

    try:
        coll = Bibliography.open(file)
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))

    cache = _metadata_cache_dir(file, cache_dir, True)
    if params.json_output:
        report = coll.fetch_materials(target=target, dry_run=params.dry_run, cache_dir=cache)
    else:
        with _RichFetchProgress() as progress:
            report = coll.fetch_materials(
                target=target, dry_run=params.dry_run, cache_dir=cache, progress=progress
            )

    warnings = fetch_report_lines(report)

    if coll.files is not None:
        files_dir = str(coll.files.root)
        warnings.append(f"Files stored in {files_dir}")
    else:
        files_dir = None

    _finish_mod(
        file,
        "fetch",
        coll,
        params,
        warnings,
        files_dir=files_dir,
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
