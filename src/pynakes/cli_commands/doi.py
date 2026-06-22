"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json
from typing import Optional

import typer

from pynakes import doi as doi_ops
from pynakes.cli_common import (
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection

# --- doi -------------------------------------------------------------------


def doi_import(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    doi: str = typer.Argument(..., help="DOI or DOI URL to import"),
    key: Optional[str] = typer.Option(None, "--key", help="Citation key to use"),
    key_source: str = typer.Option(
        "generated",
        "--key-source",
        help="Citation key source when --key is absent: generated or provider",
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Import even if the DOI already exists"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Import a reference from a DOI."""
    if key_source not in doi_ops.KEY_SOURCES:
        _emit_error(
            json_output,
            "InvalidKeySource",
            f"Invalid key source {key_source!r}; expected one of: "
            f"{', '.join(sorted(doi_ops.KEY_SOURCES))}",
        )

    try:
        coll = Collection.open(file)
        entry = coll.import_doi(
            doi,
            key=key,
            key_source=key_source,
            allow_duplicate_doi=allow_duplicate,
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidDOI", str(exc))
    except doi_ops.DuplicateDOIError as exc:
        if json_output:
            typer.echo(
                _json.dumps(
                    {
                        "status": "conflict",
                        "error": "DuplicateDOI",
                        "message": str(exc),
                        "doi": exc.doi,
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
            typer.echo(f"DuplicateDOI: {exc}")
            typer.echo("Retry with --allow-duplicate to import another copy.")
        raise typer.Exit(code=2) from exc
    except doi_ops.CitationKeyConflictError as exc:
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
    except doi_ops.DOIImportError as exc:
        _emit_error(json_output, "DOIImportError", str(exc))

    verb = "Would import" if dry_run else "Imported"
    _finish_mod(
        file,
        "doi_import",
        coll,
        dry_run,
        diff,
        json_output,
        [f"{verb} DOI {entry.fields['doi']} as {entry.key}."],
        doi=entry.fields["doi"],
        key=entry.key,
        key_source="user" if key else key_source,
        entry_type=entry.type,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("import")(_safe(doi_import))
