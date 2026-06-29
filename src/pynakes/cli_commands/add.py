"""CLI command registration for ``pynakes add``."""

import re

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography

_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")


def _parse_field_assignments(assignments: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Field assignment must use name=value syntax: {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        if not _FIELD_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid field name: {name!r}")
        if name.lower() in {"key", "type"}:
            raise ValueError(f"{name!r} is not a field; use the citation key or --type")
        fields[name] = value.strip()
    return fields


def add(
    key: str = typer.Argument(..., help="Citation key for the new entry"),
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    entry_type: str = typer.Option("article", "--type", help="BibTeX/BibLaTeX entry type"),
    field: list[str] = typer.Option(
        [], "--field", "-f", help="Field assignment, repeatable: name=value"
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Append even if the citation key already exists"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a manually specified reference entry."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)
    try:
        fields = _parse_field_assignments(field)
        coll = Bibliography.open(file)
        entry = coll.add_entry(
            entry_type,
            key,
            fields,
            allow_duplicate=allow_duplicate,
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))
        return

    human = [f"{_verb('add', params)} {entry.type} {entry.key}."]
    _finish_mod(
        file,
        "add",
        coll,
        params,
        human,
        key=entry.key,
        entry_type=entry.type,
        fields=dict(entry.fields),
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("add")(_safe(add))
