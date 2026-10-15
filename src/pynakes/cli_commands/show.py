"""CLI command registration for ``pynakes ref show``."""

import typer

from pynakes.bounded import request_digest
from pynakes.cli_commands._bounded import (
    bounds_payload,
    check_bounds,
    cursor_option,
    emit_page,
    entry_records,
    include_option,
    included_lines,
    limit_option,
    max_chars_option,
    page_of,
    parse_includes,
    parse_select,
    select_option,
)
from pynakes.cli_commands._reference import parse_key_list, unique_entries, unique_entry
from pynakes.cli_common import (
    InvalidInputError,
    _emit_json,
    _entries,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
    bind_where_filter,
    key_option,
    where_option,
)
from pynakes.engine import Bibliography


def show(
    file: str | None = bib_file_argument(),
    key: str | None = typer.Argument(None, help="Citation key to display"),
    keys: list[str] | None = key_option(
        "Summarize several references at once: comma-separated keys, repeatable"
    ),
    where: str | None = where_option(
        "Summarize every reference this selector matches, in file order (the shared "
        "--where grammar, saved queries and used/unused included); narrowed by --key"
    ),
    resolved: bool = typer.Option(
        False, "--resolved", help="Include fields inherited through crossref/xdata"
    ),
    abstract: bool = typer.Option(
        False, "--abstract", help="Include each abstract in the --key summary"
    ),
    select: list[str] | None = select_option(),
    include: list[str] | None = include_option(),
    max_chars: int | None = max_chars_option(),
    limit: int | None = limit_option(
        "With --key or --where, return at most this many entries per page"
    ),
    cursor: str | None = cursor_option(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one uniquely identified reference, or triage several at once.

    With a citation key this prints every stored field of that one reference.
    With `--key k1,k2,...` it prints a compact summary of each requested
    reference instead — title, creator, date, venue, and identifiers, plus the
    abstract under `--abstract` — so a set of candidates can be scanned in
    one call rather than one invocation per key. Both forms refuse to guess
    when a key is duplicated, and the `--key` form reports every unknown key
    together. `--where EXPR` summarizes every entry the selector matches, in
    file order — `--where 'query "to-read"'` runs a saved query, and
    `used`/`unused` test the library's linked TeX sources.

    Bounded reads: `--select` returns only the named fields (the abstract
    among them); `--include materials,provenance` adds the materials
    available for each entry and the provenance the library recorded;
    `--max-chars` cuts long values and lists every cut under `truncated`.
    With `--key` or `--where`, `--limit` pages the selection and
    `page.next_cursor` resumes it — a cursor is refused once the library
    changes, so pages never silently skip or repeat entries. Information
    the library lacks is reported as missing (`null`, `missing`,
    `missing_fields`), never as an omission.
    """
    selecting = bool(keys) or where is not None
    if selecting:
        if key is not None:
            raise InvalidInputError("Pass a citation key or --key/--where, not both")
    elif key is None:
        raise InvalidInputError("Provide a citation key, --key, or --where")
    if abstract and not selecting:
        raise InvalidInputError(
            "--abstract applies to the --key/--where summary; showing a single key "
            "already prints every field, abstract included"
        )
    if not selecting and (limit is not None or cursor is not None):
        raise InvalidInputError("--limit and --cursor page a --key or --where selection")
    check_bounds(limit, max_chars)
    selection = parse_select(select)
    parts = parse_includes(include)

    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)

    if where is not None:
        _show_selection(
            coll,
            file,
            where,
            parse_key_list(keys) if keys else [],
            resolved=resolved,
            include_abstract=abstract,
            select=selection,
            include=parts,
            max_chars=max_chars,
            limit=limit,
            cursor=cursor,
            json_output=json_output,
        )
        return

    if keys:
        _show_summaries(
            coll,
            file,
            parse_key_list(keys),
            resolved=resolved,
            include_abstract=abstract,
            select=selection,
            include=parts,
            max_chars=max_chars,
            limit=limit,
            cursor=cursor,
            json_output=json_output,
        )
        return

    entry = unique_entry(coll, key, json_output, action="ref_show")
    if selection is not None or parts or max_chars is not None:
        _show_bounded_entry(
            coll,
            file,
            entry,
            resolved=resolved,
            select=selection,
            include=parts,
            max_chars=max_chars,
            json_output=json_output,
        )
        return

    fields = coll.lib.resolved_fields(entry) if resolved else entry.fields
    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "ref_show",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "key": entry.key,
                "entry_type": entry.type,
                "fields": dict(fields),
                "resolved": resolved,
            }
        )
        return
    typer.echo(f"@{entry.type}{{{entry.key}}}")
    for name, value in fields.items():
        typer.echo(f"  {name} = {value}")


def _show_bounded_entry(
    coll: Bibliography,
    file: str,
    entry,
    *,
    resolved: bool,
    select: tuple[str, ...] | None,
    include: tuple[str, ...],
    max_chars: int | None,
    json_output: bool,
) -> None:
    """Show one entry's fields under a projection, text limit, or inclusion."""
    (record,), warnings = entry_records(
        coll,
        [entry],
        resolved=resolved,
        include_abstract=False,
        # Every stored field, unless a selection narrows it: the single-key
        # form shows the whole record by default.
        select=select if select is not None else tuple(name.lower() for name in entry.fields),
        include=include,
        max_chars=max_chars,
    )
    if select is None:
        # Nothing was selected away, so nothing was omitted or missing.
        record.pop("missing_fields", None)
        record.pop("omitted_fields", None)
    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "ref_show",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": warnings,
                **record,
                "resolved": resolved,
                "bounds": bounds_payload(
                    select=select, include=include, max_chars=max_chars, limit=None
                ),
            }
        )
        return
    truncated = record.get("truncated")
    truncated = truncated if isinstance(truncated, dict) else {}
    typer.echo(f"@{entry.type}{{{entry.key}}}")
    for name, value in (record.get("fields") or {}).items():
        cut = "…" if f"fields.{name}" in truncated else ""
        typer.echo(f"  {name} = {'(none)' if value is None else value}{cut}")
    for name, value in included_lines(record):
        typer.echo(f"  {name}: {value}")


def _show_summaries(
    coll: Bibliography,
    file: str,
    keys: list[str],
    *,
    resolved: bool,
    include_abstract: bool,
    select: tuple[str, ...] | None,
    include: tuple[str, ...],
    max_chars: int | None,
    limit: int | None,
    cursor: str | None,
    json_output: bool,
) -> None:
    """Print one triage summary per requested key, in the order requested."""
    entries = unique_entries(coll, keys, json_output, action="ref_show")
    page, page_info = page_of(
        coll,
        entries,
        limit=limit,
        cursor=cursor,
        request=request_digest(command="ref show", keys=keys),
        json_output=json_output,
        action="ref_show",
    )
    records, warnings = entry_records(
        coll,
        page,
        resolved=resolved,
        include_abstract=include_abstract,
        select=select,
        include=include,
        max_chars=max_chars,
    )
    payload: dict[str, object] = {
        "status": "success",
        "action": "ref_show",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": warnings,
        "keys": keys,
        "resolved": resolved,
        "abstract": include_abstract,
        "bounds": bounds_payload(select=select, include=include, max_chars=max_chars, limit=limit),
    }
    emit_page(
        payload,
        records,
        page_info,
        heading=f"{file}: {len(records)} {_entries(len(records))}.",
        json_output=json_output,
    )


def _show_selection(
    coll: Bibliography,
    file: str,
    where: str,
    keys: list[str],
    *,
    resolved: bool,
    include_abstract: bool,
    select: tuple[str, ...] | None,
    include: tuple[str, ...],
    max_chars: int | None,
    limit: int | None,
    cursor: str | None,
    json_output: bool,
) -> None:
    """Print one triage summary per entry the ``--where`` selector matches."""
    if keys:
        # A mistyped --key is an error, never a quietly smaller selection.
        unique_entries(coll, keys, json_output, action="ref_show")
    warnings: list[dict] = []
    selector = bind_where_filter(coll, where, keys=keys or None, warnings=warnings)
    matches = [entry for entry in coll.lib.entries.values() if selector is None or selector(entry)]
    page, page_info = page_of(
        coll,
        matches,
        limit=limit,
        cursor=cursor,
        request=request_digest(command="ref show", where=where, keys=keys),
        json_output=json_output,
        action="ref_show",
    )
    records, reader_warnings = entry_records(
        coll,
        page,
        resolved=resolved,
        include_abstract=include_abstract,
        select=select,
        include=include,
        max_chars=max_chars,
    )
    payload: dict[str, object] = {
        "status": "success",
        "action": "ref_show",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [*warnings, *reader_warnings],
        "where": where,
        "keys": keys,
        "resolved": resolved,
        "abstract": include_abstract,
        "bounds": bounds_payload(select=select, include=include, max_chars=max_chars, limit=limit),
    }
    emit_page(
        payload,
        records,
        page_info,
        heading=f"{file}: --where matches {page_info.total} {_entries(page_info.total)}.",
        json_output=json_output,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("show")(_safe(show))
