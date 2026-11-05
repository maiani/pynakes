"""Library-level additions with explicit routing evidence and guarded writes."""

from pathlib import Path

import typer

from pynakes.cli._common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    _EXTERNAL_MODIFICATION_OPTIONS,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _safe,
)
from pynakes.cli.commands._reference import parse_field_assignments
from pynakes.cli.commands.add import _missing_required_fields
from pynakes.library import Library, LibraryRoutingError
from pynakes.model import BibEntry


def add(
    manifest: str = typer.Argument(..., help="Library .library.toml manifest"),
    key: str = typer.Argument(..., help="Citation key for the new reference"),
    entry_type: str = typer.Option("article", "--type", help="BibTeX/BibLaTeX entry type"),
    field: list[str] = typer.Option([], "--field", help="Field assignment, repeatable: name=value"),
    destination: str | None = typer.Option(
        None, "--destination", help="Override routing with a member path relative to the manifest"
    ),
    expect_library_sha256: str | None = typer.Option(
        None, "--expect-library-sha256", help="Require the Library fingerprint from a preview"
    ),
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview routing and addition without writing"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show the destination bibliography diff"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the addition and routing evidence as JSON"
    ),
) -> None:
    """Add supplied reference metadata to its routed Library member.

    Higher rule priorities win; ties and existing-work candidates need review.
    No match uses the manifest's fallback. --destination overrides placement rules,
    never existing-work checks. Offline; does not acquire or move PDFs.
    """
    lib = Library.open(manifest)
    if expect_library_sha256 is not None and expect_library_sha256 != lib.source_sha256:
        _emit_conflict(
            json_output,
            "ExternalModification",
            "Library changed since the reviewed preview",
            file=str(Path(manifest)),
            options=_EXTERNAL_MODIFICATION_OPTIONS,
        )
    entry = BibEntry(
        key=key, type=entry_type.strip().lower(), fields=parse_field_assignments(field)
    )
    try:
        staged = lib.stage_entry(entry, destination=destination)
    except LibraryRoutingError as exc:
        details = {"routing": exc.decision.to_dict(), "library_sha256": lib.source_sha256}
        if exc.decision.status == "incomplete":
            _emit_error(json_output, "InvalidInput", str(exc), **details)
        _emit_conflict(
            json_output,
            "LibraryRoutingConflict",
            str(exc),
            options=[
                {"id": "review_existing", "description": "Review reported existing works and keys"},
                {
                    "id": "choose_destination",
                    "description": "For placement conflicts, retry with --destination MEMBER",
                },
            ],
            **details,
        )
        return
    coll = staged.bibliography
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    warnings = []
    missing = _missing_required_fields(coll, entry.type, entry.fields)
    if missing:
        warnings.append(
            {
                "type": "missing_required_fields",
                "fields": missing,
                "message": f"Entry {key} is missing required fields: {', '.join(missing)}",
            }
        )
    decision = staged.decision
    names = ", ".join(
        rule.name for rule in decision.matched_rules if rule.destination == decision.destination
    )
    human = [
        f"Destination: {decision.destination} ({decision.reason}{': ' + names if names else ''})."
    ]
    _finish_mod(
        str(coll.path),
        "library_add",
        coll,
        params,
        human,
        warnings=warnings,
        key=entry.key,
        entry_type=entry.type,
        fields=entry.fields,
        manifest=str(lib.manifest),
        routing=decision.to_dict(),
        library_sha256=staged.library_sha256,
    )


def register(app: typer.Typer) -> None:
    """Register Library operations."""
    app.command("add")(_safe(add))
