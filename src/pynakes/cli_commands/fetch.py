"""CLI command registration for ``pynakes asset fetch``.

Downloads arXiv materials (PDF and source) into the configured Pinax directory.
"""

from enum import Enum
from pathlib import Path
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
    _CACHE_FILE_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.fetch_progress import FetchArtifact, FetchProgressEvent
from pynakes.metadata import FetchPolicy

_ARTIFACT_LABELS: dict[FetchArtifact, str] = {
    "preprint_pdf": "preprint PDF",
    "preprint_source": "preprint source",
    "published_pdf": "published PDF",
    "supplement_pdf": "supplement PDF",
}


class FetchAccess(str, Enum):
    """Access context used for publisher-hosted materials."""

    OPEN = "open"
    INSTITUTIONAL = "institutional"


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
        elif event.kind in {"artifact_done", "artifact_skip", "fail"}:
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


def _looks_like_bib_path(target: str | None) -> bool:
    """Return whether ``target`` is a path to an existing ``.bib`` file.

    A citation key is never also a ``.bib`` file on disk, so this distinguishes
    ``asset fetch refs.bib`` (a mis-typed whole-library run) from
    ``asset fetch Newton1687`` without guessing.
    """
    return target is not None and target.lower().endswith(".bib") and Path(target).is_file()


def fetch(
    target: str | None = typer.Argument(
        None, help="Citation key to fetch (default: all entries with configured missing materials)"
    ),
    file: str | None = bib_file_argument(),
    file_option: str | None = typer.Option(
        None, "--file", help="Library path when the citation-key argument is omitted"
    ),
    preprint: bool | None = typer.Option(
        None, "--preprint", help="Fetch preprint PDF (overrides metadata pinax-fetch-policy)"
    ),
    published: bool | None = typer.Option(
        None, "--published", help="Fetch published PDF (overrides metadata pinax-fetch-policy)"
    ),
    source: bool | None = typer.Option(
        None, "--source", help="Fetch arXiv source (overrides metadata pinax-fetch-policy)"
    ),
    supplement: bool | None = typer.Option(
        None, "--supplement", help="Fetch one unambiguous supplementary PDF"
    ),
    bestpdf: bool | None = typer.Option(
        None,
        "--bestpdf",
        help=(
            "Best available PDF: published if OA, otherwise preprint "
            "(overrides metadata pinax-fetch-policy)"
        ),
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be fetched without downloading"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    cache_file: str | None = _CACHE_FILE_OPTION,
    access: FetchAccess = typer.Option(
        FetchAccess.OPEN,
        "--access",
        help="Publisher access context: open or institutional (uses existing network access)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Download Pinax materials, optionally using existing institutional network access.

    With no citation key every entry with configured missing materials is
    fetched. Since the key comes first positionally, name the library with
    ``--file`` for that whole-library form (``asset fetch --file refs.bib``);
    the positional library path is for the single-key form
    (``asset fetch KEY refs.bib``).
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    if file is not None and file_option is not None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Specify the library once, not both positionally and with --file",
        )
    if target is not None and not target.strip():
        # A blank key (an unset variable in a script) means "no key", not a
        # lookup for the empty key.
        target = None
    if file is None and file_option is None and _looks_like_bib_path(target):
        _emit_error(
            json_output,
            "InvalidInput",
            f"The first argument is a citation key, not a library path; "
            f"use --file {target} to fetch every entry in that library",
        )
    file = _resolve_input_bib(file_option or file, json_output)

    try:
        coll = Bibliography.open(file)
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))

    flags = [preprint, published, source, supplement, bestpdf]
    policy = (
        FetchPolicy(
            preprint=bool(preprint),
            published=bool(published),
            source=bool(source),
            supplement=bool(supplement),
            bestpdf=bool(bestpdf),
        )
        if any(f is not None for f in flags)
        else None
    )

    if params.json_output:
        report = coll.fetch_materials(
            target=target,
            policy=policy,
            dry_run=params.dry_run,
            cache_file=cache_file,
            access=access.value,
        )
    else:
        with _RichFetchProgress() as progress:
            report = coll.fetch_materials(
                target=target,
                policy=policy,
                dry_run=params.dry_run,
                cache_file=cache_file,
                progress=progress,
                access=access.value,
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
        access=report["access"],
        fetch_policy=report["fetch_policy"],
        fetched=report["fetched"],
        skipped=report["skipped"],
        failed=report["failed"],
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("fetch")(_safe(fetch))
