"""CLI command registration for ``pynakes ref import``.

Resolving several identifiers in one call is not a convenience wrapper around
the single-identifier path: it changes what a failure means. One identifier that
does not resolve is a failed command. One of eight that does not resolve is
information — very often *the* information, since a reference an assistant
invented is exactly a plausible identifier that no provider has heard of. So a
multi-identifier import reports per-identifier outcomes and commits whatever
resolved, in one write, while a single-identifier import keeps its existing
error and conflict envelopes byte for byte.
"""

import json
import sys

import typer

from pynakes import importer as importer_ops
from pynakes.cli_commands._fetch_report import fetch_report_lines
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_option,
)
from pynakes.engine import Bibliography


#: Identifiers never end in ``.bib``, so a trailing positional that does marks
#: the library rather than another thing to resolve. This keeps the long-standing
#: ``ref import <identifier> <file>`` order working now that the identifier
#: argument is variadic.
def split_library_argument(tokens: list[str]) -> tuple[list[str], str | None]:
    """Split positional tokens into identifiers and an optional library path."""
    if tokens and tokens[-1].lower().endswith(".bib"):
        return tokens[:-1], tokens[-1]
    return tokens, None


def read_identifier_lines(text: str) -> list[str]:
    """Parse identifiers from piped text: one per line, ``#`` comments ignored.

    Pasting a list an assistant produced is the case this serves, so the format
    is the most forgiving one that stays unambiguous — blank lines and comments
    are skipped, and surrounding whitespace is dropped.
    """
    identifiers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            identifiers.append(stripped)
    return identifiers


def import_reference(
    identifiers: list[str] = typer.Argument(
        ...,
        help="One or more DOIs, repository identifiers, or supported reference URLs. "
        'Use "-" to read them from stdin, one per line',
    ),
    file: str | None = bib_file_option(),
    key: str | None = typer.Option(
        None, "--key", help="Citation key to use (only with a single identifier)"
    ),
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
    cache_file: str | None = _CACHE_FILE_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Import one or more references from supported identifiers or URLs.

    Several identifiers resolve in one call and commit in one write. Each is
    reported individually, and one that does not resolve does not stop the
    others — a list an assistant produced routinely contains a reference that
    does not exist, and identifying it is the point rather than a reason to
    abandon the rest. A single identifier keeps its existing behavior: a failure
    is the command's failure.
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    positional, trailing = split_library_argument(list(identifiers))
    if trailing is not None:
        if file is not None:
            _emit_error(
                json_output,
                "InvalidInput",
                "Specify the library once, not both positionally and with --file",
            )
            return
        file = trailing
    if positional == ["-"]:
        positional = read_identifier_lines(sys.stdin.read())
        if not positional:
            _emit_error(json_output, "InvalidInput", "No identifiers were read from stdin")
            return
    if not positional:
        _emit_error(json_output, "InvalidInput", "No identifier to import")
        return
    if key is not None and len(positional) > 1:
        _emit_error(
            json_output,
            "InvalidInput",
            "--key names the key for one entry; omit it when importing several identifiers",
        )
        return

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
    if len(positional) > 1:
        _import_several(coll, file, positional, params, key_source, allow_duplicate, cache_file)
        return

    identifier = positional[0]
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
                json.dumps(
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
            fetch_report = coll.fetch_materials(
                target=entry.key,
                dry_run=params.dry_run,
                cache_file=cache_file,
            )
        except ValueError as exc:
            _emit_error(json_output, "InvalidInput", str(exc))
            return

    label = importer_ops.imported_entry_identifier(entry, kind)
    human = [f"{_verb('import', params, 'Imported')} {kind} {label} as {entry.key}."]
    if fetch_report is not None:
        human.extend(
            fetch_report_lines(
                fetch_report,
                skipped_prefix="Skipped fetch for",
                failed_prefix="Failed fetch for",
            )
        )

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


def _import_several(
    coll: Bibliography,
    file: str,
    identifiers: list[str],
    params: RunParams,
    key_source: str,
    allow_duplicate: bool,
    cache_file: str | None,
) -> None:
    """Resolve several identifiers, then commit whatever resolved in one write.

    Each identifier gets its own outcome, and a failure is recorded rather than
    raised: the useful answer to "here are eight references" is which ones are
    real, not a stop at the first that is not. The write stays atomic because
    every resolved entry is staged in memory and committed once, so the file
    never holds half a list.

    A duplicate is reported as ``skipped`` rather than as a conflict. Exit 2 is
    for a question only the caller can answer, and here there is nothing to
    decide: the other identifiers still have to be resolved, and re-running with
    ``--allow-duplicate`` is the answer if a second copy really was wanted.
    """
    results: list[dict[str, object]] = []
    warnings: list[str] = []
    imported = 0
    for identifier in identifiers:
        try:
            kind, entry = coll.import_reference(
                identifier,
                key_source=key_source,
                allow_duplicate=allow_duplicate,
            )
        except importer_ops.DuplicateReferenceError as exc:
            results.append(
                {
                    "identifier": identifier,
                    "status": "skipped",
                    "reason": "duplicate",
                    "existing_keys": exc.keys,
                    "message": str(exc),
                }
            )
            warnings.append(f"{identifier}: already present as {', '.join(exc.keys)}; skipped.")
            continue
        except (
            importer_ops.UnsupportedIdentifierError,
            importer_ops.ReferenceImportError,
            ValueError,
        ) as exc:
            results.append({"identifier": identifier, "status": "failed", "message": str(exc)})
            warnings.append(f"{identifier}: {exc}")
            continue
        imported += 1
        results.append(
            {
                "identifier": importer_ops.imported_entry_identifier(entry, kind),
                "status": "imported",
                "identifier_type": kind,
                "key": entry.key,
                "entry_type": entry.type,
                "doi": entry.fields.get("doi"),
            }
        )

    if imported == 0:
        _emit_error(
            params.json_output,
            "ReferenceImportError",
            f"None of the {len(identifiers)} identifiers could be imported.",
            results=results,
            warnings=warnings,
        )
        return

    failed = sum(1 for result in results if result["status"] == "failed")
    skipped = sum(1 for result in results if result["status"] == "skipped")
    human = [
        f"{_verb('import', params, 'Imported')} {imported} of {len(identifiers)} reference(s)"
        f" ({skipped} already present, {failed} unresolved)."
    ]
    human.extend(f"  {line}" for line in warnings)

    _finish_mod(
        file,
        "import",
        coll,
        params,
        human,
        warnings=warnings,
        requested=len(identifiers),
        imported=imported,
        skipped=skipped,
        failed=failed,
        results=results,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("import")(_safe(import_reference))
