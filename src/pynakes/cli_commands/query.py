"""CLI commands for saved queries: ``query list``, ``set``, ``remove``, and ``run``."""

import typer

from pynakes import metadata as metadata_ops
from pynakes import saved_queries as saved_ops
from pynakes.bounded import request_digest
from pynakes.cli_commands._bounded import (
    bounds_payload,
    check_bounds,
    cursor_option,
    emit_page,
    entry_records,
    include_option,
    limit_option,
    max_chars_option,
    page_of,
    parse_includes,
    parse_select,
    select_option,
)
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    InvalidInputError,
    RunParams,
    _emit_conflict,
    _emit_error,
    _emit_json,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography

_DUPLICATE_OPTIONS = [
    {
        "id": "manual_edit",
        "description": "Keep one metadata line for this query name, then retry",
    }
]


def query_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List the library's saved queries, and whether each still parses."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    queries = [query.to_dict() for query in saved_ops.saved_queries(coll.lib)]
    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "query_list",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "count": len(queries),
                "queries": queries,
            }
        )
        return
    if not queries:
        typer.echo(f"{file}: no saved queries.")
        return
    typer.echo(f"{file}: {len(queries)} saved quer{'y' if len(queries) == 1 else 'ies'}.")
    for query in queries:
        problem = "" if query["valid"] else f"  [invalid: {query['error']}]"
        typer.echo(f"  {query['name']}: {query['expression']}{problem}")


def query_set(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Query name: letters, digits, '_', '.', '-'"),
    expression: str = typer.Argument(..., help="Selector expression (the --where grammar)"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Save a named selector query in the library, or replace one.

    The expression is validated with the shared `--where` grammar and stored as
    a `query-NAME` line in `pynakes-meta`. The library keeps the query, not
    its result, so `query run` always reflects the entries as they are.
    """
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    try:
        node = saved_ops.validate_saved_query(name, expression)
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from None
    name = name.strip()
    expression = expression.strip()

    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    existing = saved_ops.saved_query(coll.lib, name)
    try:
        update = coll.set_metadata(saved_ops.metadata_key(name), expression, namespace="pynakes")
    except metadata_ops.DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=_DUPLICATE_OPTIONS,
        )

    if existing is not None and existing.expression == expression:
        summary = f"Query {name!r} is already saved as: {expression}"
    else:
        summary = f"{_verb('save', params, 'Saved')} query {name!r}: {expression}"
    _finish_mod(
        file,
        "query_set",
        coll,
        params,
        [summary],
        modified_entries=0,
        name=name,
        expression=expression,
        created=update.created,
        parsed=node.to_dict(),
        uses_citations=saved_ops.query_uses_citations(node),
    )


def query_remove(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Name of the saved query to remove"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove a saved query from the library."""
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    query = _require_query(coll, name, json_output, action="query_remove")
    try:
        coll.remove_metadata(saved_ops.metadata_key(query.name))
    except metadata_ops.DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=_DUPLICATE_OPTIONS,
        )
    _finish_mod(
        file,
        "query_remove",
        coll,
        params,
        [f"{_verb('remove', params, 'Removed')} query {query.name!r}."],
        modified_entries=0,
        name=query.name,
        expression=query.expression,
    )


def query_run(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Name of the saved query to run"),
    resolved: bool = typer.Option(
        False, "--resolved", help="Include fields inherited through crossref/xdata"
    ),
    abstract: bool = typer.Option(False, "--abstract", help="Include each abstract in the summary"),
    select: list[str] | None = select_option(),
    include: list[str] | None = include_option(),
    max_chars: int | None = max_chars_option(),
    limit: int | None = limit_option(),
    cursor: str | None = cursor_option(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a saved query against the library as it is now.

    Returns the matching entries in file order, as `ref show --key` returns
    a selection: a summary per entry (or the `--select` fields), the research
    included parts under `--include`, and pages under `--limit`/`--cursor`.
    `used`/`unused` resolve against the library's linked TeX sources.
    """
    check_bounds(limit, max_chars)
    selection = parse_select(select)
    parts = parse_includes(include)
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    query = _require_query(coll, name, json_output, action="query_run")
    try:
        matches, warnings = saved_ops.select_entries(
            coll.lib, query.expression, base_dir=coll.path.parent if coll.path else None
        )
    except saved_ops.NoCitationSourcesError as exc:
        _emit_error(json_output, "NoSources", str(exc), action="query_run", name=query.name)
    except ValueError as exc:
        raise InvalidInputError(f"Saved query {query.name!r} no longer parses: {exc}") from None

    page, page_info = page_of(
        coll,
        matches,
        limit=limit,
        cursor=cursor,
        request=request_digest(command="query run", expression=query.expression),
        json_output=json_output,
        action="query_run",
    )
    records, reader_warnings = entry_records(
        coll,
        page,
        resolved=resolved,
        include_abstract=abstract,
        select=selection,
        include=parts,
        max_chars=max_chars,
    )
    payload: dict[str, object] = {
        "status": "success",
        "action": "query_run",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [*warnings, *reader_warnings],
        "name": query.name,
        "expression": query.expression,
        "resolved": resolved,
        "abstract": abstract,
        "bounds": bounds_payload(select=selection, include=parts, max_chars=max_chars, limit=limit),
    }
    emit_page(
        payload,
        records,
        page_info,
        heading=f"{file}: query {query.name!r} matches {page_info.total} "
        f"{_entries(page_info.total)}.",
        json_output=json_output,
    )


def _require_query(
    coll: Bibliography, name: str, json_output: bool, *, action: str
) -> saved_ops.SavedQuery:
    query = saved_ops.saved_query(coll.lib, name)
    if query is None:
        available = [item.name for item in saved_ops.saved_queries(coll.lib)]
        _emit_error(
            json_output,
            "KeyNotFound",
            f"No saved query named {name!r}",
            action=action,
            name=name,
            available=available,
        )
    return query


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(query_list))
    app.command("set")(_safe(query_set))
    app.command("remove")(_safe(query_remove))
    app.command("run")(_safe(query_run))
