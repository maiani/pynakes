"""CLI command registration for ``pynakes analyze``."""

import typer

from pynakes.analysis import analyze as analyze_bibliography
from pynakes.cli_choices import AnalysisSection
from pynakes.cli_common import (
    InvalidInputError,
    _emit_json,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
)
from pynakes.engine import Bibliography

_MAX_AUTHORS_HELP = (
    "Link only entries listing at most this many authors; 0 links every entry "
    "(default: the library's coauthors-max-authors setting, else 100)"
)


def analyze(
    file: str | None = bib_file_argument(),
    section: list[AnalysisSection] = typer.Option(
        [],
        "--section",
        help="Report only these sections (repeatable; default: all)",
    ),
    top: int = typer.Option(
        10,
        "--top",
        help="Length of the author and venue frequency lists and of the co-author "
        "top pairs and collaborators",
    ),
    max_authors: int | None = typer.Option(None, "--max-authors", help=_MAX_AUTHORS_HELP),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Describe a bibliography: what it holds and how complete its records are.

    Offline, descriptive counts grouped into sections: entries and duplicate
    keys, entry types, years, the most frequent authors and venues, the
    co-authorship network in brief, identifier and field coverage, groups,
    `lint` findings, and linked-file and Pinax materials. Each section
    composes an existing report — the `lint` section is exactly `lint`'s
    summary — so the numbers reconcile with the commands that produced them.
    `coauthors` reports the whole co-author network. Counts describe the
    records; they never score the works.
    """
    if top < 0:
        raise InvalidInputError("--top must not be negative")
    if max_authors is not None and max_authors < 0:
        raise InvalidInputError("--max-authors must not be negative")
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    sections = [item.value for item in section] or None
    report = analyze_bibliography(coll, sections=sections, top=top, max_authors=max_authors)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "analyze",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": report.warnings,
                **report.to_dict(),
            }
        )
        return

    typer.echo(f"{file}:")
    for name, data in report.sections.items():
        typer.echo(f"  {name}: {_describe(name, data)}")
    for warning in report.warnings:
        typer.echo(f"warning: {warning['message']}")


def _describe(name: str, data: dict) -> str:
    """Return a one-line human summary of one section."""
    if name == "entries":
        text = f"{data['total']} entries, {data['unique_keys']} distinct keys"
        if data["duplicate_keys"]:
            text += f", {len(data['duplicate_keys'])} duplicated"
        return text
    if name == "types":
        return _pairs(data["counts"], "type")
    if name == "years":
        if data["earliest"] is None:
            return f"no dated entries ({data['undated']} undated)"
        return (
            f"{data['earliest']}-{data['latest']}, {data['dated']} dated, {data['undated']} undated"
        )
    if name == "authors":
        return f"{data['distinct']} distinct; " + _pairs(data["top"], "name")
    if name == "coauthors":
        text = (
            f"{data['authors']} authors, {data['pairs']} pairs, {data['components']} components "
            f"(largest {data['largest_component']})"
        )
        if data["variant_candidates"]:
            text += f", {data['variant_candidates']} name-variant candidates"
        return text
    if name == "venues":
        return f"{data['distinct']} distinct; " + _pairs(data["top"], "venue")
    if name == "identifiers":
        return ", ".join(
            f"{field} {item['present']}/{data['total']}" for field, item in data["fields"].items()
        )
    if name == "fields":
        return f"{data['distinct']} distinct; " + _pairs(data["counts"][:8], "field")
    if name == "groups":
        return (
            f"{data['declared']} declared, {data['entries_with_groups']} grouped, "
            f"{data['entries_without_groups']} ungrouped"
        )
    if name == "lint":
        return (
            f"{data['issues']} findings ({data['errors']} errors, {data['warnings']} warnings, "
            f"{data['info']} info), {data['suppressed']} suppressed"
        )
    linked = data["linked_files"]
    text = f"{linked['entries_with_files']} entries link files"
    if "missing" in linked:
        text += f" ({linked['missing']} missing)"
    pinax = data["pinax"]
    if pinax.get("configured") and "keys_with_materials" in pinax:
        text += f"; pinax materials for {pinax['keys_with_materials']}/{pinax['keys']} keys"
    return text


def _pairs(items: list[dict], label: str) -> str:
    return ", ".join(f"{item[label]} ({item['entries']})" for item in items) or "(none)"


def register(app: typer.Typer) -> None:
    """Register this command on its Typer application."""
    app.command()(_safe(analyze))
