"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import typer

from pynakes.cli_checks import CheckOutcome, _run_checks, strict_option
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _CACHE_FILE_OPTION,
    _CONCURRENCY_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
    key_option,
    parse_key_selector,
    select_keys,
    where_option,
)
from pynakes.engine import Bibliography
from pynakes.integrity import library_published

# --- integrity / enrichment -------------------------------------------------


def _integrity_bar(description: str):
    """Return the stderr progress bar for an online pass, loading Rich only now."""
    from pynakes.cli_commands._rich_progress import RichIntegrityProgress

    return RichIntegrityProgress(description)


def _verify_one(
    file: str,
    online: bool,
    cache_file: str | None,
    published: bool | None,
    json_output: bool,
    concurrency: int,
    where: str | None = None,
    key: list[str] | None = None,
) -> CheckOutcome:
    coll = Bibliography.open(file)
    published = library_published(coll.lib, "verify", published)
    selection_warnings: list[dict] = []
    selected = select_keys(coll, where, key, json_output, "verify", warnings=selection_warnings)
    if online and not json_output:
        with _integrity_bar("Verifying") as progress:
            report = coll.verify(
                online=online,
                cache_file=cache_file,
                progress=progress,
                concurrency=concurrency,
                keys=selected,
            )
    else:
        report = coll.verify(
            online=online, cache_file=cache_file, concurrency=concurrency, keys=selected
        )
    result = {
        "status": "success",
        "action": "verify",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": selection_warnings,
        "selected": None if selected is None else len(selected),
        "online": online,
        "summary": {
            "checked": report.checked,
            "errors": report.errors,
            "warnings": report.warnings,
            "info": report.infos,
        },
        "issues": [issue.to_dict() for issue in report.issues],
    }
    if report.errors and report.checked == 0:
        result["note"] = "No DOIs could be verified — all lookups failed."
    human = [
        f"{file}: verified {report.checked} DOI-backed {_entries(report.checked)}.",
        f"  errors={report.errors}, warnings={report.warnings}, info={report.infos}",
    ]
    if report.errors and report.checked == 0:
        human.append("  No DOIs could be verified — all lookups failed.")
    human += [f"  [{issue.severity}] {issue.key}: {issue.message}" for issue in report.issues]
    if published:
        # Read-only preprint check, folded in from the former `published` command.
        # Informational only: it never affects the --strict gate.
        if online and not json_output:
            with _integrity_bar("Checking preprints") as progress:
                preprints = coll.published_check(
                    online=online,
                    cache_file=cache_file,
                    progress=progress,
                    concurrency=concurrency,
                    keys=selected,
                )
        else:
            preprints = coll.published_check(
                online=online, cache_file=cache_file, concurrency=concurrency, keys=selected
            )
        result["preprints"] = preprints.to_dict()
        result["warnings"].extend(preprints.warnings)
        human.append(
            f"  publication checks: {preprints.checked} candidate results; "
            f"{preprints.newly_found} newly found, {preprints.already_present} already recorded"
        )
        human += [f"  warning: {warning['message']}" for warning in preprints.warnings]
    return CheckOutcome(
        result=result,
        human=human,
        failed=bool(report.errors or report.warnings),
        summary={
            "checked": report.checked,
            "errors": report.errors,
            "warnings": report.warnings,
            "info": report.infos,
        },
    )


def verify(
    files: list[str] = typer.Argument(..., help="One or more .bib files"),
    online: bool = typer.Option(
        False, "--online", help="Fetch DOI provider metadata; otherwise only local checks run"
    ),
    published: bool | None = typer.Option(
        None,
        "--published/--no-published",
        help="Also report preprints that now have a published version available "
        "(default: the library's verify-published setting, else off) "
        "(read-only; informational, does not affect --strict)",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    cache_file: str | None = _CACHE_FILE_OPTION,
    concurrency: int = _CONCURRENCY_OPTION,
    strict: bool = strict_option("verification finds warnings or errors"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Verify entries against authoritative metadata (read-only).

    Checks DOI-backed entries against provider metadata; with `--published` it
    also reports preprints that now have a published version available.
    `--key` and `--where` verify only the selected entries of one library, so
    checking a handful of references never looks up the rest.
    """
    if (where is not None or key) and len(files) > 1:
        _emit_error(
            json_output, "InvalidInput", "--key and --where select the entries of one library"
        )
    _run_checks(
        files,
        "verify",
        lambda f: _verify_one(
            f, online, cache_file, published, json_output, concurrency, where, key
        ),
        json_output,
        strict,
    )


def enrich(
    file: str | None = bib_file_argument(),
    online: bool = typer.Option(
        False,
        "--online",
        help="Fetch DOI provider metadata; otherwise only local DOI URLs are used",
    ),
    published: bool | None = typer.Option(
        None,
        "--published/--no-published",
        help="Also promote preprints to their published version, writing the "
        "published DOI/journal when one is available (requires --online); default: "
        "the library's enrich-published setting, else off",
    ),
    only_field: list[str] | None = typer.Option(
        None,
        "--only-field",
        metavar="NAME",
        help="Apply only updates to these fields (repeatable or comma-separated; "
        "'type' for an entry-type change), e.g. --only-field eprint,archiveprefix "
        "after reviewing a --dry-run",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    cache_file: str | None = _CACHE_FILE_OPTION,
    concurrency: int = _CONCURRENCY_OPTION,
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Conservatively fill missing metadata (modifies the file).

    Fills missing DOI/date/identifier fields; with `--published` it also
    promotes preprints to their published version (writing the published
    DOI/journal), folding in the former `published --apply` operation.
    `--key` and `--where` limit it to the selected entries, so a lookup
    for a handful of references never reaches the rest of the library.
    `--only-field` applies a reviewed subset: preview with `--dry-run`, then
    apply only those fields with `--expect-sha256` set to the previewed
    `source_sha256`, so nothing changed in between.
    """
    if published is True and not online:
        # Offline, the preprint pass has nothing to check against and would
        # report "Enriched 0 entries" as if it had looked and found nothing.
        _emit_error(
            json_output,
            "OnlineLookupRequired",
            "enrich --published looks up published versions of preprints; "
            "pass --online to allow the requests.",
        )
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    # Before any provider is asked: a stale precondition should cost no lookup.
    _check_expected_sha256(file, coll, params)
    selection_warnings: list[dict] = []
    selected = select_keys(coll, where, key, json_output, "enrich", warnings=selection_warnings)
    from_setting = published is None
    published = library_published(coll.lib, "enrich", published)
    if published and not online:
        # The library asks for the preprint pass, but a setting never enables
        # the network: skip it and say so rather than refusing the run.
        published = False
        if from_setting:
            selection_warnings.append(
                {
                    "type": "published_skipped_offline",
                    "message": "enrich-published is set, but promoting preprints needs "
                    "--online; skipped",
                }
            )
    fields = (
        sorted({name.strip() for item in only_field for name in item.split(",") if name.strip()})
        if only_field
        else None
    )
    updates: list = []
    if published:
        # Promote before the online DOI fill. A preprint is still @misc, a type
        # with no journal field, so a fill that ran first dropped the published
        # journal while keeping its volume and pages. The offline step (a DOI
        # found in a URL field) still runs first, because the promotion reads a
        # preprint DOI only from the doi field. Its warnings repeat below.
        updates += coll.enrich(keys=selected, fields=fields).updates
        if not json_output:
            with _integrity_bar("Checking preprints") as progress:
                preprints = coll.apply_published(
                    online=online,
                    cache_file=cache_file,
                    progress=progress,
                    concurrency=concurrency,
                    keys=selected,
                    fields=fields,
                )
        else:
            preprints = coll.apply_published(
                online=online,
                cache_file=cache_file,
                concurrency=concurrency,
                keys=selected,
                fields=fields,
            )
        updates += preprints.updates
    if online and not json_output:
        with _integrity_bar("Enriching") as progress:
            report = coll.enrich(
                online=online,
                cache_file=cache_file,
                progress=progress,
                concurrency=concurrency,
                keys=selected,
                fields=fields,
            )
    else:
        report = coll.enrich(
            online=online,
            cache_file=cache_file,
            concurrency=concurrency,
            keys=selected,
            fields=fields,
        )
    updates += report.updates
    warnings = [*selection_warnings, *report.warnings]
    if selected == []:
        warnings.append(
            {"type": "no_entries_selected", "message": "No entry matched the selection"}
        )
    extra: dict[str, object] = {}
    detail: list[str] = []
    if published:
        warnings += preprints.warnings
        extra["preprints"] = {
            "checked": preprints.checked,
            "published": preprints.published,
            "newly_found": preprints.newly_found,
            "already_present": preprints.already_present,
            "by_status": preprints.by_status,
            "promoted": preprints.promoted,
            "linked": preprints.linked,
            "not_found": sum(1 for c in preprints.candidates if c.status == "not_found"),
            "updates": [update.to_dict() for update in preprints.updates],
        }
        # Two opposite directions of travel, counted apart. Reporting the
        # backfill as a promotion described the reverse of what it does.
        if preprints.promoted:
            detail.append(
                f"  promoted {preprints.promoted} "
                f"{_entries(preprints.promoted)} from preprint to published"
            )
        if preprints.linked:
            detail.append(
                f"  added arXiv preprint provenance to {preprints.linked} published "
                f"{_entries(preprints.linked)}"
            )
    lookups = _lookup_coverage(warnings, concurrency, cache_file)
    if lookups["not_checked"]:
        detail.append(
            f"  not checked: {len(lookups['not_checked'])} "
            f"{_entries(len(lookups['not_checked']))} ({lookups['retry']})"
        )
    # Counted over every update this command applied, preprint work included, so
    # the dry-run summary matches both the diff below it and the JSON envelope.
    changed_entries = len({update.key for update in updates})
    human = [
        f"{_verb('enrich', params, 'Enriched')} {changed_entries} {_entries(changed_entries)}.",
        f"  field_updates={len(updates)}",
        *detail,
    ]
    _finish_mod(
        file,
        "enrich",
        coll,
        params,
        human,
        warnings=warnings,
        changed_entries=len({update.key for update in updates}),
        changed_fields=len(updates),
        updates=[update.to_dict() for update in updates],
        where=where,
        keys=parse_key_selector(key),
        selected=None if selected is None else len(selected),
        lookups=lookups,
        only_fields=fields,
        **extra,
    )


def _lookup_coverage(
    warnings: list[dict], concurrency: int, cache_file: str | None
) -> dict[str, object]:
    """Name the entries whose provider lookups failed, so "not checked" is never read as "no match".

    ``retry`` is the command-line suffix that reruns just the retryable ones,
    at a lower concurrency when a provider throttled the run; ``None`` when
    there is nothing to retry.
    """
    failed = [w for w in warnings if w.get("checked") is False]
    not_checked = sorted({str(w["key"]) for w in failed})
    rate_limited = sorted({str(w["key"]) for w in failed if w.get("rate_limited")})
    retryable = sorted({str(w["key"]) for w in failed if w.get("retryable")})
    retry = None
    if retryable:
        lower = max(1, concurrency // 4) if rate_limited else concurrency
        retry = f"--key {','.join(retryable)} --concurrency {lower}"
        if cache_file:
            retry = f"{retry} --cache-file {cache_file}"
    return {
        "not_checked": not_checked,
        "rate_limited": rate_limited,
        "retryable": retryable,
        "retry": retry,
    }


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(verify))
    app.command()(_safe(enrich))
