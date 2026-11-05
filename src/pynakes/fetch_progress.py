"""Compatibility exports for material-fetch progress events.

New implementation code imports :mod:`pynakes.fetch.progress` directly.
"""

from pynakes.fetch.progress import (
    WOULD_FETCH,
    FetchArtifact,
    FetchProgress,
    FetchProgressEvent,
    FetchProgressKind,
    byte_progress,
    emit_progress,
)

__all__ = [
    "WOULD_FETCH",
    "FetchArtifact",
    "FetchProgress",
    "FetchProgressEvent",
    "FetchProgressKind",
    "byte_progress",
    "emit_progress",
]
