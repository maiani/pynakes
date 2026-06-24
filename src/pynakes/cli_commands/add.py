"""CLI command registration for ``pynakes add``.

A single comprehensive importer: it auto-detects whether the identifier is a DOI
or an arXiv id/URL, fetches authoritative metadata, and appends a prepared
entry. arXiv entries are written as ``@online`` in BibLaTeX libraries and
``@misc`` in BibTeX ones (per ``databaseType``; default BibTeX). No PDFs or
linked files are downloaded.
"""

import json as _json
from typing import Optional

import typer

from pynakes import importer as importer_ops
from pynakes.cli_common import (
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection

# --- add -------------------------------------------------------------------


def add(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    identifier: str = typer.Argument(..., help="DOI, DOI URL, arXiv id, or arXiv URL to import"),
    key: Optional[str] = typer.Option(None, "--key", help="Citation key to use"),
    key_source: str = typer.Option(
        "generated",
        "--key-source",
        help="Citation key source when --key is absent: generated or provider",
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Import even if the reference already exists"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a reference by DOI or arXiv identifier."""
    if key_source not in importer_ops.KEY_SOURCES:
        _emit_error(
            json_output,
            "InvalidKeySource",
            f"Invalid key source {key_source!r}; expected one of: "
            f"{', '.join(sorted(importer_ops.KEY_SOURCES))}",
        )

    try:
        coll = Collection.open(file)
        kind, entry = coll.import_reference(
            identifier,
            key=key,
            key_source=key_source,
            allow_duplicate=allow_duplicate,
        )
    except importer_ops.UnsupportedIdentifierError as exc:
        _emit_error(json_output, "UnsupportedIdentifier", str(exc))
    except ValueError as exc:
        _emit_error(json_output, "InvalidIdentifier", str(exc))
    except importer_ops.DuplicateReferenceError as exc:
        if json_output:
            typer.echo(
                _json.dumps(
                    {
                        "status": "conflict",
                        "error": "DuplicateReference",
                        "message": str(exc),
                        "identifier": exc.identifier,
                        "existing_keys": exc.keys,
                        "options": [
                            {
                                "id": "keep_existing",
                                "description": "Do not import a duplicate reference",
                            },
                            {
                                "id": "allow_duplicate",
                                "description": "Retry with --allow-duplicate",
                            },
                        ],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(f"DuplicateReference: {exc}")
            typer.echo("Retry with --allow-duplicate to import another copy.")
        raise typer.Exit(code=2) from exc
    except importer_ops.CitationKeyConflictError as exc:
        _emit_conflict(
            json_output,
            "CitationKeyConflict",
            str(exc),
            key=exc.key,
            options=[
                {"id": "choose_key", "description": "Retry with a different --key"},
                {"id": "auto_key", "description": "Retry without --key"},
            ],
        )
    except importer_ops.ReferenceImportError as exc:
        _emit_error(json_output, "ReferenceImportError", str(exc))

    verb = "Would add" if dry_run else "Added"
    label = entry.fields.get("doi") or entry.fields.get("eprint") or entry.key
    _finish_mod(
        file,
        "add",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} {kind} {label} as {entry.key}."],
        identifier_type=kind,
        identifier=label,
        doi=entry.fields.get("doi"),
        key=entry.key,
        key_source="user" if key else key_source,
        entry_type=entry.type,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("add")(_safe(add))
