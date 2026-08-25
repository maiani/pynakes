"""Shared Rich progress-bar scaffolding for online CLI passes.

Both ``asset fetch`` and the online ``verify``/``enrich`` family render a
transient stderr progress bar while walking a bibliography. This factors out
the ``Console``/``Progress`` construction and context-manager delegation each
one needs, leaving each renderer to supply only its own columns and its
event-handling ``__call__``.
"""

from __future__ import annotations

from types import TracebackType

from rich.console import Console
from rich.progress import Progress, ProgressColumn


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
