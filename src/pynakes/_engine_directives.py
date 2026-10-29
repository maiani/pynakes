"""Staging per-entry directives and comments on a Bibliography.

A directive (see :mod:`pynakes.directives`) is a comment line directly above its
entry; an entry comment is a ``%`` line there holding free text for people. Adding
one inserts a line at the start of the entry's source span; removing one deletes
its comment slot; changing a directive rewrites the slot in place. No entry's own
text changes, and nothing else in the file moves.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pynakes._entry_comments import attached_comment_indices
from pynakes.directives import (
    EntryDirective,
    directive_problem,
    entry_directives,
    format_directive,
    parse_directive,
)
from pynakes.model import BibEntry, BibFile

if TYPE_CHECKING:
    from pynakes._engine_helpers import SourceSnapshot

_COMMENT_BLOCK = re.compile(r"^@comment\s*[{(](.*)[})]\s*$", re.IGNORECASE | re.DOTALL)


class BibliographyDirectives:
    """Mixin adding directive staging to :class:`~pynakes.engine.Bibliography`."""

    if TYPE_CHECKING:
        lib: BibFile
        _removed_comments: set[int]
        _source_snapshot: SourceSnapshot
        _directive_insertions: list[tuple[BibEntry, str]]

    def entry_directives(self, key: str) -> list[EntryDirective]:
        """Return the directives attached above the unique entry ``key``."""
        return entry_directives(self.lib).get(id(self._directive_entry(key)), [])

    def add_entry_directive(
        self, key: str, verb: str, args: tuple[str, ...] = (), reason: str | None = None
    ) -> bool:
        """Stage ``% pynakes: verb args -- reason`` above entry ``key``.

        Arguments an existing directive of the same verb already carries are not
        repeated; when every one is already there, only a changed ``reason`` is
        written. Returns whether anything was staged. Raises ``ValueError`` for a
        directive pynakes cannot act on, ``KeyError`` for an unknown key.
        """
        problem = directive_problem(EntryDirective(verb, args))
        if problem is not None:
            raise ValueError(problem)
        entry = self._directive_entry(key)
        same = [d for d in self.entry_directives(key) if d.verb == verb]
        present = {arg.lower() for directive in same for arg in directive.args}
        missing = tuple(arg for arg in args if arg.lower() not in present)
        if missing or not same:
            self._insert_directive(entry, format_directive(verb, missing or args, reason))
            return True
        changed = False
        wanted = {arg.lower() for arg in args}
        for directive in same:
            covers = not wanted or wanted & {arg.lower() for arg in directive.args}
            if covers and reason is not None and directive.reason != reason:
                self._rewrite_directive(directive, directive.args, reason)
                changed = True
        return changed

    def remove_entry_directive(self, key: str, verb: str, args: tuple[str, ...] = ()) -> int:
        """Stage removal of ``args`` from entry ``key``'s ``verb`` directives.

        With no ``args``, every ``verb`` directive above the entry goes. A
        directive left with no arguments is removed outright. Returns how many
        directive lines were removed or rewritten.
        """
        targets = {arg.lower() for arg in args}
        changed = 0
        for directive in self.entry_directives(key):
            if directive.verb != verb:
                continue
            keep = tuple(arg for arg in directive.args if arg.lower() not in targets)
            if targets and len(keep) == len(directive.args):
                continue
            if targets and keep:
                self._rewrite_directive(directive, keep, directive.reason)
            else:
                self._drop_directive(directive)
            changed += 1
        return changed

    def entry_comments(self, key: str) -> list[tuple[int, str]]:
        """Return ``(slot, text)`` for each free comment attached above entry ``key``.

        Directives and metadata blocks are not free comments. The text drops the
        ``%`` marker or the ``@comment`` wrapper and surrounding space.
        """
        entry = self._directive_entry(key)
        result: list[tuple[int, str]] = []
        for index in attached_comment_indices(self.lib).get(id(entry), []):
            raw = self.lib.raw_comments[index]
            if parse_directive(raw) is None:
                result.append((index, _comment_text(raw)))
        return result

    def add_entry_comment(self, key: str, text: str) -> bool:
        """Stage ``% text`` directly above entry ``key``, where it moves with the entry.

        A comment already attached with the same text is not repeated. Returns
        whether anything was staged. Raises ``ValueError`` for text that cannot be
        a comment line, ``KeyError`` for an unknown key.
        """
        problem = comment_problem(text)
        if problem is not None:
            raise ValueError(problem)
        text = text.strip()
        if any(existing == text for _index, existing in self.entry_comments(key)):
            return False
        self._insert_directive(self._directive_entry(key), f"% {text}")
        return True

    def remove_entry_comment(self, key: str, text: str) -> int:
        """Stage removal of entry ``key``'s attached comments reading ``text``.

        Returns how many comment lines were removed.
        """
        text = text.strip()
        removed = 0
        for index, existing in self.entry_comments(key):
            if existing == text:
                self.lib.raw_comments[index] = ""
                self._removed_comments.add(index)
                removed += 1
        return removed

    # --- internals -------------------------------------------------------

    def _directive_entry(self, key: str) -> BibEntry:
        matches = self.lib.entries.get_all(key)
        if not matches:
            raise KeyError(key)
        if len(matches) != 1:
            raise ValueError(f"Citation key {key!r} is duplicated; repair duplicates first")
        return matches[0]

    def _insert_directive(self, entry: BibEntry, line: str) -> None:
        if self._source_snapshot.entries.get(id(entry)) is None:
            raise RuntimeError("directives can only be added to a library read from its source")
        self._directive_insertions.append((entry, line))

    def _rewrite_directive(
        self, directive: EntryDirective, args: tuple[str, ...], reason: str | None
    ) -> None:
        index = _slot(directive)
        old = self.lib.raw_comments[index]
        body = format_directive(directive.verb, args, reason, marker=False)
        if old.lstrip().startswith("@"):
            self.lib.raw_comments[index] = f"@comment{{{body}}}"
        else:
            ending = old[len(old.rstrip("\r\n")) :]
            self.lib.raw_comments[index] = f"% {body}{ending}"

    def _drop_directive(self, directive: EntryDirective) -> None:
        index = _slot(directive)
        self.lib.raw_comments[index] = ""
        self._removed_comments.add(index)


def _slot(directive: EntryDirective) -> int:
    if directive.comment_index is None:
        raise RuntimeError("directive has no comment slot")
    return directive.comment_index


def comment_problem(text: str) -> str | None:
    """Return why ``text`` cannot be an entry comment, or ``None`` when it can."""
    body = text.strip()
    if not body:
        return "the comment text is empty"
    if "\n" in body or "\r" in body:
        return "the comment must be a single line"
    if "@" in body:
        # BibTeX reads no comment syntax between entries: an @ would start one.
        return "the comment cannot contain '@', which BibTeX reads as the start of an entry"
    if body.lower().startswith("pynakes"):
        return (
            "a comment starting with 'pynakes' reads as a directive or metadata; use ref directive"
        )
    return None


def _comment_text(raw: str) -> str:
    body = raw.strip()
    if body.startswith("%"):
        return body.lstrip("%").strip()
    block = _COMMENT_BLOCK.match(body)
    return block.group(1).strip() if block else body
