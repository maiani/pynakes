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


FetchProgress = Callable[[FetchProgressEvent], None]
