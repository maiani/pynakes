"""CLI command registration for bibliography search."""

import typer

from pynakes import search as search_ops
from pynakes.cli_common import (
    _emit_json,
    _entries,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
    build_where_filter,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.triage import abstract_excerpt


def search(
    query: str = typer.Argument(
        ...,
        help=(
            "Search query: words/phrases, optionally scoped as field:term or "
            'field:"phrase". Pass "" to select by --where alone'
        ),
    ),
    file: str | None = bib_file_argument(),
    field: list[str] | None = typer.Option(
        None,
        "--field",
        help="Restrict stored fields searched and returned; repeat for multiple fields",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Match case sensitively"),
    fuzzy: bool = typer.Option(
        False,
        "--fuzzy",
        help="Also match near-misses (misspellings, inflections) by similarity",
    ),
    show_abstract: bool = typer.Option(
        False,
        "--show-abstract",
        help="Print an excerpt of each result's abstract beneath the hit",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Maximum number of matches"),
    no_rank: bool = typer.Option(
        False,
        "--no-rank",
        help="Keep raw file order instead of ranking by match strength",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search entries by free text, phrases, or field-scoped terms.

    Each result is tagged with the field(s) that matched, e.g. \\[title] or
    \\[title, groups]: ``key`` and ``type`` for the citation key and entry
    type, or the matching stored field name (``title``, ``author``,
    ``groups``, ``abstract``, ...). With ``--json`` every hit is explained
    individually — field, term, exact or fuzzy, score, and the matching excerpt.
    By default, results are ranked by match strength — key > title > author >
    other fields > groups/abstract, then by score — with ties kept in file
    order; pass ``--no-rank`` for plain file order.

    ``--where`` narrows *which* entries are searched with the shared selector
    grammar, so date ranges and "missing field" questions need no special
    flags: ``--where 'year >= 2020 and abstract missing'``.

    An empty query selects by predicate alone —
    ``pynakes search "" --where 'doi missing'`` answers "which entries have no
    DOI" without a text match. The query argument stays required so that a
    lone path cannot be mistaken for a query; ``""`` is the explicit opt-in.
    Predicate-only results report no matched fields and are always in file
    order, since relevance ranking needs terms to rank.

    ``--show-abstract`` adds a one-line abstract excerpt under each hit, so a
    candidate set can be triaged from the search itself; ``--json`` always
    carries the full abstract. To read whole entries instead, pass the keys to
    ``ref show --keys``.
    """
    file = _resolve_input_bib(file, json_output)
    lib = Bibliography.open(file).lib
    where_filter = build_where_filter(where, keys=key)
    ranked = not no_rank and bool(query.strip())
    results = search_ops.search_entries(
        lib,
        query,
        fields=field,
        extra_fields=("abstract",) if show_abstract else None,
        where=where_filter,
        case_sensitive=case_sensitive,
        fuzzy=fuzzy,
        limit=limit,
        rank=ranked,
    )

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "search",
                "file": file,
                "query": query,
                "where": where,
                "keys": parse_key_selector(key),
                "where_parsed": where_filter.to_dict() if where_filter is not None else None,
                "fields": field or [],
                "case_sensitive": case_sensitive,
                "fuzzy": fuzzy,
                "show_abstract": show_abstract,
                "limit": limit,
                "ranked": ranked,
                "count": len(results),
                "matches": [result.to_dict() for result in results],
            }
        )
        return

    typer.echo(f"{file}: {len(results)} matching {_entries(len(results))}.")
    for result in results:
        title = result.fields.get("title")
        suffix = f" — {title}" if title else ""
        tag = ", ".join(result.matched_fields)
        if any(match.kind == "fuzzy" for match in result.matches):
            tag += f", ~{result.score:.2f}"
        label = f" [{tag}]" if tag else ""
        typer.echo(f"  @{result.type}{{{result.key}}}{suffix}{label}")
        if show_abstract:
            excerpt = abstract_excerpt(result.fields.get("abstract"))
            typer.echo(f"      {excerpt or '(no abstract)'}")


def register(app: typer.Typer) -> None:
    """Register this command on its Typer application."""
    app.command()(_safe(search))
