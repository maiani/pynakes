"""Scrub non-entry source blocks without rebuilding the bibliography."""

import re
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from pynakes.scrub import ScrubOptions, ScrubReport

from pynakes._engine_source import SourceSpan, SpanEdit, _source_block_raw
from pynakes.model import BibFile

# Recognizable local paths only: ordinary bibliographic notes stay intact.
LOCAL_PATH = re.compile(r"file://|(?:^|[\s{=:])(?:/home/|/Users/|~/|[A-Za-z]:[\\/])", re.I)


def scrub_source(
    lib: BibFile,
    report: "ScrubReport",
    *,
    comments: bool,
    fields: bool,
    original: BibFile | None = None,
) -> list[SpanEdit]:
    edits: list[SpanEdit] = []
    cursor = 0
    layout = []
    source = original or lib
    for index, (gap, kind, ref) in enumerate(lib.source_layout):
        original_gap, original_kind, original_ref = source.source_layout[index]
        original_raw = _source_block_raw(source, original_kind, original_ref) or ""
        raw = _source_block_raw(lib, kind, ref) or ""
        new_gap = gap
        if comments and gap.strip():
            new_gap = "".join(char for char in gap if char.isspace())
            edits.append(
                SpanEdit(SourceSpan(cursor, cursor + len(original_gap), original_gap), new_gap)
            )
            report.comments += 1
        cursor += len(original_gap)
        if fields and kind in {"string", "preamble", "raw"} and LOCAL_PATH.search(raw):
            edits.append(SpanEdit(SourceSpan(cursor, cursor + len(original_raw), original_raw), ""))
            report.comments += 1
            if kind == "string":
                lib.raw_strings[cast(int, ref)] = ""
                match = re.match(r"@string\s*[{(]\s*([^=\s]+)", raw, re.I)
                if match:
                    lib.strings.pop(match[1], None)
            elif kind == "preamble":
                lib.preamble[cast(int, ref)] = ""
            else:
                ref = ""
        layout.append((new_gap, kind, ref))
        cursor += len(original_raw)
    trailing = lib.source_trailing
    if comments and trailing.strip():
        replacement = "".join(char for char in trailing if char.isspace())
        edits.append(
            SpanEdit(
                SourceSpan(cursor, cursor + len(source.source_trailing), source.source_trailing),
                replacement,
            )
        )
        lib.source_trailing = replacement
        report.comments += 1
    lib.source_layout = layout
    return edits


class _ScrubBuffer(Protocol):
    lib: BibFile
    _pristine_text: str
    _scrub_edits: list[SpanEdit]
    _removed_comments: set[int]


def stage_scrub(coll: _ScrubBuffer, options: "ScrubOptions | None" = None) -> "ScrubReport":
    """Stage model removals and non-entry edits against the original source."""
    from pynakes import scrub as scrub_ops
    from pynakes.bibtex_parser import parse_bib

    opts = options or scrub_ops.ScrubOptions()
    source_report = scrub_ops.ScrubReport()
    coll._scrub_edits.extend(
        scrub_source(
            coll.lib,
            source_report,
            comments=scrub_ops._resolve_switch(
                coll.lib, opts.comments, scrub_ops.SCRUB_COMMENTS_KEY
            ),
            fields=bool(scrub_ops.resolve_private_fields(coll.lib, opts))
            and "*" not in scrub_ops.resolve_keep_fields(coll.lib, opts),
            original=parse_bib(coll._pristine_text) if coll._pristine_text else None,
        )
    )
    report = scrub_ops.scrub_library(coll.lib, options)
    report.comments += source_report.comments
    coll._removed_comments.update(report.removed_comment_indices)
    return report
