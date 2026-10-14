"""CLI command registration for bibliography search."""

import typer

from pynakes import search as search_ops
from pynakes.bounded import parse_field_selection, project_fields, request_digest
from pynakes.cli_commands._bounded import (
    bounds_payload,
    check_bounds,
    cursor_option,
    limit_option,
    max_chars_option,
    page_of,
    parse_select,
    select_option,
)
from pynakes.cli_common import (
    InvalidInputError,
    _emit_json,
    _entries,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
    build_where_filter,
    deprecation_warning,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.triage import abstract_excerpt


def search(
    file: str | None = bib_file_argument(),
    query: str = typer.Argument(
        ...,
        help=(
            "Search query: words/phrases, optionally scoped as field:term or "
            'field:"phrase". Pass "" to select by --where alone'
        ),
    ),
    search_in: list[str] | None = typer.Option(
        None,
        "--in",
        help="Search only these stored fields: comma-separated, repeatable. "
        "The citation key and entry type stay searchable",
    ),
    select: list[str] | None = select_option(),
    in_field: list[str] | None = typer.Option(
        None,
        "--in-field",
        help="Deprecated, removed in 0.9.0: use --in to choose the fields searched "
        "and --select to choose the fields returned",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Match case sensitively"),
    fuzzy: bool = typer.Option(
        False,
        "--fuzzy",
        help="Also match near-misses (misspellings, inflections) by similarity",
    ),
    abstract: bool = typer.Option(
        False,
        "--abstract",
        help="Print an excerpt of each result's abstract beneath the hit",
    ),
    limit: int | None = limit_option("Maximum number of matches per page"),
    cursor: str | None = cursor_option(),
    max_chars: int | None = max_chars_option(),
    no_rank: bool = typer.Option(
        False,
        "--no-rank",
        help="Keep raw file order instead of ranking by match strength",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search entries by free text, phrases, or field-scoped terms.

    Each result is tagged with the field(s) that matched, e.g. \\[title] or
    \\[title, groups]: `key` and `type` for the citation key and entry
    type, or the matching stored field name (`title`, `author`,
    `groups`, `abstract`, ...). With `--json` every hit is explained
    individually — field, term, exact or fuzzy, score, and the matching excerpt.
    By default, results are ranked by match strength — key > title > author >
    other fields > groups/abstract, then by score — with ties kept in file
    order; pass `--no-rank` for plain file order.

    Two options shape a search without changing the query: `--in` chooses
    which stored fields the terms are looked for in, and `--select` chooses
    which fields each result returns. They are independent: `--in title
    --select title,abstract` matches titles only and still returns the
    abstracts.

    `--where` narrows *which* entries are searched with the shared selector
    grammar, so date ranges and "missing field" questions need no special
    flags: `--where 'year >= 2020 and abstract missing'`.

    An empty query selects by predicate alone —
    `pynakes search "" --where 'doi missing'` answers "which entries have no
    DOI" without a text match. The query argument stays required so that a
    lone path cannot be mistaken for a query; `""` is the explicit opt-in.
    Predicate-only results report no matched fields and are always in file
    order, since relevance ranking needs terms to rank.

    `--abstract` adds a one-line abstract excerpt under each hit, so a
    candidate set can be triaged from the search itself; `--json` always
    carries the full abstract. To read whole entries instead, pass the keys to
    `ref show --key`.

    Results page like every bounded read: `--limit` caps a page,
    `page.next_cursor` resumes the same search with `--cursor` (refused once
    the library changes), and `--max-chars` cuts long field values, listing
    each cut under the result's `truncated`.
    """
    check_bounds(limit, max_chars)
    warnings: list[dict] = []
    if in_field:
        if search_in or select:
            raise InvalidInputError(
                "--in-field is deprecated and cannot be combined with --in or --select; "
                "use --in and --select"
            )
        warnings.append(
            deprecation_warning(
                "--in-field", "--in and --select", removal="0.9.0", json_output=json_output
            )
        )
    try:
        scope = parse_field_selection(search_in)
    except ValueError as exc:
        raise InvalidInputError(f"--in: {exc}") from None
    selection = parse_select(select)
    if selection is not None and abstract and "abstract" not in selection:
        # --abstract shows each abstract; with a selection it has to be selected.
        selection = (*selection, "abstract")
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    lib = coll.lib
    where_filter = build_where_filter(where, keys=key)
    ranked = not no_rank and bool(query.strip())
    results = search_ops.search_entries(
        lib,
        query,
        fields=in_field,
        search_in=scope,
        extra_fields=("abstract",) if abstract else None,
        where=where_filter,
        case_sensitive=case_sensitive,
        fuzzy=fuzzy,
        rank=ranked,
    )
    results, page = page_of(
        coll,
        results,
        limit=limit,
        cursor=cursor,
        request=request_digest(
            command="search",
            query=query,
            where=where,
            keys=parse_key_selector(key),
            in_fields=list(scope or in_field or []),
            case_sensitive=case_sensitive,
            fuzzy=fuzzy,
            ranked=ranked,
        ),
        json_output=json_output,
        action="search",
    )

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "search",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": warnings,
                "query": query,
                "where": where,
                "keys": parse_key_selector(key),
                "where_parsed": where_filter.to_dict() if where_filter is not None else None,
                "in_fields": list(scope or in_field or []),
                "case_sensitive": case_sensitive,
                "fuzzy": fuzzy,
                "abstract": abstract,
                "limit": limit,
                "ranked": ranked,
                "bounds": bounds_payload(
                    select=selection, include=(), max_chars=max_chars, limit=limit
                ),
                "count": len(results),
                "page": page.to_dict(),
                "matches": [_bounded_match(result, selection, max_chars) for result in results],
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
        if abstract:
            excerpt = abstract_excerpt(result.fields.get("abstract"))
            typer.echo(f"      {excerpt or '(no abstract)'}")
    if not page.complete:
        typer.echo(
            f"Showing {page.offset + 1}-{page.offset + page.returned} of {page.total}; "
            f"continue with --cursor {page.next_cursor}"
        )


def _bounded_match(
    result: search_ops.SearchResult, select: tuple[str, ...] | None, max_chars: int | None
) -> dict[str, object]:
    """Serialize one match with the selected fields, cut to ``max_chars``."""
    described = result.to_dict()
    projection = project_fields(result.fields, select, max_chars)
    described["fields"] = projection.fields
    if select is not None:
        described["missing_fields"] = projection.missing
        described["omitted_fields"] = projection.omitted
    described["truncated"] = {name: cut.to_dict() for name, cut in projection.truncated.items()}
    return described


def register(app: typer.Typer) -> None:
    """Register this command on its Typer application."""
    app.command()(_safe(search))
