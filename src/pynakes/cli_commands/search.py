"""CLI command registration for bibliography search."""

import json as _json

import typer

from pynakes import fields as fields_ops
from pynakes import search as search_ops
from pynakes.cli_common import _entries, _resolve_input_bib, _safe
from pynakes.engine import Bibliography


def search(
    query: str = typer.Argument(
        ...,
        help='Search query: words/phrases, optionally scoped as field:term or field:"phrase"',
    ),
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    field: list[str] | None = typer.Option(
        None,
        "--field",
        help="Restrict stored fields searched and returned; repeat for multiple fields",
    ),
    where: str | None = typer.Option(None, "--where", help="Filter expression"),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Match case sensitively"),
    limit: int | None = typer.Option(None, "--limit", help="Maximum number of matches"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search entries by free text, phrases, or field-scoped terms."""
    file = _resolve_input_bib(file, json_output)
    lib = Bibliography.open(file).lib
    where_filter = fields_ops.parse_query(where) if where is not None else None
    results = search_ops.search_entries(
        lib,
        query,
        fields=field,
        where=where_filter,
        case_sensitive=case_sensitive,
        limit=limit,
    )

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "status": "success",
                    "action": "search",
                    "file": file,
                    "query": query,
                    "where": where,
                    "fields": field or [],
                    "case_sensitive": case_sensitive,
                    "limit": limit,
                    "count": len(results),
                    "matches": [result.to_dict() for result in results],
                },
                indent=2,
            )
        )
        return

    typer.echo(f"{file}: {len(results)} matching {_entries(len(results))}.")
    for result in results:
        title = result.fields.get("title")
        suffix = f" — {title}" if title else ""
        typer.echo(f"  @{result.type}{{{result.key}}}{suffix} [{', '.join(result.matched_fields)}]")


def register(app: typer.Typer) -> None:
    """Register this command on its Typer application."""
    app.command()(_safe(search))
