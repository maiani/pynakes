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

import sys

import typer

from pynakes.cli_choices import KeySource
from pynakes.cli_commands._fetch_report import fetch_report_lines
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.model import BibEntry


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


def key_pattern_warnings(coll: Bibliography, file: str) -> list[dict[str, object]]:
    """Warn when generated keys would not follow the library's evident style.

    Run before staging: the library's own keys are the evidence. Nothing is
    reported when a ``key-pattern`` is stored or the keys follow the default.
    """
    from pynakes import keys as keys_ops
    from pynakes._keys_pattern import DEFAULT_PATTERN
    from pynakes.metadata import library_key_pattern

    if library_key_pattern(coll.lib, "") is not None:
        return []
    inference = keys_ops.infer_key_pattern(coll.lib)
    if inference.pattern is None or inference.pattern == DEFAULT_PATTERN:
        return []
    return [
        {
            "type": "key_pattern_unset",
            "pattern": inference.pattern,
            "matched": inference.matched,
            "checked": inference.checked,
            "message": (
                f"No key-pattern is stored, so generated keys use pynakes' default style, "
                f"but {inference.matched} of {inference.checked} existing keys follow "
                f"{inference.pattern}. Adopt it with: "
                f"pynakes metadata set {file} key-pattern '{inference.pattern}'"
            ),
        }
    ]


def published_version_warnings(entries: list[BibEntry], file: str) -> list[dict[str, object]]:
    """Point out imported preprints whose record already names a published DOI.

    The import keeps what the preprint server described, so such an entry stays
    a preprint type with the journal's DOI. Promotion is a separate, online,
    reviewable step; this names the command and the keys it applies to.
    """
    from pynakes._identifiers import is_arxiv_doi
    from pynakes._integrity_common import _PREPRINT_DOI_PREFIXES
    from pynakes.identity import entry_arxiv_id

    keys = [
        entry.key
        for entry in entries
        if entry.type.lower() in {"misc", "online", "unpublished"}
        and entry_arxiv_id(entry)
        and (doi := entry.fields.get("doi", "").strip())
        and not is_arxiv_doi(doi)
        and not doi.lower().startswith(_PREPRINT_DOI_PREFIXES)
    ]
    if not keys:
        return []
    joined = ",".join(keys)
    return [
        {
            "type": "published_version_available",
            "keys": keys,
            "message": (
                f"Imported as a preprint, but the record names a published DOI: "
                f"{', '.join(keys)}. Promote with: "
                f"pynakes enrich {file} --published --online --key {joined}"
            ),
        }
    ]


def import_reference(
    file: str | None = bib_file_argument(),
    identifiers: list[str] = typer.Argument(
        ...,
        help="One or more DOIs, repository identifiers, or supported reference URLs. "
        "Append =KEY to name an entry's citation key (arXiv:2301.00001=Lovelace1843). "
        'Use "-" to read them from stdin, one per line',
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="Citation key to use (only with a single identifier; for several, "
        "write each as IDENTIFIER=KEY)",
    ),
    key_source: KeySource | None = typer.Option(
        None,
        "--key-source",
        help="Citation key source when --key is absent: generated or provider; default: "
        "the library's import-key-source setting, else generated",
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
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
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
    # The importer pulls in provider and HTTP code; load it only to import.
    from pynakes import importer as importer_ops

    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    positional = list(identifiers)
    if positional == ["-"]:
        positional = read_identifier_lines(sys.stdin.read())
        if not positional:
            _emit_error(json_output, "InvalidInput", "No identifiers were read from stdin")
            return
    if not positional:
        _emit_error(json_output, "InvalidInput", "No identifier to import")
        return
    pairs = [importer_ops.split_identifier_key(value) for value in positional]
    if key is not None and len(pairs) > 1:
        _emit_error(
            json_output,
            "InvalidInput",
            "--key names the key for one entry; to name keys for several identifiers, "
            "write each as IDENTIFIER=KEY",
        )
        return
    if key is not None and pairs[0][1] is not None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Give the citation key either with --key or as IDENTIFIER=KEY, not both",
        )
        return

    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    # Before any provider is asked: a stale precondition should cost no lookup.
    _check_expected_sha256(file, coll, params)
    source = importer_ops.library_key_source(
        coll.lib, None if key_source is None else key_source.value
    )
    generates_keys = source == "generated" and (
        key is None and any(pair_key is None for _, pair_key in pairs)
    )
    pattern_warnings = key_pattern_warnings(coll, file) if generates_keys else []
    if len(pairs) > 1:
        _import_several(
            coll, file, pairs, params, source, allow_duplicate, cache_file, pattern_warnings
        )
        return

    identifier, pair_key = pairs[0]
    key = key if key is not None else pair_key
    entry = None
    try:
        kind, entry = coll.import_reference(
            identifier,
            key=key,
            key_source=source,
            allow_duplicate=allow_duplicate,
        )
    except importer_ops.UnsupportedIdentifierError as exc:
        _emit_error(json_output, "UnsupportedIdentifier", str(exc))
        return
    except ValueError as exc:
        _emit_error(json_output, "InvalidIdentifier", str(exc))
        return
    except importer_ops.DuplicateReferenceError as exc:
        _emit_conflict(
            json_output,
            "DuplicateReference",
            str(exc),
            identifier=exc.identifier,
            existing_keys=exc.keys,
            options=[
                {"id": "keep_existing", "description": "Do not import a duplicate reference"},
                {"id": "allow_duplicate", "description": "Retry with --allow-duplicate"},
            ],
        )
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
        "key_source": "user" if key else source,
        "entry_type": entry.type,
    }
    if fetch_report is not None:
        details["fetch"] = fetch_report

    warnings = [*pattern_warnings, *published_version_warnings([entry], file)]
    human.extend(f"  {warning['message']}" for warning in warnings)
    _finish_mod(
        file,
        "ref_import",
        coll,
        params,
        human,
        warnings=warnings,
        **details,
    )


def _import_several(
    coll: Bibliography,
    file: str,
    identifiers: list[tuple[str, str | None]],
    params: RunParams,
    key_source: str,
    allow_duplicate: bool,
    cache_file: str | None,
    pattern_warnings: list[dict[str, object]],
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
    # The importer pulls in provider and HTTP code; load it only to import.
    from pynakes import importer as importer_ops

    results: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = list(pattern_warnings)
    imported_entries: list[BibEntry] = []
    imported = 0
    for identifier, key in identifiers:
        try:
            kind, entry = coll.import_reference(
                identifier,
                key=key,
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
            warnings.append(
                {
                    "type": "duplicate_reference",
                    "identifier": identifier,
                    "message": f"{identifier}: already present as {', '.join(exc.keys)}; skipped.",
                }
            )
            continue
        except importer_ops.CitationKeyConflictError as exc:
            results.append(
                {
                    "identifier": identifier,
                    "status": "failed",
                    "reason": "key_conflict",
                    "key": exc.key,
                    "message": str(exc),
                }
            )
            warnings.append(
                {
                    "type": "import_failed",
                    "identifier": identifier,
                    "message": f"{identifier}: {exc}; name another key.",
                }
            )
            continue
        except (
            importer_ops.UnsupportedIdentifierError,
            importer_ops.ReferenceImportError,
            ValueError,
        ) as exc:
            results.append({"identifier": identifier, "status": "failed", "message": str(exc)})
            warnings.append(
                {
                    "type": "import_failed",
                    "identifier": identifier,
                    "message": f"{identifier}: {exc}",
                }
            )
            continue
        imported += 1
        imported_entries.append(entry)
        results.append(
            {
                "identifier": importer_ops.imported_entry_identifier(entry, kind),
                "status": "imported",
                "identifier_type": kind,
                "key": entry.key,
                "key_source": "user" if key else key_source,
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

    warnings.extend(published_version_warnings(imported_entries, file))
    failed = sum(1 for result in results if result["status"] == "failed")
    skipped = sum(1 for result in results if result["status"] == "skipped")
    human = [
        f"{_verb('import', params, 'Imported')} {imported} of {len(identifiers)} reference(s)"
        f" ({skipped} already present, {failed} unresolved)."
    ]
    human.extend(f"  {warning['message']}" for warning in warnings)

    _finish_mod(
        file,
        "ref_import",
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
