"""CLI command registration for ``pynakes capabilities``.

The full description runs to well over a hundred kilobytes, almost all of it
per-command option schemas. A caller discovering the tool needs a map first
and one command's details later, so ``--json`` returns a compact index by
default and the details on request — the same bounded-read idea the entry
reads follow.
"""

import json
from enum import StrEnum

import typer

from pynakes.capabilities import get_capabilities
from pynakes.cli_common import InvalidInputError, _emit_json, _safe

# --- capabilities ------------------------------------------------

#: Sections that stay in the default index: small, and needed to read any
#: envelope correctly. Every other section is listed by name and size.
_INDEX_KEYS = (
    "tool",
    "version",
    "description",
    "network_access_is_explicit",
    "supports_dry_run",
    "supports_json_output",
    "supports_backup",
    "supports_atomic_write",
    "supports_multiple_files",
    "exit_codes",
    "positional_convention",
    "metadata_namespaces",
    "gate_commands",
)


class CapabilitySection(StrEnum):
    """``capabilities --section``: one detailed part of the description."""

    ANALYSIS = "analysis"
    ENTRY_FIELDS = "entry_fields"
    FIELD_ENCODING = "field_encoding"
    SELECTION_EXPORT = "selection_export"
    GROUPS_SEPARATOR = "groups_separator"
    BATCH_OPERATIONS = "batch_operations"
    BOUNDED_READS = "bounded_reads"
    CAPABILITIES = "capabilities"
    COMMAND_GROUPS = "command_groups"
    COMMANDS = "commands"
    DEPRECATIONS = "deprecations"
    ERROR_CODES = "error_codes"
    FORMATTING = "formatting"
    MATERIAL_COLLECTION = "material_collection"
    PREDICATE_GRAMMAR = "predicate_grammar"
    PYTHON_API = "python_api"
    SAVED_QUERIES = "saved_queries"
    SEARCH_QUERY_GRAMMAR = "search_query_grammar"
    WORK_MATCHING = "work_matching"
    WRITE_PRECONDITION = "write_precondition"


def _index(caps: dict) -> dict:
    """Return the discovery index: the map, not the territory."""
    details = {key: value for key, value in caps.items() if key not in _INDEX_KEYS}
    details.pop("command_schemas", None)
    return {
        **{key: caps[key] for key in _INDEX_KEYS if key in caps},
        "command_index": {
            path: schema["help"].strip().splitlines()[0] if schema["help"] else ""
            for path, schema in sorted(caps["command_schemas"].items())
        },
        "sections": {
            name: len(json.dumps(value, separators=(",", ":")))
            for name, value in sorted(details.items())
        },
        "more": "capabilities --command 'PATH' returns one command's options (repeatable); "
        "--section NAME returns one section (repeatable); --all returns everything",
    }


def capabilities(
    command: list[str] | None = typer.Option(
        None,
        "--command",
        metavar="PATH",
        help="Return the full schema of this command, e.g. 'ref show' (repeatable)",
    ),
    section: list[CapabilitySection] | None = typer.Option(
        None,
        "--section",
        help="Return this section of the description, e.g. predicate_grammar (repeatable)",
    ),
    everything: bool = typer.Option(
        False, "--all", help="Return the whole description (large: every command's schema)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show what pynakes can do: a compact index, or the details asked for.

    `--json` returns an index — exit codes, conventions, a one-line summary
    of every command, and the names and sizes of the detailed sections. Ask
    for one command's options with `--command 'ref show'` and for a section
    with `--section predicate_grammar`; `--all` returns everything.
    """
    caps = get_capabilities()
    if json_output:
        payload: dict = {"status": "success", "action": "capabilities", "warnings": []}
        if everything:
            payload.update(caps)
        elif command or section:
            payload.update(_selected(caps, command or [], [item.value for item in section or []]))
        else:
            payload.update(_index(caps))
        _emit_json(payload)
        return
    typer.echo(f"{caps['tool']} v{caps['version']}")
    descriptions = caps["commands"]
    for panel, names in caps["command_groups"].items():
        typer.echo(f"\n{panel}:")
        for name in names:
            typer.echo(f"  {name:14} {descriptions[name]}")


def _selected(caps: dict, commands: list[str], sections: list[str]) -> dict:
    """Return the named command schemas and sections, refusing unknown names."""
    schemas = caps["command_schemas"]
    unknown_commands = [path for path in commands if path not in schemas]
    if unknown_commands:
        raise InvalidInputError(
            f"No command {', '.join(map(repr, unknown_commands))}; "
            "capabilities --json lists every command under command_index"
        )
    unknown_sections = [name for name in sections if name not in caps]
    if unknown_sections:
        raise InvalidInputError(
            f"No section {', '.join(map(repr, unknown_sections))}; "
            "capabilities --json lists them under sections"
        )
    selected: dict = {name: caps[name] for name in sections}
    if commands:
        selected["command_schemas"] = {path: schemas[path] for path in commands}
    return selected


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(capabilities))
