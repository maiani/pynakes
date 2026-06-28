"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json
from typing import Optional

import typer

from pynakes import importer as importer_ops
from pynakes.cli_common import (
    _entries,
    _resolve_input_bib,
    _safe,
)
from pynakes.filestore import FileStore
from pynakes.io import load_bib

# --- inspect ---------------------------------------------------------------


def inspect(
    file: Optional[str] = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    resolved: bool = typer.Option(
        False,
        "--resolved",
        help="Include each entry's resolved fields (crossref/xdata inheritance applied)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a .bib file structure.

    The JSON form is the canonical structured read of a library: every entry
    with its fields, the ``@string``/``@preamble``/comment declarations, both
    metadata namespaces, encoding, line ending, and duplicate keys. With
    ``--resolved`` each entry also carries its inherited (crossref/xdata) field
    view.
    """
    file = _resolve_input_bib(file, json_output)
    lib = load_bib(file)
    duplicates = lib.entries.duplicate_keys()
    store = FileStore.from_metadata(lib, file)

    if json_output:
        entries = []
        for entry in lib.entries.values():
            record = {"key": entry.key, "type": entry.type, "fields": dict(entry.fields)}
            if resolved:
                record["resolved_fields"] = lib.resolved_fields(entry)
            if store is not None:
                record.update(
                    store.annotation_for(
                        entry.key,
                        refetchable=importer_ops.entry_arxiv_id(entry) is not None,
                    )
                )
            entries.append(record)
        result = {
            "status": "success",
            "action": "inspect",
            "file": file,
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
        typer.echo(_json.dumps(result, indent=2))
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
        typer.echo(f"Duplicate keys: {', '.join(f'{k} ×{n}' for k, n in duplicates.items())}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(inspect))
