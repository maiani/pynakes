"""CLI command registration for ``pynakes asset fetch``.

Downloads arXiv materials (PDF and source) into the configured Pinax directory.
"""

from enum import Enum

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)

from pynakes.cli_choices import Material
from pynakes.cli_commands._fetch_report import fetch_report_lines
from pynakes.cli_commands._rich_progress import RichProgressBase
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
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


class _RichFetchProgress(RichProgressBase):
    """Render Pinax fetch progress to stderr for human CLI runs."""

    def __init__(self) -> None:
        super().__init__(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
        )
        self._tasks: dict[tuple[str, FetchArtifact], object] = {}

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


#: The fetch-policy flag each ``--material`` sets.
MATERIALS = {
    Material.PREPRINT: "preprint",
    Material.PUBLISHED: "published",
    Material.SOURCE: "source",
    Material.SUPPLEMENT: "supplement",
    Material.BEST_PDF: "bestpdf",
}


def fetch(
    file: str | None = bib_file_argument(),
    target: str | None = typer.Argument(
        None, help="Citation key to fetch (default: all entries with configured missing materials)"
    ),
    material: list[Material] | None = typer.Option(
        None,
        "--material",
        help="Material to fetch, repeatable; overrides the library's pinax-fetch-policy. "
        "best-pdf is the published PDF when open access, otherwise the preprint; "
        "supplement fetches one unambiguous supplementary PDF",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
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
    fetched.
    """
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    if target is not None and not target.strip():
        # A blank key (an unset variable in a script) means "no key", not a
        # lookup for the empty key.
        target = None
    file = _resolve_input_bib(file, json_output)

    try:
        coll = Bibliography.open(file)
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))

    chosen = {MATERIALS[name] for name in material or []}
    policy = (
        FetchPolicy(**{flag: flag in chosen for flag in MATERIALS.values()}) if chosen else None
    )
    _check_expected_sha256(file, coll, params)

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

    human = fetch_report_lines(report)

    if coll.files is not None:
        files_dir = str(coll.files.root)
        human.append(f"Files stored in {files_dir}")
    else:
        files_dir = None

    _finish_mod(
        file,
        "asset_fetch",
        coll,
        params,
        human,
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
