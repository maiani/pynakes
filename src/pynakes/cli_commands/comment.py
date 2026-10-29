"""CLI command registration for ``pynakes ref comment``."""

import typer

from pynakes._engine_directives import comment_problem
from pynakes.cli_commands._reference import unique_entry
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
    key_option,
    select_keys,
    where_option,
)
from pynakes.engine import Bibliography


def comment(
    file: str | None = bib_file_argument(),
    text: str = typer.Argument(..., metavar="TEXT", help="The comment, one line of free text"),
    key: list[str] | None = key_option(
        "The entries to comment: citation keys, comma-separated, repeatable"
    ),
    where: str | None = where_option("Comment every entry matching this selector"),
    remove: bool = typer.Option(
        False, "--remove", help="Remove the entries' attached comments reading TEXT"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add or remove an entry comment: a `% TEXT` line directly above each entry.

    `ref comment refs.bib "checked against the first edition" --key Newton1687`
    writes `% checked against the first edition` directly above the entry. The
    comment is attached: it moves with the entry when entries are sorted,
    combined, or split, and `scrub` removes it with the other comments. It is
    for people and changes nothing, so it suits remarks that do not belong in a
    `note` field, which a bibliography style prints. A comment the entry already
    carries is not repeated. `--remove` takes it out again.
    """
    if not key and where is None:
        _emit_error(
            json_output, "InvalidInput", "Name the entries with --key or select them with --where"
        )
    if not remove:
        problem = comment_problem(text)
        if problem is not None:
            _emit_error(json_output, "InvalidInput", f"Invalid comment: {problem}")
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    selection_warnings: list[dict] = []
    selected = (
        select_keys(coll, where, key, json_output, "ref_comment", warnings=selection_warnings) or []
    )
    for name in selected:
        unique_entry(coll, name, json_output, action="ref_comment")
    if remove:
        changed = [name for name in selected if coll.remove_entry_comment(name, text)]
    else:
        changed = [name for name in selected if coll.add_entry_comment(name, text)]
    shown = f"% {text.strip()}"
    if dry_run:
        verb_done = "Would remove" if remove else "Would add"
    else:
        verb_done = "Removed" if remove else "Added"
    human = [f"{verb_done} {shown!r} on {len(changed)} of {len(selected)} selected entries."]
    warnings: list[dict] = [*selection_warnings]
    if not selected:
        warnings.append({"type": "no_entries_selected", "message": "No entry matched --where"})
    elif remove and not changed:
        warnings.append(
            {"type": "comment_not_found", "message": f"No selected entry has {shown!r}"}
        )
    _finish_mod(
        file,
        "ref_comment",
        coll,
        params,
        human,
        warnings=warnings,
        modified_entries=len(changed),
        keys=changed,
        selected=len(selected),
        comment=text.strip(),
        removed=remove,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("comment")(_safe(comment))
