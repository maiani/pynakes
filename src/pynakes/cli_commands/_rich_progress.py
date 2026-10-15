"""Shared Rich progress-bar scaffolding for online CLI passes.

Both ``asset fetch`` and the online ``verify``/``enrich`` family render a
transient stderr progress bar while walking a bibliography. This factors out
the ``Console``/``Progress`` construction and context-manager delegation each
one needs, leaving each renderer to supply only its own columns and its
event-handling ``__call__``.

Commands import this module only when they draw a bar, so the rest of the CLI
starts without loading Rich's progress machinery.
"""

from __future__ import annotations

from types import TracebackType

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from pynakes.fetch_progress import FetchArtifact, FetchProgressEvent
from pynakes.progress import EntryProgressEvent


class RichProgressBase:
    """Wrap one transient, stderr :class:`rich.progress.Progress` bar."""

    def __init__(self, *columns: ProgressColumn) -> None:
        console = Console(stderr=True)
        self._progress = Progress(
            *columns,
            console=console,
            transient=True,
            disable=not console.is_terminal,
        )

    def __enter__(self) -> "RichProgressBase":
        self._progress.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._progress.__exit__(exc_type, exc, traceback)


_ARTIFACT_LABELS: dict[FetchArtifact, str] = {
    "preprint_pdf": "preprint PDF",
    "preprint_source": "preprint source",
    "published_pdf": "published PDF",
    "supplement_pdf": "supplement PDF",
}


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


class RichFetchProgress(RichProgressBase):
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
        self._tasks: dict[tuple[str, FetchArtifact], TaskID] = {}
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
            if event.total_bytes is not None:
                self._progress.update(task_id, advance=event.advance, total=event.total_bytes)
            else:
                self._progress.update(task_id, advance=event.advance)
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


class RichIntegrityProgress(RichProgressBase):
    """Render an online verify/enrich pass's entry-by-entry progress to stderr.

    Mirrors ``asset fetch``'s :class:`RichFetchProgress`, scaled down to one task
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
        self._task_id: TaskID | None = None

    def __call__(self, event: EntryProgressEvent) -> None:
        description = f"{self._description}: {event.key}"
        if self._task_id is None:
            self._task_id = self._progress.add_task(description, total=event.entry_total)
        self._progress.update(self._task_id, completed=event.entry_index, description=description)
