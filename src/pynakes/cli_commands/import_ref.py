"""CLI command registration for ``pynakes ref import``."""

import json as _json

import typer

from pynakes import importer as importer_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography


def import_reference(
    identifier: str = typer.Argument(..., help="DOI, DOI URL, arXiv id, or arXiv URL to import"),
    file: str | None = typer.Argument(
        None, help="Path to the .bib file (default: auto-detect single .bib in cwd)"
    ),
    key: str | None = typer.Option(None, "--key", help="Citation key to use"),
    key_source: str = typer.Option(
        "generated",
        "--key-source",
        help="Citation key source when --key is absent: generated or provider",
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Import even if the reference already exists"
    ),
    fetch: bool = typer.Option(
        False,
        "--fetch",
        help="After importing, fetch configured Pinax materials for the new entry",
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Import a reference by DOI or arXiv identifier."""
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    file = _resolve_input_bib(file, json_output)
    if key_source not in importer_ops.KEY_SOURCES:
        _emit_error(
            json_output,
            "InvalidKeySource",
            f"Invalid key source {key_source!r}; expected one of: "
            f"{', '.join(sorted(importer_ops.KEY_SOURCES))}",
        )
        return

    coll = Bibliography.open(file)
    entry = None
    try:
        kind, entry = coll.import_reference(
            identifier,
            key=key,
            key_source=key_source,
            allow_duplicate=allow_duplicate,
        )
    except importer_ops.UnsupportedIdentifierError as exc:
        _emit_error(json_output, "UnsupportedIdentifier", str(exc))
        return
    except ValueError as exc:
        _emit_error(json_output, "InvalidIdentifier", str(exc))
        return
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
        return
    except importer_ops.ReferenceImportError as exc:
        message = str(exc)
        extra = {}
        if params.dry_run:
            message = (
                f"{message}. No changes were written; --dry-run failed before staging an entry."
            )
            extra = {"dry_run": True, "modified": False}
        _emit_error(json_output, "ReferenceImportError", message, **extra)
        return
    if entry is None:
        return

    fetch_report = None
    if fetch:
        try:
            fetch_report = coll.fetch_materials(target=entry.key, dry_run=params.dry_run)
        except ValueError as exc:
            _emit_error(json_output, "InvalidInput", str(exc))
            return

    label = entry.fields.get("doi") or entry.fields.get("eprint") or entry.key
    human = [f"{_verb('import', params, 'Imported')} {kind} {label} as {entry.key}."]
    if fetch_report is not None:
        human.extend(_fetch_human_lines(fetch_report))

    details = {
        "identifier_type": kind,
        "identifier": label,
        "doi": entry.fields.get("doi"),
        "key": entry.key,
        "key_source": "user" if key else key_source,
        "entry_type": entry.type,
    }
    if fetch_report is not None:
        details["fetch"] = fetch_report

    _finish_mod(
        file,
        "import",
        coll,
        params,
        human,
        **details,
    )


def _fetch_human_lines(report: dict) -> list[str]:
    lines: list[str] = []
    for item in report["fetched"]:
        parts = []
        if item["pdf_path"]:
            parts.append("PDF")
        if item["source_path"]:
            parts.append("source")
        label = "+".join(parts) if parts else "materials"
        lines.append(f"Fetched {label} for {item['key']} (arXiv:{item['arxiv_id']}).")
    for item in report["skipped"]:
        lines.append(f"Skipped fetch for {item['key']} ({item['reason']}).")
    for item in report["failed"]:
        lines.append(f"Failed fetch for {item['key']} ({item['error']}).")
    return lines


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("import")(_safe(import_reference))
