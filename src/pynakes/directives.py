"""Per-entry directives: ``% pynakes: <verb> <args> [-- reason]`` above an entry.

A library's settings live in its ``pynakes-meta`` comment. A setting that
applies to one entry lives in a comment written directly above that entry, which
pynakes keeps with the entry wherever it moves (see :mod:`pynakes._entry_comments`)
and which BibTeX, Biber, and JabRef all leave alone::

    % pynakes: ignore missing_doi -- the venue assigns no DOIs
    @article{Newton1687,

The ``@comment{pynakes: ...}`` spelling is read too. A directive is a verb, its
comma-separated arguments, and an optional reason after `` -- ``; the reason is
for people and changes nothing. The verbs pynakes understands:

``ignore NAME[:FIELD], ...``
    ``lint`` leaves this entry's findings of finding type or category ``NAME``
    out of its report, limited to ``FIELD`` when one is given
    (``missing_profile_required_field:volume``).

A directive with an unknown verb or argument is reported by ``lint`` rather than
silently doing nothing, as is an ``ignore`` that no longer matches a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pynakes._entry_comments import attached_comment_indices
from pynakes._lint_issue import unknown_ignore_names
from pynakes.model import BibFile

__all__ = [
    "DIRECTIVE_VERBS",
    "EntryDirective",
    "directive_problem",
    "entry_directives",
    "format_directive",
    "parse_directive",
]

#: Verbs pynakes acts on, mapped to whether they take at least one argument.
DIRECTIVE_VERBS: dict[str, bool] = {"ignore": True}

_PREFIX = "pynakes:"
_COMMENT_BLOCK = re.compile(r"^@comment\s*[{(](.*)[})]\s*$", re.IGNORECASE | re.DOTALL)
_REASON_SEPARATOR = " -- "
_REASON_SPLIT = re.compile(r"\s+--(?:\s+|$)")


@dataclass(frozen=True)
class EntryDirective:
    """One parsed directive, and the comment slot it came from (when parsed)."""

    verb: str
    args: tuple[str, ...] = ()
    reason: str | None = None
    #: Index into ``BibFile.raw_comments``; ``None`` for a directive not yet written.
    comment_index: int | None = None

    def text(self) -> str:
        """Return the directive body, without the comment marker."""
        return format_directive(self.verb, self.args, self.reason, marker=False)


def parse_directive(comment: str) -> EntryDirective | None:
    """Parse one comment's text, or return ``None`` when it is not a directive.

    Accepts a ``%`` line or an ``@comment{...}`` block whose body starts with
    ``pynakes:`` (``pynakes-meta:`` is library metadata, not a directive). The
    verb is lowercased; arguments keep their spelling, minus surrounding space.
    """
    body = comment.strip()
    if body.startswith("%"):
        body = body.lstrip("%").strip()
    else:
        block = _COMMENT_BLOCK.match(body)
        if block is None:
            return None
        body = block.group(1).strip()
    if not body.lower().startswith(_PREFIX):
        return None
    body = body[len(_PREFIX) :].strip()
    body, *reason_part = _REASON_SPLIT.split(body, maxsplit=1)
    reason = reason_part[0].strip() or None if reason_part else None
    verb, _, rest = body.strip().partition(" ")
    args = tuple(part.strip() for part in rest.replace(",", " ").split() if part.strip())
    return EntryDirective(verb.strip().lower(), args, reason)


def format_directive(
    verb: str, args: tuple[str, ...] | list[str] = (), reason: str | None = None, *, marker=True
) -> str:
    """Return the canonical ``% pynakes: verb a, b -- reason`` line (no newline)."""
    text = f"{_PREFIX} {verb}"
    if args:
        text += " " + ", ".join(args)
    if reason:
        text += f"{_REASON_SEPARATOR}{reason}"
    return f"% {text}" if marker else text


def directive_problem(directive: EntryDirective) -> str | None:
    """Return why ``directive`` is invalid, or ``None`` when pynakes can act on it."""
    if directive.verb not in DIRECTIVE_VERBS:
        known = ", ".join(sorted(DIRECTIVE_VERBS))
        return f"unknown directive {directive.verb!r} (known: {known})"
    if DIRECTIVE_VERBS[directive.verb] and not directive.args:
        return f"directive {directive.verb!r} needs at least one argument"
    if directive.verb == "ignore":
        names = [arg.partition(":")[0] for arg in directive.args]
        unknown = unknown_ignore_names(names)
        if unknown:
            return f"'ignore' names no finding type or category: {', '.join(unknown)}"
        if any(arg.endswith(":") for arg in directive.args):
            return "'ignore' NAME:FIELD needs a field after the colon"
    return None


def entry_directives(lib: BibFile) -> dict[int, list[EntryDirective]]:
    """Map ``id(entry)`` to the directives attached above it, in source order.

    Only comments attached to the entry count: a directive separated from the
    entry below it by a blank line is a free comment and applies to nothing.
    """
    result: dict[int, list[EntryDirective]] = {}
    for entry_id, indices in attached_comment_indices(lib).items():
        for index in indices:
            parsed = parse_directive(lib.raw_comments[index])
            if parsed is not None:
                result.setdefault(entry_id, []).append(
                    EntryDirective(parsed.verb, parsed.args, parsed.reason, index)
                )
    return result
