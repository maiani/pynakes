"""CLI command registration for ``pynakes ref compare``."""

import json

import typer

from pynakes.cli_commands._reference import unique_entries, unique_entry
from pynakes.cli_common import (
    InvalidInputError,
    _metadata_cache_dir,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography


def compare(
    key: str = typer.Argument(..., help="Citation key to compare"),
    file: str | None = bib_file_argument(),
    with_: str | None = typer.Option(
        None,
        "--with",
        help="Compare against another local citation key instead of a remote record",
    ),
    online: bool = typer.Option(
        False,
        "--online",
        help="Fetch DOI/arXiv provider metadata (required to compare against a remote record)",
    ),
    cache_dir: str | None = typer.Option(
        None, "--cache-dir", help="Directory for deterministic provider-response cache"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Compare one reference's fields against another reference (read-only).

    With ``--with OTHER_KEY``, compares two entries already in the library —
    e.g. reviewing a candidate duplicate pair before merging. No network
    access. Without it, compares against a fetched DOI/arXiv remote record:
    prefers the entry's DOI (existing, or inferred from a local URL), falling
    back to an arXiv id.

    Either way, reports only the fields where a non-empty value on the other
    side differs from the local one, for manual review — nothing is written.
    Apply chosen fields afterward with ``ref edit KEY --field name=value``.
    """
    if with_ is not None and online:
        raise InvalidInputError(
            "--with compares two local entries and cannot combine with --online"
        )
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    if with_ is not None:
        entry, other = unique_entries(coll, [key, with_], json_output, action="ref_compare")
        report = coll.compare_entries(entry.key, other.key)
    else:
        entry = unique_entry(coll, key, json_output, action="ref_compare")
        cache = _metadata_cache_dir(file, cache_dir, online)
        report = coll.compare_entry_with_remote(entry.key, online=online, cache_dir=cache)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "success",
                    "action": "ref_compare",
                    "file": file,
                    "online": online,
                    **report.to_dict(),
                },
                indent=2,
            )
        )
        return

    typer.echo(f"@{entry.type}{{{entry.key}}}")
    if report.source:
        typer.echo(f"  compared against {report.source}:{report.identifier}")
    if not report.fields:
        typer.echo("  (no differing fields)" if report.source else "  (nothing compared)")
    for comparison in report.fields:
        local = comparison.local if comparison.local is not None else "(missing)"
        typer.echo(f"  {comparison.field}:")
        typer.echo(f"    local: {local}")
        typer.echo(f"    other: {comparison.other}")
    for warning in report.warnings:
        typer.echo(f"  [warning] {warning['message']}")


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("compare")(_safe(compare))
