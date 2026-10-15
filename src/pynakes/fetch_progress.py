"""Progress events for Pinax material fetching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# The ``skipped`` reason a dry run records for an entry it *would* have
# fetched. Distinct from the genuine no-action reasons ("no DOI", "materials
# already present") so a reader can tell a plan from a non-event.
WOULD_FETCH = "would fetch"

FetchArtifact = Literal["preprint_pdf", "preprint_source", "published_pdf", "supplement_pdf"]
FetchProgressKind = Literal[
    "entry",
    "artifact_start",
    "artifact_progress",
    "artifact_done",
    "artifact_skip",
    "skip",
    "fail",
    "retry",
]


@dataclass(frozen=True)
class FetchProgressEvent:
    """One progress event emitted while fetching Pinax materials."""

    kind: FetchProgressKind
    key: str
    artifact: FetchArtifact | None = None
    entry_index: int | None = None
    entry_total: int | None = None
    advance: int = 0
    total_bytes: int | None = None
    message: str = ""
    #: For ``retry``: seconds the run waits before trying again, and the attempt that follows.
    retry_in: float | None = None
    attempt: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the event as one JSON Lines progress record, without empty values."""
        record: dict[str, object] = {"event": self.kind, "key": self.key}
        for name in (
            "artifact",
            "entry_index",
            "entry_total",
            "total_bytes",
            "retry_in",
            "attempt",
        ):
            value = getattr(self, name)
            if value is not None:
                record[name] = value
        if self.message:
            record["message"] = self.message
        return record


FetchProgress = Callable[[FetchProgressEvent], None]


def byte_progress(
    progress: FetchProgress | None,
    key: str,
    artifact: FetchArtifact,
) -> Callable[[int, int | None], None] | None:
    """Return a byte-count callback that reports ``artifact_progress`` events, or ``None``."""
    if progress is None:
        return None

    def callback(advance: int, total: int | None) -> None:
        progress(
            FetchProgressEvent(
                kind="artifact_progress",
                key=key,
                artifact=artifact,
                advance=advance,
                total_bytes=total,
            )
        )

    return callback


def emit_progress(
    progress: FetchProgress | None,
    kind: FetchProgressKind,
    key: str,
    artifact: FetchArtifact,
    *,
    total_bytes: int | None = None,
    message: str = "",
) -> None:
    """Send one artifact-level event to *progress*, when there is a listener."""
    if progress is None:
        return
    progress(
        FetchProgressEvent(
            kind=kind,
            key=key,
            artifact=artifact,
            total_bytes=total_bytes,
            message=message,
        )
    )
