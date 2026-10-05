"""CLI command registration for ``pynakes ref show``."""

import typer

from pynakes.cli_commands._reference import parse_key_list, unique_entries, unique_entry
from pynakes.cli_common import (
    InvalidInputError,
    _emit_json,
    _entries,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
    key_option,
)
from pynakes.engine import Bibliography
from pynakes.triage import entry_summary


def show(
    file: str | None = bib_file_argument(),
    key: str | None = typer.Argument(None, help="Citation key to display"),
    keys: list[str] | None = key_option(
        "Summarize several references at once: comma-separated keys, repeatable"
    ),
    resolved: bool = typer.Option(
        False, "--resolved", help="Include fields inherited through crossref/xdata"
    ),
    abstract: bool = typer.Option(
        False, "--abstract", help="Include each abstract in the --key summary"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one uniquely identified reference, or triage several at once.

    With a citation key this prints every stored field of that one reference.
    With ``--key k1,k2,...`` it prints a compact summary of each requested
    reference instead — title, creator, date, venue, and identifiers, plus the
    abstract under ``--abstract`` — so a set of candidates can be scanned in
    one call rather than one invocation per key. Both forms refuse to guess
    when a key is duplicated, and the ``--key`` form reports every unknown key
    together.
    """
    if keys:
        if key is not None:
            raise InvalidInputError("Pass a citation key or --key, not both")
    elif key is None:
        raise InvalidInputError("Provide a citation key or --key")
    if abstract and not keys:
        raise InvalidInputError(
            "--abstract applies to the --key summary; showing a single key already "
            "prints every field, abstract included"
        )

    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)

    if keys:
        _show_summaries(
            coll,
            file,
            parse_key_list(keys),
            resolved=resolved,
            include_abstract=abstract,
            json_output=json_output,
        )
        return

    entry = unique_entry(coll, key, json_output, action="ref_show")
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


def _show_summaries(
    coll: Bibliography,
    file: str,
    keys: list[str],
    *,
    resolved: bool,
    include_abstract: bool,
    json_output: bool,
) -> None:
    """Print one triage summary per requested key, in the order requested."""
    summaries = []
    for entry in unique_entries(coll, keys, json_output, action="ref_show"):
        fields = coll.lib.resolved_fields(entry) if resolved else entry.fields
        summaries.append(
            {
                "key": entry.key,
                "entry_type": entry.type,
                "summary": entry_summary(entry, fields, include_abstract=include_abstract),
            }
        )

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "ref_show",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "keys": keys,
                "count": len(summaries),
                "entries": summaries,
                "resolved": resolved,
                "abstract": include_abstract,
            }
        )
        return

    typer.echo(f"{file}: {len(summaries)} {_entries(len(summaries))}.")
    # One label column across every entry keeps the values aligned down the
    # whole listing, which is what makes it scannable.
    width = max((len(name) for item in summaries for name in item["summary"]), default=0)
    for item in summaries:
        typer.echo("")
        typer.echo(f"@{item['entry_type']}{{{item['key']}}}")
        for name, value in item["summary"].items():
            typer.echo(f"  {name.ljust(width)}  {'(none)' if value is None else value}")


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("show")(_safe(show))
