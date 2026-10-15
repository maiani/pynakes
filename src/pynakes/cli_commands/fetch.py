"""CLI command registration for ``pynakes asset fetch``.

Downloads arXiv materials (PDF and source) into the configured Pinax directory.
"""

import json
import sys
from enum import Enum

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from pynakes.cli_checks import strict_option
from pynakes.cli_choices import Material, ProgressStream
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
    key_option,
    select_keys,
    where_option,
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


class _DownloadOrCountColumn(DownloadColumn):
    """Bytes for a download task; ``done/total`` for the entry-queue task."""

    def render(self, task: Task) -> Text:
        if task.fields.get("entries"):
            return Text(f"{int(task.completed)}/{int(task.total or 0)} entries")
        return super().render(task)


class _SpeedColumn(TransferSpeedColumn):
    """Transfer speed for a download task; nothing for the entry-queue task."""

    def render(self, task: Task) -> Text:
        return Text("") if task.fields.get("entries") else super().render(task)


class _RichFetchProgress(RichProgressBase):
    """Render Pinax fetch progress to stderr for human CLI runs.

    One task tracks the entry queue, so a long run whose entries are mostly
    skipped (materials already present) still shows it is moving; each
    download gets its own byte-level task beneath it.
    """

    def __init__(self) -> None:
        super().__init__(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            _DownloadOrCountColumn(),
            _SpeedColumn(),
            TimeElapsedColumn(),
        )
        self._tasks: dict[tuple[str, FetchArtifact], object] = {}
        self._entries: TaskID | None = None

    def _track_entry(self, event: FetchProgressEvent) -> None:
        if not event.entry_total or not event.entry_index:
            return
        if self._entries is None:
            self._entries = self._progress.add_task(
                "Fetching", total=event.entry_total, entries=True
            )
        done = event.entry_index - (1 if event.kind == "entry" else 0)
        self._progress.update(self._entries, completed=done, description=f"Fetching: {event.key}")

    def __call__(self, event: FetchProgressEvent) -> None:
        self._track_entry(event)
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


class _JsonLinesProgress:
    """Write each fetch event as one JSON object per line on stderr (``--progress jsonl``).

    Byte-level ``artifact_progress`` events are left out: the stream says which
    entry and material the run is on, what each one came to, and when it waits
    to retry, not how many bytes each chunk held. Every line is flushed, so a
    reader sees it as soon as it is written, and stdout keeps the final envelope.
    """

    def __enter__(self) -> "_JsonLinesProgress":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __call__(self, event: FetchProgressEvent) -> None:
        if event.kind == "artifact_progress":
            return
        sys.stderr.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        sys.stderr.flush()


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
    discover: bool = typer.Option(
        False,
        "--discover",
        help="When a preprint is needed and the entry has a DOI but no arXiv id, look one up "
        "(OpenAlex, then Semantic Scholar), check it against arXiv's record, and use and "
        "record a confirmed id (eprint, only when the entry has none)",
    ),
    progress_stream: ProgressStream = typer.Option(
        ProgressStream.AUTO,
        "--progress",
        help="Progress while the run lasts: auto (a bar on a terminal, nothing with --json), "
        "jsonl (one JSON event per line on stderr, also with --json), or none",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    strict: bool = strict_option(
        "a requested material failed to download or was unavailable "
        "(materials already present pass)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Download Pinax materials, optionally using existing institutional network access.

    With no citation key every entry with configured missing materials is
    fetched; `--key` / `--where` fetch for the selected entries only. The
    result is reported in full either way; `coverage` says which requested
    PDFs are still missing and why, and `--strict` then exits 1 when the run
    was incomplete. Rerunning fetches only what is still missing.
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
    if target is not None and (where is not None or key):
        _emit_error(
            json_output, "InvalidInput", "Name one citation key or select with --key/--where"
        )
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
    selected = select_keys(coll, where, key, json_output, "asset_fetch")

    progress: _RichFetchProgress | _JsonLinesProgress | None = None
    if progress_stream is ProgressStream.JSONL:
        progress = _JsonLinesProgress()
    elif progress_stream is ProgressStream.AUTO and not params.json_output:
        progress = _RichFetchProgress()
    if progress is None:
        report = coll.fetch_materials(
            target=target,
            keys=selected,
            policy=policy,
            dry_run=params.dry_run,
            cache_file=cache_file,
            access=access.value,
            discover=discover,
        )
    else:
        with progress:
            report = coll.fetch_materials(
                target=target,
                keys=selected,
                policy=policy,
                dry_run=params.dry_run,
                cache_file=cache_file,
                progress=progress,
                access=access.value,
                discover=discover,
            )

    human = fetch_report_lines(report)
    summary = report["summary"]
    incomplete = bool(summary["failed"] or summary["unavailable"])

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
        warnings=report["warnings"],
        files_dir=files_dir,
        access=report["access"],
        fetch_policy=report["fetch_policy"],
        strict=strict,
        summary=summary,
        coverage=report["coverage"],
        complete=report["coverage"]["complete"] and not summary["failed"],
        fetched=report["fetched"],
        skipped=report["skipped"],
        failed=report["failed"],
        discovered=report["discovered"],
    )
    if strict and incomplete:
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("fetch")(_safe(fetch))
