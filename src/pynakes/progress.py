"""Generic per-entry progress events for whole-library CLI passes.

Any operation that walks every entry in a library once — online verify/enrich,
a future lint or dedupe pass over a large file — can report progress with this
single event shape rather than defining its own. Contrast with
:mod:`pynakes.fetch_progress`, whose ``FetchProgressEvent`` also tracks
per-artifact byte counts and multiple event kinds; that richer shape stays
specific to Pinax material fetching.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["EntryProgressEvent", "EntryProgress"]


@dataclass(frozen=True)
class EntryProgressEvent:
    """One entry visited during a whole-library pass.

    ``entry_index``/``entry_total`` place the current entry within the whole
    library being processed, regardless of whether this particular entry
    triggers any actual work (e.g. a network lookup).
    """

    key: str
    entry_index: int
    entry_total: int


EntryProgress = Callable[[EntryProgressEvent], None]
