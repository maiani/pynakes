"""CLI commands for bibliography links: ``biblink add``, ``remove``, ``list`` and ``check``.

``add`` and ``remove`` edit both files of a link as one change: one preview
covering both, each file guarded by its own digest, and both written or
neither. ``list`` and ``check`` read the bibliography named and follow only the
links it declares.
"""

from pathlib import Path

import typer

from pynakes import biblinks as link_ops
from pynakes._engine_helpers import fingerprint
from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_choices import LinkConstraint, LinkFlow, SyncDirection
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    _EXTERNAL_MODIFICATION_OPTIONS,
    RunParams,
    _check_expected_sha256,
    _emit,
    _emit_conflict,
    _emit_error,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
)
from pynakes.engine import Bibliography, ExternalModificationError

_EXPECT_OTHER_SHA256_OPTION = typer.Option(
    None,
    "--expect-other-sha256",
    metavar="SHA256",
    help="Like --expect-sha256, for the other bibliography of the link: refuse, writing "
    "nothing, unless its sha256 still equals the other.source_sha256 a --dry-run reported",
)


def _params(dry_run: bool, diff: bool, json_output: bool, backup: bool) -> RunParams:
    return RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)


def _finish_pair(
    action: str,
    first: Bibliography,
    second: Bibliography,
    params: RunParams,
    human: list[str],
    **details: object,
) -> None:
    """Preview or commit both ends and emit the two-file modifying envelope.

    ``file`` and ``source_sha256`` describe the bibliography named first, as in
    every modifying envelope; ``other`` carries the same for the second file.
    """
    first_sha, second_sha = _source_sha256(first), _source_sha256(second)
    diff_text = "\n".join(part for part in (first.diff(), second.diff()) if part)
    if params.dry_run:
        changed = [first.is_modified, second.is_modified]
    else:
        try:
            changed = link_ops.commit_together([first, second], backup=params.backup)
        except ExternalModificationError as exc:
            _emit_conflict(
                params.json_output,
                "ExternalModification",
                str(exc),
                file=str(exc.path),
                options=_EXTERNAL_MODIFICATION_OPTIONS,
            )
    result = {
        "status": "success",
        "action": action,
        "file": str(first.path),
        "dry_run": params.dry_run,
        "modified": any(changed),
        "modified_entries": 0,
        "warnings": [],
        "source_sha256": first_sha,
        "other": {"file": str(second.path), "source_sha256": second_sha, "modified": changed[1]},
        **details,
    }
    _emit(params.json_output, result, human, diff_text, params.diff)


def _open_pair(
    file: str, other: str, params: RunParams, expect: str | None, expect_other: str | None
) -> tuple[Bibliography, Bibliography]:
    first, second = Bibliography.open(file), Bibliography.open(other)
    _check_expected_sha256(file, first, _with_expect(params, expect))
    _check_expected_sha256(other, second, _with_expect(params, expect_other))
    return first, second


def _with_expect(params: RunParams, expect: str | None) -> RunParams:
    return RunParams(
        dry_run=params.dry_run,
        diff=params.diff,
        json_output=params.json_output,
        backup=params.backup,
        expect_sha256=expect,
    )


def biblink_add(
    file: str | None = bib_file_argument(),
    parent: str = typer.Argument(..., help="The parent bibliography this one draws from"),
    constraint: LinkConstraint = typer.Option(
        LinkConstraint.FIELD_SUBSET,
        "--constraint",
        help="What must hold: key-subset (every child key is in the parent) or field-subset "
        "(also the parent's type and values for every field the child has)",
    ),
    flow: LinkFlow = typer.Option(
        LinkFlow.DOWN,
        "--flow",
        help="Which way a sync may move values: down (parent to child), up, both, or none",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    expect_other_sha256: str | None = _EXPECT_OTHER_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of both files"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Declare FILE a child of PARENT, writing the link into both bibliographies.

    Each file records the other, relative to its own folder, with the same
    constraint and flow. Re-running it repairs a link only one end declares or
    changes its constraint or flow. Nothing is copied: `biblink check` validates
    the link, and values move only when a sync is run.
    """
    file = _resolve_input_bib(file, json_output)
    params = _params(dry_run, diff, json_output, backup)
    child, parent_coll = _open_pair(file, parent, params, expect_sha256, expect_other_sha256)
    constraint_name, flow_name = str(constraint.value), str(flow.value)
    child_side, parent_side = link_ops.stage_link(child, parent_coll, constraint_name, flow_name)
    human = [
        f"{_verb('link', params)} {file} as a child of {parent} "
        f"(constraint={constraint_name}, flow={flow_name}).",
    ]
    _finish_pair(
        "biblink_add",
        child,
        parent_coll,
        params,
        human,
        link={"child": child_side.to_dict(), "parent": parent_side.to_dict()},
    )


def biblink_remove(
    file: str | None = bib_file_argument(),
    other: str = typer.Argument(..., help="The linked bibliography, parent or child"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    expect_other_sha256: str | None = _EXPECT_OTHER_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of both files"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove the link between FILE and OTHER from both bibliographies.

    Removes whatever either end declares about the other, so a half-declared
    link is cleared too. Entries are untouched.
    """
    file = _resolve_input_bib(file, json_output)
    params = _params(dry_run, diff, json_output, backup)
    first, second = _open_pair(file, other, params, expect_sha256, expect_other_sha256)
    try:
        removed = link_ops.stage_unlink(first, second)
    except LookupError as exc:
        _emit_error(json_output, "KeyNotFound", str(exc))
    human = [f"{_verb('unlink', params)} {file} and {other}."]
    _finish_pair(
        "biblink_remove",
        first,
        second,
        params,
        human,
        removed=[declaration.to_dict() for declaration in removed],
    )


def biblink_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List the parents and children this bibliography declares."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    declarations = link_ops.declared_links(coll.lib)
    rows = [
        {
            **declaration.to_dict(),
            "resolved": str(declaration.resolve(file)),
            "exists": declaration.resolve(file).is_file(),
        }
        for declaration in declarations
    ]
    human = [f"{file}: no linked bibliographies."] if not rows else []
    for row in rows:
        missing = "" if row["exists"] else "  (missing)"
        human.append(
            f"{row['role']}: {row['path']}  constraint={row['constraint']} "
            f"flow={row['flow']}{missing}"
        )
    result = {
        "status": "success",
        "action": "biblink_list",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": [],
        "links": rows,
    }
    _emit(json_output, result, human)


def _check_one(file: str) -> CheckOutcome:
    reports = link_ops.check_links(file)
    failing = [report for report in reports if not report.ok]
    human = [f"{file}: no linked bibliographies."] if not reports else []
    for report in reports:
        state = "ok" if report.ok else ("incomplete" if not report.complete else "drift")
        human.append(
            f"{report.declaration.role} {report.declaration.path} "
            f"({report.declaration.constraint}): {state}, "
            f"{report.checked_entries} entr{'y' if report.checked_entries == 1 else 'ies'} "
            f"checked, {len(report.findings)} finding(s)"
        )
        human.extend(f"  - {finding.message}" for finding in report.findings)
    result = {
        "status": "success",
        "action": "biblink_check",
        "file": file,
        "source_sha256": fingerprint(Path(file)).sha256,
        "warnings": [],
        "ok": not failing,
        "links": [report.to_dict() for report in reports],
    }
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(failing),
        summary={
            "links": len(reports),
            "failing_links": len(failing),
            "findings": sum(len(report.findings) for report in reports),
        },
    )


def biblink_check(
    file: str | None = bib_file_argument(),
    strict: bool = strict_option("a link does not hold or could not be fully checked"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate every link this bibliography declares (read-only).

    For each parent or child: whether the other end declares the link back
    with the same constraint and flow, child keys missing from the parent,
    keys too ambiguous to compare, and, under field-subset, type and field
    drift. A link whose other file cannot be read is reported incomplete, never
    as agreeing. Only the links FILE declares are followed, one step.
    """
    file = _resolve_input_bib(file, json_output)
    _run_checks([file], "biblink_check", _check_one, json_output, strict)


def _expected_digests(values: list[str] | None, json_output: bool) -> dict[Path, str]:
    """Parse ``--expect-linked-sha256 PATH=SHA256`` values, keyed by resolved path."""
    expected: dict[Path, str] = {}
    for value in values or []:
        path, sep, digest = value.rpartition("=")
        if not sep or not path:
            _emit_error(
                json_output, "InvalidInput", f"--expect-linked-sha256 needs PATH=SHA256: {value!r}"
            )
        expected[Path(path).resolve()] = digest
    return expected


def biblink_sync(
    file: str | None = bib_file_argument(),
    parents: bool = typer.Option(False, "--parents", help="Sync along FILE's parent links only"),
    children: bool = typer.Option(False, "--children", help="Sync along FILE's child links only"),
    direction: SyncDirection = typer.Option(
        SyncDirection.DOWN,
        "--direction",
        help="down copies parents' values into children; up copies children's values "
        "into parents. A link is followed only when its flow allows the direction",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    expect_linked_sha256: list[str] | None = typer.Option(
        None,
        "--expect-linked-sha256",
        metavar="PATH=SHA256",
        help="Like --expect-sha256, for another file the sync writes; repeatable, one per "
        "file, with the source_sha256 a --dry-run reported for it under files",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of every file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Copy values along FILE's links, one step and one direction, to repair drift.

    For each selected link (all of FILE's links unless `--parents` or
    `--children` narrows them) whose flow allows the direction, the drifted
    fields `biblink check` reports take the other end's value: the parent's
    going down, the child's going up, including the entry type. Entries are
    never added, removed or renamed; going down never deletes a field only the
    child has, and going up leaves fields the parent inherits through crossref
    or xdata. Two links proposing different values for one field are a conflict,
    and that field is left alone. Every file written is previewed together and
    written all or none.
    """
    file = _resolve_input_bib(file, json_output)
    params = _params(dry_run, diff, json_output, backup)
    both = not parents and not children
    plan, origin, targets = link_ops.sync_links(
        file, parents=parents or both, children=children or both, direction=str(direction.value)
    )
    _check_expected_sha256(file, origin, _with_expect(params, expect_sha256))
    expected = _expected_digests(expect_linked_sha256, json_output)
    for target in targets:
        if target is origin:
            continue
        digest = expected.get(Path(str(target.path)).resolve())
        _check_expected_sha256(str(target.path), target, _with_expect(params, digest))
    files = [origin, *(target for target in targets if target is not origin)]
    digests = [_source_sha256(coll) for coll in files]
    diff_text = "\n".join(part for part in (coll.diff() for coll in files) if part)
    if dry_run:
        changed = [coll.is_modified for coll in files]
    else:
        try:
            changed = link_ops.commit_together(files, backup=backup)
        except ExternalModificationError as exc:
            _emit_conflict(
                json_output,
                "ExternalModification",
                str(exc),
                file=str(exc.path),
                options=_EXTERNAL_MODIFICATION_OPTIONS,
            )
    by_file: dict[str, list[dict[str, object]]] = {}
    for change in plan.changes:
        by_file.setdefault(change.file, []).append(change.to_dict())
    entries = {(change.file, change.key) for change in plan.changes}
    human = [
        f"{_verb('sync', params)} {len(plan.changes)} value(s) {direction.value} along "
        f"{file}'s links ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'})."
    ]
    human.extend(
        f"  {change.file}: {change.key} {change.field or 'type'} = {change.new}"
        for change in plan.changes
    )
    human.extend(
        f"  conflict: {c['file']} {c['key']} {c['field'] or 'type'}" for c in plan.conflicts
    )
    if plan.skipped:
        human.append(f"  skipped: {len(plan.skipped)} (see --json for each reason)")
    result = {
        "status": "success",
        "action": "biblink_sync",
        "file": file,
        "dry_run": dry_run,
        "modified": any(changed),
        "modified_entries": len(entries),
        "warnings": [],
        "source_sha256": digests[0],
        "direction": direction.value,
        "files": [
            {
                "file": str(coll.path),
                "source_sha256": digest,
                "modified": was_changed,
                "changes": by_file.get(str(coll.path), []),
            }
            for coll, digest, was_changed in zip(files, digests, changed, strict=True)
        ],
        "conflicts": plan.conflicts,
        "skipped": [skip.to_dict() for skip in plan.skipped],
    }
    _emit(json_output, result, human, diff_text, diff)


def register(app: typer.Typer) -> None:
    """Register the ``biblink`` command family."""
    app.command("add")(_safe(biblink_add))
    app.command("remove")(_safe(biblink_remove))
    app.command("list")(_safe(biblink_list))
    app.command("check")(_safe(biblink_check))
    app.command("sync")(_safe(biblink_sync))
