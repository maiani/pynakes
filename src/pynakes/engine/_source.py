"""Identity-aware source positions and surgical bibliography splicing."""

from dataclasses import dataclass
from typing import cast

from pynakes.model import BibEntry, BibFile


@dataclass(frozen=True)
class SourceSpan:
    """One exact block location in the pristine source text."""

    start: int
    end: int
    raw: str


@dataclass(frozen=True)
class SourceSnapshot:
    """Identity-aware source locations captured with a pristine engine state."""

    entries: dict[int, SourceSpan]
    raw_comments: tuple[str, ...]
    comments: dict[int, SourceSpan]
    complete: bool


@dataclass(frozen=True)
class SpanEdit:
    """Replace one pristine source span with ``replacement``."""

    span: SourceSpan
    replacement: str


def snapshot_source_spans(text: str, lib: BibFile) -> SourceSnapshot:
    """Capture exact entry/comment positions from ``lib.source_layout``.

    The layout retains entry object identity and raw-comment indices, so these
    spans remain unambiguous even when two blocks contain identical bytes.  An
    incomplete snapshot signals an in-memory library without a source layout;
    those libraries retain the explicit whole-model rendering path.
    """
    entry_spans: dict[int, SourceSpan] = {}
    comment_spans: dict[int, SourceSpan] = {}
    cursor = 0
    for gap, kind, ref in lib.source_layout:
        if text[cursor : cursor + len(gap)] != gap:
            return SourceSnapshot(entry_spans, tuple(lib.raw_comments), comment_spans, False)
        cursor += len(gap)
        raw = _source_block_raw(lib, kind, ref)
        if raw is None or text[cursor : cursor + len(raw)] != raw:
            return SourceSnapshot(entry_spans, tuple(lib.raw_comments), comment_spans, False)
        span = SourceSpan(cursor, cursor + len(raw), raw)
        if kind == "entry":
            entry_spans[id(ref)] = span
        elif kind == "comment":
            comment_spans[cast(int, ref)] = span
        cursor = span.end

    complete = text[cursor:] == lib.source_trailing
    return SourceSnapshot(entry_spans, tuple(lib.raw_comments), comment_spans, complete)


def _source_block_raw(lib: BibFile, kind: str, ref: object) -> str | None:
    if kind == "entry":
        return cast(BibEntry, ref).raw_content
    if kind == "comment":
        return lib.raw_comments[cast(int, ref)]
    if kind == "string":
        return lib.raw_strings[cast(int, ref)]
    if kind == "preamble":
        return lib.preamble[cast(int, ref)]
    if kind == "raw":
        return cast(str, ref)
    return None


def apply_span_edits(text: str, edits: list[SpanEdit]) -> str:
    """Apply validated, non-overlapping source edits from right to left."""
    ordered = sorted(edits, key=lambda edit: (edit.span.start, edit.span.end))
    previous_end = -1
    for edit in ordered:
        span = edit.span
        if span.start < previous_end:
            raise ValueError("overlapping surgical source edits")
        if span.start < 0 or span.end < span.start or span.end > len(text):
            raise ValueError("surgical source edit is outside the pristine text")
        if text[span.start : span.end] != span.raw:
            raise ValueError("surgical source edit no longer matches the pristine text")
        previous_end = span.end

    for edit in reversed(ordered):
        span = edit.span
        text = text[: span.start] + edit.replacement + text[span.end :]
    return text
