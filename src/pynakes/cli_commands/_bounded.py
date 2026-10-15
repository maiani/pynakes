"""Shared options and output for bounded multi-entry reads.

``ref show --key`` and ``ref show --where`` return the same page of entry records (see
:mod:`pynakes.entry_reader`) under the same options, so a caller that learned
to page one can page the other. This module owns those options, the cursor
error handling, and the envelope keys they share.
"""

from collections.abc import Sequence
from typing import Any

import typer

from pynakes.bounded import (
    CursorError,
    Page,
    StaleCursorError,
    paginate,
    parse_field_selection,
)
from pynakes.cli_common import InvalidInputError, _emit_conflict, _emit_json, _source_sha256
from pynakes.engine import Bibliography
from pynakes.entry_reader import EntryReader, parse_include
from pynakes.model import BibEntry
from pynakes.triage import abstract_excerpt


def select_option() -> Any:
    """Return the ``--select`` field-projection option."""
    return typer.Option(
        None,
        "--select",
        help="Return only these fields under 'fields': comma-separated, repeatable. "
        "A selected field the entry lacks is null and listed in missing_fields",
    )


def include_option() -> Any:
    """Return the ``--include`` option: what to add beyond the entry's fields."""
    return typer.Option(
        None,
        "--include",
        help="Also report what the library records outside the entry's fields: "
        "materials (Pinax files and file links), provenance (manifest records and "
        "directives). Comma-separated, repeatable",
    )


def parse_includes(values: list[str] | None) -> tuple[str, ...]:
    """Parse ``--include`` values, reporting an unknown part as invalid input."""
    try:
        return parse_include(values)
    except ValueError as exc:
        raise InvalidInputError(f"--include: {exc}") from None


def max_chars_option() -> Any:
    """Return the ``--max-chars`` per-value text limit."""
    return typer.Option(
        None,
        "--max-chars",
        help="Cut every returned text value to at most this many characters; "
        "each cut is listed under 'truncated'",
    )


def limit_option(help: str = "Return at most this many entries per page") -> Any:
    """Return the ``--limit`` page-size option."""
    return typer.Option(None, "--limit", help=help)


def cursor_option() -> Any:
    """Return the ``--cursor`` page-resume option."""
    return typer.Option(
        None,
        "--cursor",
        help="Resume a paged read: pass page.next_cursor from the previous page. "
        "Refused when the library changed since",
    )


def check_bounds(limit: int | None, max_chars: int | None) -> None:
    """Reject negative page sizes and text limits (``--limit 0`` only counts)."""
    if limit is not None and limit < 0:
        raise InvalidInputError("--limit must not be negative")
    if max_chars is not None and max_chars < 0:
        raise InvalidInputError("--max-chars must not be negative")


def parse_select(values: list[str] | None) -> tuple[str, ...] | None:
    """Parse ``--select`` values, reporting an empty selection as invalid input."""
    try:
        return parse_field_selection(values)
    except ValueError as exc:
        raise InvalidInputError(f"--select: {exc}") from None


def page_of(
    coll: Bibliography,
    items: Sequence,
    *,
    limit: int | None,
    cursor: str | None,
    request: str,
    json_output: bool,
    action: str,
) -> tuple[list, Page]:
    """Paginate ``items`` against this snapshot, rendering cursor failures."""
    snapshot = _source_sha256(coll)
    try:
        return paginate(items, limit=limit, cursor=cursor, snapshot=snapshot, request=request)
    except CursorError as exc:
        raise InvalidInputError(f"--cursor: {exc}") from None
    except StaleCursorError as exc:
        _emit_conflict(
            json_output,
            "StaleCursor",
            str(exc),
            action=action,
            source_sha256=snapshot,
            options=[
                {
                    "id": "restart",
                    "description": "Re-run without --cursor to read the current library "
                    "from the first page",
                }
            ],
        )


def entry_records(
    coll: Bibliography,
    entries: Sequence[BibEntry],
    *,
    resolved: bool,
    include_abstract: bool,
    select: tuple[str, ...] | None,
    include: tuple[str, ...],
    max_chars: int | None,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return the bounded records for ``entries`` and any source warnings."""
    reader = EntryReader(coll, resolved=resolved)
    records = [
        reader.record(
            entry,
            include_abstract=include_abstract,
            select=select,
            include=include,
            max_chars=max_chars,
        )
        for entry in entries
    ]
    return records, reader.warnings


def bounds_payload(
    *,
    select: tuple[str, ...] | None,
    include: tuple[str, ...],
    max_chars: int | None,
    limit: int | None,
) -> dict[str, object]:
    """Describe the bounds a read applied, as the envelope reports them."""
    return {
        "select": list(select) if select is not None else None,
        "include": list(include),
        "max_chars": max_chars,
        "limit": limit,
    }


def retrieval_hint(records: list[dict[str, object]]) -> dict[str, object] | None:
    """Name how to read in full the records this page truncated, if any."""
    keys = [str(record["key"]) for record in records if record.get("truncated")]
    if not keys:
        return None
    return {
        "command": "ref show",
        "keys": list(dict.fromkeys(keys)),
        "note": "Re-run without --max-chars (or with a larger limit) to read these "
        "values whole; ref show FILE KEY prints one complete record",
    }


def emit_page(
    payload: dict[str, object],
    records: list[dict[str, object]],
    page: Page,
    *,
    heading: str,
    json_output: bool,
) -> None:
    """Emit a page of records: the JSON envelope, or a scannable listing."""
    if json_output:
        payload["count"] = len(records)
        payload["page"] = page.to_dict()
        payload["entries"] = records
        payload["retrieve_full"] = retrieval_hint(records)
        _emit_json(payload)
        return

    typer.echo(heading)
    width = max(
        (len(name) for record in records for name in _labels(record)),
        default=0,
    )
    for record in records:
        typer.echo("")
        marker = "  (duplicate key)" if record.get("duplicate_key") else ""
        typer.echo(f"@{record['entry_type']}{{{record['key']}}}{marker}")
        for name, value in _lines(record):
            typer.echo(f"  {name.ljust(width)}  {value}")
    if not page.complete:
        typer.echo("")
        typer.echo(
            f"Showing {page.offset + 1}-{page.offset + page.returned} of {page.total}; "
            f"continue with --cursor {page.next_cursor}"
        )
    warnings = payload.get("warnings")
    for warning in warnings if isinstance(warnings, list) else []:
        if isinstance(warning, dict):
            typer.echo(f"warning: {warning.get('message')}")


def _labels(record: dict[str, object]) -> list[str]:
    return [name for name, _value in _lines(record)]


def _lines(record: dict[str, object]) -> list[tuple[str, str]]:
    """Return the label/value lines of one record's human rendering."""
    truncated = record.get("truncated") or {}
    assert isinstance(truncated, dict)

    def shown(value: object, label: str) -> str:
        if value is None:
            return "(none)"
        text = abstract_excerpt(str(value), limit=10**9) if label.endswith("abstract") else value
        return f"{text}…" if label in truncated else str(text)

    lines: list[tuple[str, str]] = []
    summary = record.get("summary") or {}
    assert isinstance(summary, dict)
    lines += [(name, shown(value, f"summary.{name}")) for name, value in summary.items()]
    fields = record.get("fields")
    if isinstance(fields, dict):
        lines += [
            (name, shown(value, f"fields.{name}"))
            for name, value in fields.items()
            if name not in summary
        ]
    return lines + included_lines(record)


def included_lines(record: dict[str, object]) -> list[tuple[str, str]]:
    """Return the label/value lines of the parts ``--include`` added, if any."""
    lines: list[tuple[str, str]] = []
    if "materials" in record:
        lines.append(("materials", _materials_line(record["materials"])))
    if "provenance" in record:
        lines.append(("provenance", _provenance_line(record["provenance"])))
    return lines


def _materials_line(materials: object) -> str:
    if not isinstance(materials, dict):
        return "(none)"
    parts: list[str] = []
    pinax = materials.get("pinax")
    if isinstance(pinax, dict) and pinax.get("available"):
        parts.append("pinax: " + ", ".join(str(kind) for kind in pinax["available"]))
    linked = materials.get("linked_files") or []
    if linked:
        ok = sum(1 for link in linked if link.get("status") == "ok")
        parts.append(f"linked files: {ok}/{len(linked)} found")
    return "; ".join(parts) if parts else "(none)"


def _provenance_line(provenance: object) -> str:
    if not isinstance(provenance, dict):
        return "(none)"
    parts: list[str] = []
    for kind, record in (provenance.get("materials") or {}).items():
        when = record.get("fetched_date") or record.get("added_date")
        source = record.get("source")
        parts.append(f"{kind} from {source}" + (f" ({when})" if when else ""))
    for directive in provenance.get("directives") or []:
        text = f"{directive['verb']} {', '.join(directive['args'])}".strip()
        if directive.get("reason"):
            text += f" -- {directive['reason']}"
        parts.append(f"directive: {text}")
    return "; ".join(parts) if parts else "(none)"
