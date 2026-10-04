"""`asset check`: verify linked files and Pinax materials, optionally reconciling drift."""

import typer

from pynakes import files as files_ops
from pynakes.cli_common import CheckOutcome, _run_checks, _safe
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore

# --- files -----------------------------------------------------------------


def _files_check_one(
    file: str, root: list[str] | None, fix: bool = False, backup: bool = False
) -> CheckOutcome:
    lib = Bibliography.open(file).lib
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
        "action": "files_check",
        "file": file,
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
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if any linked file is missing or wrong-type"
    ),
    fix: bool = typer.Option(False, "--fix", help="Reconcile Pinax manifest drift"),
    backup: bool = typer.Option(
        False,
        "--backup",
        help="Also write manifest.json.bak before reconciling Pinax manifest drift",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate linked-file references (accepts multiple files for CI gating)."""
    _run_checks(
        files,
        "files_check",
        lambda f: _files_check_one(f, root, fix, backup),
        json_output,
        strict,
    )


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("check")(_safe(files_check))
