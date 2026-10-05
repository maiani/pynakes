"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes.authors import split_name_list
from pynakes.cli_common import (
    _emit_json,
    _entries,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.fields import TITLE_FIELDS
from pynakes.filestore import FileStore
from pynakes.formatters import latex_to_plain_text
from pynakes.identity import entry_arxiv_id

# --- inspect ---------------------------------------------------------------


def _display_view(fields: dict[str, str]) -> dict[str, object]:
    """Project title/name fields to human-readable text.

    Title-family fields are cleaned with ``latex_to_plain_text``. ``author``/
    ``editor`` are split into individual people first (``split_name_list``,
    brace-aware) and each name is cleaned afterward — cleaning before splitting
    would strip the braces that protect a corporate name containing "and"
    (``{Smith and Sons}``) from being split into two people.
    """
    display: dict[str, object] = {}
    for name in TITLE_FIELDS:
        if name in fields:
            display[name] = latex_to_plain_text(fields[name])
    for name in ("author", "editor"):
        if name in fields:
            display[name] = [
                latex_to_plain_text(person) for person in split_name_list(fields[name])
            ]
    return display


def inspect(
    file: str | None = bib_file_argument(),
    resolved: bool = typer.Option(
        False,
        "--resolved",
        help="Include each entry's resolved fields (crossref/xdata inheritance applied)",
    ),
    display: bool = typer.Option(
        False,
        "--display",
        help="Include each entry's LaTeX/brace-cleaned title fields and split, cleaned author/editor names",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a .bib file structure.

    The JSON form is the canonical structured read of a library: every entry
    with its fields, the ``@string``/``@preamble``/comment declarations, both
    metadata namespaces, encoding, line ending, and duplicate keys. With
    ``--resolved`` each entry also carries its inherited (crossref/xdata) field
    view. With ``--display`` each entry also carries a ``display`` view: title
    fields with LaTeX markup and braces cleaned to readable text, and
    ``author``/``editor`` split into individual, cleaned names — a presentation
    projection for a UI, never a value to write back. Cleaning is applied to
    the resolved fields when ``--resolved`` is also given, otherwise to the
    entry's own fields.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    lib = coll.lib
    duplicates = lib.entries.duplicate_keys()
    store = FileStore.from_metadata(lib, file)

    if json_output:
        entries = []
        for entry in lib.entries.values():
            record = {"key": entry.key, "type": entry.type, "fields": dict(entry.fields)}
            if resolved:
                record["resolved_fields"] = lib.resolved_fields(entry)
            if display:
                record["display"] = _display_view(record.get("resolved_fields", record["fields"]))
            if store is not None:
                record.update(
                    store.annotation_for(
                        entry.key,
                        refetchable=entry_arxiv_id(entry) is not None,
                    )
                )
            entries.append(record)
        result = {
            "status": "success",
            "action": "inspect",
            "file": file,
            "source_sha256": _source_sha256(coll),
            "warnings": [],
            "encoding": lib.encoding,
            "line_ending": "crlf" if lib.line_ending == "\r\n" else "lf",
            "entry_count": len(lib.entries),
            "entries": entries,
            "strings": dict(lib.strings),
            "preamble": list(lib.preamble),
            "comments": list(lib.raw_comments),
            "jabref_metadata": {
                "values": dict(lib.jabref_metadata),
                "blocks": [block.to_dict() for block in lib.jabref_metadata_blocks],
            },
            "pynakes_metadata": {
                "values": dict(lib.pynakes_metadata),
                "blocks": [block.to_dict() for block in lib.pynakes_metadata_blocks],
            },
            "duplicate_keys": duplicates,
        }
        if store is not None:
            result["pinax"] = {
                "files_dir": str(store.root),
                "manifest": str(store.manifest_path),
            }
        _emit_json(result)
        return

    le = "CRLF" if lib.line_ending == "\r\n" else "LF"
    typer.echo(f"{file}: {len(lib.entries)} {_entries(len(lib.entries))} ({lib.encoding}, {le})")
    declarations = []
    if lib.strings:
        declarations.append(f"{len(lib.strings)} @string")
    if lib.preamble:
        declarations.append(f"{len(lib.preamble)} @preamble")
    if lib.raw_comments:
        declarations.append(f"{len(lib.raw_comments)} comment(s)")
    if declarations:
        typer.echo(f"  {', '.join(declarations)}")
    for entry in lib.entries.values():
        count = len(lib.resolved_fields(entry)) if resolved else len(entry.fields)
        suffix = " resolved" if resolved else ""
        typer.echo(f"  @{entry.type}{{{entry.key}}}  ({count}{suffix} fields)")
    if duplicates:
        instances = lib.entries.duplicate_key_instances()
        parts = []
        for key, indices in instances.items():
            line_refs = ", ".join(f"#{i}" for i in indices)
            parts.append(f"{key} ({line_refs})")
        typer.echo(f"Duplicate keys: {', '.join(parts)}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(inspect))
