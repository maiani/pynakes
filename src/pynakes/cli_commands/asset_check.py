"""`asset check` verifies linked files and Pinax materials; `asset repair` reconciles drift."""

import typer

from pynakes import files as files_ops
from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_common import (
    _emit,
    _emit_error,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
    note_deprecation,
)
from pynakes.cli_surface import MOVED_OPTIONS
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore

# --- files -----------------------------------------------------------------


def _files_check_one(
    file: str, root: list[str] | None, fix: bool = False, backup: bool = False
) -> CheckOutcome:
    coll = Bibliography.open(file)
    lib = coll.lib
    report = files_ops.check_linked_files(lib, file, root)
    store = FileStore.from_metadata(lib, file)
    fixed: list[dict[str, str]] = []
    if store is not None and fix:
        fixed = store.fix_drift(
            (entry.key for entry in lib.entries.values() if entry.key.strip()),
            backup=backup,
        )
    pinax = store.scan_entries(lib.entries.values()) if store is not None else None
    result = {
        "status": "success",
        "action": "asset_check",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [],
        **report.to_dict(),
    }
    if pinax is not None:
        result["pinax"] = pinax.to_dict()
        result["fixed"] = fixed
    human = [
        f"{file}: checked {report.checked} linked file(s); "
        f"ok={report.ok}, missing={report.missing}, "
        f"wrong_type={report.wrong_type}, unresolved={report.unresolved}."
    ]
    human += [
        f"  [{issue.status}] {issue.entry_key}[{issue.index}]: {issue.path}"
        for issue in report.issues
    ]
    pinax_bad = 0
    if pinax is not None:
        pinax_bad = len(pinax.orphans) + len(pinax.drift)
        human.append(
            f"  pinax: entries={len(pinax.entries)}, "
            f"orphans={len(pinax.orphans)}, drift={len(pinax.drift)}."
        )
        if fixed:
            human.append(f"    fixed {len(fixed)} pinax manifest item(s).")
        human += [
            f"    [orphan] {orphan.key}:{orphan.kind}: {orphan.path}" for orphan in pinax.orphans
        ]
        human += [
            f"    [drift] {item['key']}:{item['kind']}: {item['reason']}" for item in pinax.drift
        ]
    bad = report.missing + report.wrong_type + report.unresolved + pinax_bad
    return CheckOutcome(
        result=result,
        human=human,
        failed=bad > 0,
        summary={
            "checked": report.checked,
            "ok": report.ok,
            "missing": report.missing,
            "wrong_type": report.wrong_type,
            "unresolved": report.unresolved,
            "pinax_orphans": len(pinax.orphans) if pinax is not None else 0,
            "pinax_drift": len(pinax.drift) if pinax is not None else 0,
        },
    )


def files_check(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    root: list[str] | None = typer.Option(
        None,
        "--root",
        help="Additional directory to resolve relative linked-file paths; can be repeated",
    ),
    strict: bool = strict_option("a linked file is missing, unresolved, or the wrong type"),
    fix: bool = typer.Option(False, "--fix", hidden=True, help="Deprecated: use asset repair"),
    backup: bool = typer.Option(
        False, "--backup", hidden=True, help="Deprecated: use asset repair"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate linked-file references (accepts multiple files for CI gating)."""
    if fix:
        # A gate command no longer writes; `asset repair` previews and reconciles.
        note_deprecation(
            json_output, "asset check --fix", MOVED_OPTIONS[("asset", "check")]["--fix"]
        )
    _run_checks(
        files,
        "asset_check",
        lambda f: _files_check_one(f, root, fix, backup),
        json_output,
        strict,
    )


def asset_repair(
    file: str | None = bib_file_argument(),
    backup: bool = typer.Option(
        False, "--backup", help="Also write manifest.json.bak before reconciling"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report the repairs without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of the manifest"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Reconcile the Pinax manifest with the material files that exist.

    Drops manifest rows for keys the library no longer has and records for
    files that are gone, and records material files the manifest does not
    know (as manual additions). Only the manifest changes: no material file
    and no byte of the library. ``asset check`` reports the same drift.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    store = FileStore.from_metadata(coll.lib, file)
    if store is None:
        _emit_error(
            json_output,
            "InvalidInput",
            f"{file} has no Pinax (no pinax-files-dir); run `pynakes init --pinax` first",
            action="asset_repair",
        )
    manifest, fixed = store.reconcile_manifest(
        entry.key for entry in coll.lib.entries.values() if entry.key.strip()
    )
    path = store.manifest_path
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    after = store.manifest_text(manifest) if fixed else before
    if fixed and not dry_run:
        store.write_manifest(manifest, backup=backup)
    verb = "would repair" if dry_run else "repaired"
    human = [f"{file}: {verb} {len(fixed)} Pinax manifest item(s)."]
    human += [f"  [{item['action']}] {item['key']}:{item['kind']}" for item in fixed]
    result = {
        "status": "success",
        "action": "asset_repair",
        "file": file,
        "dry_run": dry_run,
        "modified": bool(fixed) and not dry_run,
        "modified_entries": 0,
        "warnings": [],
        "source_sha256": _source_sha256(coll),
        "fixed": fixed,
    }
    _emit(json_output, result, human, generate_diff(before, after, str(path)), diff)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(files_check))
    app.command("repair")(_safe(asset_repair))
