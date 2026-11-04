"""Insert new entries in the declared order without rewriting existing source."""

from pynakes._engine_helpers import append_entry_text
from pynakes._engine_source import SourceSpan, SpanEdit, apply_span_edits, snapshot_source_spans
from pynakes._entry_comments import attached_comment_indices
from pynakes._normalize_sort import _entry_sort_key, _resolve_sort_criteria
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.model import BibEntry, BibFile


def add_entry_ordered(lib: BibFile, entry: BibEntry) -> None:
    """Add after the last entry sorting before or equal to the new entry.

    The existing sort-order setting (including its JabRef alias) is the policy;
    absent or original order keeps append behavior. Existing entries never move.
    """
    criteria = _resolve_sort_criteria(lib, None)
    existing = list(lib.entries.values())
    lib.entries.add(entry)
    if not criteria:
        return
    position = 0
    for index, other in enumerate(existing):
        for name, descending in criteria:
            left, right = _entry_sort_key(other, name), _entry_sort_key(entry, name)
            if left != right:
                precedes = left > right if descending else left < right
                break
        else:
            precedes = True  # stable ties
        if precedes:
            position = index + 1
    # A duplicate key must never displace the record a citation already reads.
    for index, other in enumerate(existing):
        if other.key == entry.key:
            position = max(position, index + 1)
    existing.insert(position, entry)
    lib.entries.set_order(existing)


def insert_added_entries(text: str, lib: BibFile, added: list[BibEntry]) -> str:
    """Splice additions into their model positions, before attached comments.

    Parse the already-edited text to find current spans; edited fields and
    metadata can have changed their offsets since the pristine snapshot.
    """
    if not added:
        return text
    added_ids = {id(entry) for entry in added}
    parsed = parse_bib(text)
    spans = snapshot_source_spans(text, parsed)
    comments = attached_comment_indices(parsed)
    anchors = iter(parsed.entries.values())
    edits: list[SpanEdit] = []
    pending: list[str] = []
    le = lib.line_ending
    for entry in lib.entries.values():
        if id(entry) in added_ids:
            pending.append(write_bib(BibFile(entries=[entry], line_ending=le)).rstrip("\r\n"))
            continue
        anchor = next(anchors)
        if pending:
            start = spans.entries[id(anchor)].start
            attached = comments.get(id(anchor), [])
            if attached:
                start = spans.comments[attached[0]].start
            prefix = le * 2 if start and text[start - 1] not in "\r\n" else ""
            edits.append(
                SpanEdit(SourceSpan(start, start, ""), prefix + (le * 2).join(pending) + le * 2)
            )
            pending = []
    text = apply_span_edits(text, edits)
    for entry_text in pending:
        text = append_entry_text(text, entry_text, le, parsed.metadata_blocks)
    return text
