"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes import metadata as metadata_ops
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _emit_json,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography

# --- metadata --------------------------------------------------------------


def metadata_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List top-level metadata blocks (both jabref-meta and pynakes-meta)."""
    file = _resolve_input_bib(file, json_output)
    lib = Bibliography.open(file).lib
    all_blocks = lib.metadata_blocks
    warnings = metadata_ops.aliased_drift_warnings(lib)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "metadata_list",
                "file": file,
                "metadata": {
                    "values": dict(lib.jabref_metadata),
                    "blocks": [b.to_dict() for b in lib.jabref_metadata_blocks],
                },
                "pynakes_metadata": {
                    "values": dict(lib.pynakes_metadata),
                    "blocks": [b.to_dict() for b in lib.pynakes_metadata_blocks],
                },
                "effective": dict(lib.metadata),
                "warnings": warnings,
            }
        )
        return

    if not all_blocks:
        typer.echo(f"{file}: no metadata found.")
        return
    for block in all_blocks:
        marker = "known" if block.known else "unknown"
        typer.echo(
            f"  [{block.namespace}:{marker}:{block.category}] "
            f"{block.key} = {block.normalized_value}"
        )
    for warning in warnings:
        typer.echo(f"  warning: {warning}")


def metadata_set(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Metadata key"),
    value: str = typer.Argument(..., help="Metadata value"),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Target comment: jabref or pynakes. Default: auto (JabRef-native keys "
        "→ jabref-meta, everything else → pynakes-meta)",
    ),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="Allow writing an unrecognized key into jabref-meta"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Set one top-level metadata block (jabref-meta or pynakes-meta)."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    if namespace is not None and namespace not in {"jabref", "pynakes"}:
        _emit_error(
            json_output,
            "InvalidNamespace",
            f"Invalid namespace {namespace!r}; expected jabref or pynakes",
        )
    coll = Bibliography.open(file)
    try:
        update = coll.set_metadata(key, value, namespace=namespace, allow_unknown=allow_unknown)
    except metadata_ops.DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=[
                {
                    "id": "manual_edit",
                    "description": "Resolve duplicate metadata blocks manually, then retry",
                }
            ],
        )

    summary = [f"{_verb('set', params, 'Set')} {update.namespace}-meta {update.key!r}."]
    if update.mirrored is not None:
        summary.append(f"Mirrored into jabref-meta {update.mirrored.key!r} to keep JabRef in sync.")

    _finish_mod(
        file,
        "metadata_set",
        coll,
        params,
        summary,
        modified_entries=0,
        key=update.key,
        value=update.value.rstrip(";").strip(),
        created=update.created,
        namespace=update.namespace,
        mirrored=(
            {"key": update.mirrored.key, "namespace": update.mirrored.namespace}
            if update.mirrored is not None
            else None
        ),
    )


def metadata_adopt_jabref(
    file: str | None = bib_file_argument(),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Start maintaining a JabRef metadata projection for this library.

    pynakes-native libraries keep their settings in ``pynakes-meta``. This writes
    the equivalent ``jabref-meta`` blocks (relocating any JabRef-native keys and
    anchoring a ``databaseType``) so that, from now on, pynakes also keeps
    ``jabref-meta`` in sync — the file works in JabRef without losing its pynakes
    settings. Running it again once tracked is a no-op.
    """
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    coll = Bibliography.open(file)
    report = coll.adopt_jabref()

    if not report.changed:
        summary = "Already JabRef-tracked; nothing to adopt."
    else:
        parts = []
        if report.moved_keys:
            parts.append(f"relocated {len(report.moved_keys)} key(s) to jabref-meta")
        if report.database_type_added:
            parts.append("anchored databaseType")
        summary = f"{_verb('adopt', params, 'Adopted')} JabRef metadata: {', '.join(parts)}."

    _finish_mod(
        file,
        "metadata_adopt_jabref",
        coll,
        params,
        [summary],
        modified_entries=0,
        moved_keys=report.moved_keys,
        database_type_added=report.database_type_added,
        was_tracked=report.was_tracked,
    )


def metadata_remove(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Metadata key to remove"),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Target comment: jabref or pynakes. Default: auto-detect namespace from the key",
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove one metadata block (jabref-meta or pynakes-meta).

    Reports which namespace the key was removed from. When the key exists in
    both namespaces, the operation is refused as ambiguous (use --namespace).
    """
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    if namespace is not None and namespace not in {"jabref", "pynakes"}:
        _emit_error(
            json_output,
            "InvalidNamespace",
            f"Invalid namespace {namespace!r}; expected jabref or pynakes",
        )
    coll = Bibliography.open(file)
    try:
        update = coll.remove_metadata(key, namespace=namespace)
    except metadata_ops.DuplicateMetadataError as exc:
        _emit_conflict(
            json_output,
            "DuplicateMetadata",
            str(exc),
            key=exc.key,
            count=exc.count,
            options=[
                {
                    "id": "specify_namespace",
                    "description": "Pass --namespace jabref or --namespace pynakes to disambiguate",
                }
            ],
        )

    if update is None:
        ns_detail = f" in {namespace}-meta" if namespace else ""
        _emit_error(
            json_output,
            "KeyNotFound",
            f"Metadata key {key!r} not found{ns_detail}",
        )

    removed_from = f"{update.namespace}-meta"
    summary = [f"{_verb('remove', params, 'Removed')} {key!r} from {removed_from}."]

    _finish_mod(
        file,
        "metadata_remove",
        coll,
        params,
        summary,
        modified_entries=0,
        key=update.key,
        namespace=update.namespace,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(metadata_list))
    app.command("set")(_safe(metadata_set))
    app.command("remove")(_safe(metadata_remove))
    app.command("adopt-jabref")(_safe(metadata_adopt_jabref))
