"""Named selector queries saved in a library's ``pynakes-meta``.

A saved query is a name and a ``--where`` expression (see :mod:`pynakes.query`),
stored as one ``pynakes-meta`` line::

    @comment{pynakes-meta:
    query-to-read: abstract exists and not group "Read"
    }

The library stores the *query*, never its result: running it evaluates the
expression against the entries as they are now, so a saved query reflects
every later edit. Expressions are validated with the shared selector parser
when they are saved and again by ``lint``, so a query that no longer parses is
reported rather than silently selecting nothing.

The ``used`` / ``unused`` predicates resolve against the library's linked TeX
sources (``tex-sources``) when the query runs, and ``query "name"`` runs
another saved query in place. :func:`compile_selector` is the one place a
``--where`` expression is bound to a library, so every command that selects
entries understands both.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from pynakes._text_utils import check_balanced_braces, strip_meta_terminator
from pynakes.metadata.schema import SAVED_QUERY_PREFIX
from pynakes.model import BibEntry, BibFile
from pynakes.query import And, Node, Not, Or, SavedQueryRef, Used, parse_query
from pynakes.usage import (
    collect_cited_keys,
    resolve_existing_tex_sources,
    tex_sources_from_metadata,
)

__all__ = [
    "SAVED_QUERY_PREFIX",
    "NoCitationSourcesError",
    "SavedQuery",
    "compile_selector",
    "metadata_key",
    "query_uses_citations",
    "saved_queries",
    "saved_query",
    "saved_query_expressions",
    "select_entries",
    "validate_query_name",
    "validate_saved_query",
]

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class NoCitationSourcesError(ValueError):
    """A query tests ``used``/``unused`` but the library links no TeX sources."""


@dataclass(frozen=True)
class SavedQuery:
    """One saved query: its name and the selector expression it runs."""

    name: str
    expression: str

    def to_dict(self, saved: Mapping[str, str] | None = None) -> dict[str, object]:
        """Describe the query, including whether its expression still parses.

        ``saved`` (see :func:`saved_query_expressions`) resolves references to
        other saved queries, so a missing or circular one makes the query
        invalid; without it, references are only checked for syntax.
        """
        described: dict[str, object] = {"name": self.name, "expression": self.expression}
        try:
            node = parse_query(self.expression, cited_keys=(), saved=saved or _ANY_QUERY)
        except ValueError as exc:
            described.update(valid=False, error=str(exc), parsed=None, uses_citations=False)
        else:
            described.update(
                valid=True,
                error=None,
                parsed=node.to_dict(),
                uses_citations=query_uses_citations(node),
            )
        return described


def metadata_key(name: str) -> str:
    """Return the ``pynakes-meta`` key that stores query ``name``."""
    return f"{SAVED_QUERY_PREFIX}{validate_query_name(name)}"


def validate_query_name(name: str) -> str:
    """Return ``name`` stripped, or raise ``ValueError`` if it cannot name a query.

    A name starts with a letter or digit and continues with letters, digits,
    ``_``, ``.``, or ``-``, so it is one token on the metadata line and in a
    shell. Names compare case-insensitively, as metadata keys do.
    """
    stripped = name.strip()
    if not _NAME_RE.fullmatch(stripped):
        raise ValueError(
            f"Invalid query name {name!r}: use letters, digits, '_', '.', or '-', "
            "starting with a letter or digit"
        )
    return stripped


class _AnyQuery(Mapping[str, str]):
    """Stands in for a library's saved queries when only syntax is checked."""

    def __getitem__(self, name: str) -> str:
        return "*"

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


_ANY_QUERY = _AnyQuery()


def validate_saved_query(
    name: str, expression: str, saved: Mapping[str, str] | None = None
) -> Node:
    """Check a query before it is stored, returning its parsed expression.

    The expression must be one line (it is one metadata line), must keep
    ``{``/``}`` balanced (it lives inside an ``@comment``), and must parse
    under the shared selector grammar. With ``saved``, every ``query "name"``
    it refers to must exist there and must not lead back to ``name``; without
    it, references are checked only for syntax.

    Raises:
        ValueError: naming what is wrong with the name or the expression.
    """
    validate_query_name(name)
    text = strip_meta_terminator(expression).strip()
    if not text:
        raise ValueError(f"Saved query {name!r} needs an expression")
    if "\n" in text or "\r" in text:
        raise ValueError(f"Saved query {name!r} must be a single line")
    check_balanced_braces(f"saved query {name!r}", text)
    if saved is None:
        return parse_query(text, cited_keys=(), saved=_ANY_QUERY)
    # Resolve as if already stored, so a cycle through this name is caught.
    candidate = {**saved, name.strip().casefold(): text}
    ref = parse_query(f"query {_quoted(name.strip())}", cited_keys=(), saved=candidate)
    return ref.expression if isinstance(ref, SavedQueryRef) else ref


def saved_queries(lib: BibFile) -> list[SavedQuery]:
    """Return the library's saved queries, in the order the file declares them.

    Both metadata namespaces are read, with ``pynakes-meta`` taking precedence
    as it does for every key; a name declared twice is listed once, with its
    effective expression.
    """
    effective = {key.lower(): value for key, value in lib.metadata.items()}
    found: dict[str, SavedQuery] = {}
    for block in [*lib.pynakes_metadata_blocks, *lib.jabref_metadata_blocks]:
        lowered = block.key.strip().lower()
        if not lowered.startswith(SAVED_QUERY_PREFIX) or lowered in found:
            continue
        name = block.key.strip()[len(SAVED_QUERY_PREFIX) :]
        value = effective.get(block.key.lower(), block.value)
        found[lowered] = SavedQuery(name, strip_meta_terminator(value).strip())
    return list(found.values())


def saved_query(lib: BibFile, name: str) -> SavedQuery | None:
    """Return the saved query called ``name`` (case-insensitively), if any."""
    wanted = f"{SAVED_QUERY_PREFIX}{name.strip()}".lower()
    for query in saved_queries(lib):
        if f"{SAVED_QUERY_PREFIX}{query.name}".lower() == wanted:
            return query
    return None


def saved_query_expressions(lib: BibFile) -> dict[str, str]:
    """Map each saved query's case-folded name to its expression."""
    return {query.name.casefold(): query.expression for query in saved_queries(lib)}


def _quoted(name: str) -> str:
    # Names are restricted to [A-Za-z0-9_.-], which a double quote never breaks.
    return f'"{name}"'


def query_uses_citations(node: Node) -> bool:
    """Return whether ``node`` tests ``used`` or ``unused`` anywhere."""
    if isinstance(node, Used):
        return True
    if isinstance(node, SavedQueryRef):
        return query_uses_citations(node.expression)
    if isinstance(node, Not):
        return query_uses_citations(node.child)
    if isinstance(node, And | Or):
        return any(query_uses_citations(child) for child in node.children)
    return False


def select_entries(
    lib: BibFile,
    expression: str,
    *,
    base_dir: str | Path | None = None,
    cited_keys: Iterable[str] | None = None,
) -> tuple[list[BibEntry], list[dict]]:
    """Run ``expression`` against ``lib`` now, returning entries in file order.

    Every physical entry the expression accepts is returned, duplicated
    citation keys included. ``used``/``unused`` resolve against ``cited_keys``
    when given, else against the library's linked ``tex-sources`` (relative to
    ``base_dir``). The second item lists warnings — linked sources missing on
    disk — in the shape the CLI envelope reports.

    Raises:
        ValueError: if the expression does not parse.
        NoCitationSourcesError: if it tests citations and no sources are known.
    """
    node, warnings = compile_selector(lib, expression, base_dir=base_dir, cited_keys=cited_keys)
    return [entry for entry in lib.entries.values() if node(entry)], warnings


def compile_selector(
    lib: BibFile,
    expression: str,
    *,
    base_dir: str | Path | None = None,
    cited_keys: Iterable[str] | None = None,
) -> tuple[Node, list[dict]]:
    """Compile a ``--where`` expression against ``lib``, with its warnings.

    ``query "name"`` resolves against the library's saved queries.
    ``used``/``unused`` resolve against ``cited_keys`` when given, else
    against the library's linked ``tex-sources`` (relative to ``base_dir``) —
    scanned only when the expression actually tests citations. The warnings
    name linked sources missing on disk, in the shape the CLI envelope reports.

    Raises:
        ValueError: if the expression does not parse, or names a saved query
            that does not exist or refers back to itself.
        NoCitationSourcesError: if it tests citations and no sources are known.
    """
    saved = saved_query_expressions(lib)
    node = parse_query(expression, cited_keys=(), saved=saved)
    warnings: list[dict] = []
    if query_uses_citations(node):
        if cited_keys is None:
            cited_keys, warnings = _linked_cited_keys(lib, base_dir)
        node = parse_query(expression, cited_keys=cited_keys, saved=saved)
    return node, warnings


def _linked_cited_keys(lib: BibFile, base_dir: str | Path | None) -> tuple[set[str], list[dict]]:
    sources = tex_sources_from_metadata(lib, base_dir or ".")
    if not sources:
        raise NoCitationSourcesError(
            "This query tests 'used'/'unused', and the library links no TeX sources; "
            "link them with `pynakes tex add`"
        )
    existing, warnings = resolve_existing_tex_sources(sources)
    cited, include_all, _scanned = collect_cited_keys(existing)
    if include_all:
        cited = {entry.key for entry in lib.entries.values()}
    return cited, warnings
