"""CLI command registration for ``pynakes ref find``."""

import json

import typer

from pynakes import lookup as lookup_ops
from pynakes.cli_common import (
    _CACHE_FILE_OPTION,
    _emit_error,
    _safe,
)
from pynakes.providers._http import ProviderFetchError


def find(
    text: str = typer.Argument(
        ...,
        help="A reference written out in prose: author, title, venue, year, in any order",
    ),
    limit: int = typer.Option(5, "--limit", min=1, max=20, help="Maximum candidates to return"),
    online: bool = typer.Option(
        False,
        "--online",
        help="Required: this command exists to query a bibliographic index",
    ),
    cache_file: str | None = _CACHE_FILE_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Find the real records matching a reference written out in prose.

    Every other way into this library starts from an identifier, which is a
    claim that can be checked. A reference written out as text carries no such
    claim, and this is how to ask whether one describes anything that exists —
    the case that matters when references arrive already written out rather
    than copied from a publisher page.

    Read-only, and it never decides for you. Candidates come back with the
    index's own relevance score; an empty result means the index matched
    nothing, which is evidence but not proof, since an obscure or very recent
    work also comes back empty. Import a candidate you accept by its DOI.
    """
    if not online:
        _emit_error(
            json_output,
            "OnlineLookupRequired",
            "ref find queries a bibliographic index; pass --online to allow the request.",
        )
        return
    try:
        report = lookup_ops.find_reference(text, rows=limit, cache_file=cache_file)
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))
        return
    except ProviderFetchError as exc:
        _emit_error(json_output, "ProviderUnavailable", str(exc))
        return

    if json_output:
        typer.echo(
            json.dumps({"status": "success", "action": "ref_find", **report.to_dict()}, indent=2)
        )
        return

    if not report.candidates:
        typer.echo(f"No {report.source} record matches {report.query!r}.")
        typer.echo(
            "  The index has nothing close. That is evidence the reference may not exist, "
            "not proof: an obscure or very recent work also matches nothing."
        )
        return

    typer.echo(f"{len(report.candidates)} candidate(s) from {report.source}:")
    for rank, candidate in enumerate(report.candidates, start=1):
        marker = "*" if candidate.strong else " "
        typer.echo(f" {marker}{rank}. {candidate.score:6.1f}  {candidate.doi}")
        typer.echo(f"        {candidate.title or '(untitled)'}")
        byline = "; ".join(candidate.authors[:4])
        if len(candidate.authors) > 4:
            byline += " et al."
        detail = " · ".join(part for part in (byline, candidate.container, candidate.year) if part)
        if detail:
            typer.echo(f"        {detail}")
    if not report.strong_matches:
        typer.echo("  No candidate plainly matches the text; review before importing any.")
    typer.echo("  Import one with: pynakes ref import <doi>")


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("find")(_safe(find))
