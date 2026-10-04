"""Comments that belong to the entry directly below them.

A comment written directly above an entry — an ``@comment`` block or a ``%``
line, with no blank line between it and the entry — describes that entry rather
than the file: a note about the work, or a directive another tool reads, such as
a linter suppression that applies to the next entry. Operations that remove or
reorder entries carry such a run of comments along with its entry, so a comment
never silently lands on a different entry. A blank line ends the run; a comment
separated from the next entry by one stays where it is, a file-level comment.

Metadata blocks (``jabref-meta``/``pynakes-meta``) never attach: they describe
the library, and their placement is the formatter's to decide.

Attachment is read from a parsed library's source layout. A library derived from
another (:meth:`pynakes.model.BibFile.derive`) has no layout of its own, so it
carries the comment text of its entries' runs instead; see :func:`detach_into`.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynakes.model import BibEntry, BibFile


def attached_comment_indices(lib: BibFile) -> dict[int, list[int]]:
    """Map ``id(entry)`` to the ``raw_comments`` indices attached above it.

    Each list is in source order. Entries with no attached comment are absent.
    Read from ``lib.source_layout``, so an in-memory library has none.
    """
    metadata = {block.comment_index for block in lib.metadata_blocks}
    attached: dict[int, list[int]] = {}
    run: list[int] = []
    for gap, kind, ref in lib.source_layout:
        if run and not _adjacent(lib.raw_comments[run[-1]], gap):
            run = []
        if kind == "comment" and isinstance(ref, int):
            text = lib.raw_comments[ref] if ref < len(lib.raw_comments) else ""
            run = [*run, ref] if text.strip() and ref not in metadata else []
        elif kind == "entry":
            if run:
                attached[id(ref)] = run
            run = []
        else:
            run = []
    return attached


def entry_comments(lib: BibFile) -> tuple[dict[int, list[str]], set[int]]:
    """Return the comment text attached to each present entry, and its indices.

    The first item maps ``id(entry)`` to the comment texts to emit directly above
    it. The second holds the ``raw_comments`` indices those texts came from, which
    a writer must therefore not emit elsewhere. A comment attached to an entry no
    longer in the library is not in either: it is emitted as a free comment,
    never dropped.
    """
    present = {id(entry) for entry in lib.entries.values()}
    texts: dict[int, list[str]] = {}
    indices: set[int] = set()
    for entry_id, run in attached_comment_indices(lib).items():
        if entry_id in present:
            texts[entry_id] = [lib.raw_comments[index] for index in run]
            indices.update(run)
    for entry_id, carried in lib._entry_comments.items():
        if entry_id in present:
            texts.setdefault(entry_id, list(carried))
    return texts, indices


def detach_into(source: BibFile, derived: BibFile) -> None:
    """Carry *source*'s attached comments into *derived*, a library made from it.

    Comments attached to an entry *derived* kept travel with it as text; those
    attached to an entry it dropped go with that entry. Either way the slot is
    blanked in *derived*'s ``raw_comments`` (indices stay stable for metadata
    blocks), so no copy is also emitted as a free comment.
    """
    kept = {id(entry) for entry in derived.entries.values()}
    carried = dict(source._entry_comments)
    for entry_id, run in attached_comment_indices(source).items():
        if entry_id in kept:
            carried[entry_id] = tuple(source.raw_comments[index] for index in run)
        for index in run:
            derived.raw_comments[index] = ""
    derived._entry_comments = {key: value for key, value in carried.items() if key in kept}


def carry_from(source: BibFile, derived: BibFile) -> None:
    """Add the attached comments of *derived*'s entries that came from *source*.

    For a library built from several sources (``corpus combine``), whose
    ``raw_comments`` come from only one of them.
    """
    kept = {id(entry) for entry in derived.entries.values()}
    texts, _indices = entry_comments(source)
    carried = dict(derived._entry_comments)
    for entry_id, run in texts.items():
        if entry_id in kept:
            carried.setdefault(entry_id, tuple(run))
    derived._entry_comments = carried


def comment_texts(lib: BibFile) -> list[str]:
    """Every comment *lib* writes: its ``raw_comments`` plus any carried as text."""
    present = {id(entry) for entry in lib.entries.values()}
    carried = [
        text for entry_id, run in lib._entry_comments.items() if entry_id in present for text in run
    ]
    return [*lib.raw_comments, *carried]


def attachment_signature(lib: BibFile) -> Counter[tuple[str, tuple[str, ...]]]:
    """Count ``(key, attached comment texts)`` pairs, for formatter validation."""
    texts, _indices = entry_comments(lib)
    return Counter(
        (entry.key, tuple(text.strip() for text in texts.get(id(entry), [])))
        for entry in lib.entries.values()
    )


def with_comments(entry: BibEntry, text: str, texts: dict[int, list[str]], le: str) -> str:
    """Return *text* (an entry's rendering) preceded by its attached comments."""
    run = [comment.strip("\r\n") for comment in texts.get(id(entry), [])]
    return le.join([*run, text]) if run else text


def _adjacent(comment: str, gap: str) -> bool:
    """Whether *gap* joins *comment* to the next block: whitespace, no blank line.

    A ``%`` comment's text ends with its own newline, which counts toward the gap.
    """
    newlines = gap.count("\n") + comment.endswith("\n")
    return not gap.strip() and newlines < 2
