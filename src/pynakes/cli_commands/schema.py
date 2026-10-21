"""Read-only field schema discovery for thin clients."""

import typer

from pynakes.cli_choices import Dialect
from pynakes.cli_common import (
    _emit_json,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.entry_types import entry_field_schema, entry_type_names
from pynakes.metadata import library_dialect


def ref_schema(
    file: str | None = bib_file_argument(),
    entry_type: str | None = typer.Argument(
        None, help="Entry type; omit for all known and existing types"
    ),
    dialect: Dialect | None = typer.Option(None, "--dialect", help="Override the library dialect"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Describe required alternatives, profile requirements, and optional fields.

    Existing fields outside the suggestions appear in `other`; they remain
    editable. Optional suggestions are not an exhaustive style data model.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    resolved = dialect or library_dialect(coll.lib)
    types = (
        [entry_type.lower()]
        if entry_type
        else sorted(
            set(entry_type_names(dialect=resolved))
            | {entry.type.lower() for entry in coll.lib.entries.values()}
        )
    )
    existing: dict[str, list[str]] = {}
    for entry in coll.lib.entries.values():
        existing.setdefault(entry.type.lower(), []).extend(entry.fields)
    schemas = [
        entry_field_schema(name, dialect=resolved, lib=coll.lib, fields=existing.get(name, ()))
        for name in types
    ]
    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "ref_schema",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "dialect": resolved,
                "entry_schemas": schemas,
            }
        )
        return
    for schema in schemas:
        typer.echo(f"{schema['entry_type']} ({resolved})")
        for label in ("required", "profile_required", "optional", "other"):
            typer.echo(f"  {label}: {schema[label]}")


def register(app: typer.Typer) -> None:
    """Register schema discovery under ref."""
    app.command("schema")(_safe(ref_schema))
