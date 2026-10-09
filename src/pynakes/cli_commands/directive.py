"""CLI command registration for ``pynakes ref directive``."""

import typer

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
    build_where_filter,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.directives import EntryDirective, directive_problem, format_directive
from pynakes.engine import Bibliography


def directive(
    file: str | None = bib_file_argument(),
    words: list[str] = typer.Argument(
        ...,
        metavar="DIRECTIVE...",
        help="The directive: a verb and its arguments, e.g. ignore missing_doi",
    ),
    key: list[str] | None = key_option(
        "The entries to apply it to: citation keys, comma-separated, repeatable"
    ),
    where: str | None = where_option("Apply it to every entry matching this selector"),
    reason: str | None = typer.Option(
        None, "--reason", help="Why the directive is there; written after ' -- '"
    ),
    remove: bool = typer.Option(
        False,
        "--remove",
        help="Remove these arguments from the entries' directives of this verb "
        "(all of them when only the verb is given)",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add or remove a per-entry directive: a ``% pynakes:`` line above each entry.

    ``ref directive refs.bib ignore missing_doi --key Newton1687 --reason "no DOI"``
    writes ``% pynakes: ignore missing_doi -- no DOI`` directly above the entry,
    and ``lint`` then leaves that finding out. ``--where`` applies it to a whole
    selection at once, e.g. every pre-DOI article. Arguments an entry already
    carries are not repeated. ``--remove`` takes them out again; a directive left
    with no arguments is removed whole.
    """
    verb = words[0].lower()
    args = tuple(part for word in words[1:] for part in word.replace(",", " ").split())
    if not key and where is None:
        _emit_error(
            json_output, "InvalidInput", "Name the entries with --key or select them with --where"
        )
    if remove and reason is not None:
        _emit_error(json_output, "InvalidInput", "--reason cannot be combined with --remove")
    if not remove:
        problem = directive_problem(EntryDirective(verb, args))
        if problem is not None:
            _emit_error(json_output, "InvalidInput", f"Invalid directive: {problem}")
    selector = build_where_filter(where, keys=key)
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    missing = [name for name in parse_key_selector(key) if name not in coll.lib.entries]
    if missing:
        _emit_error(
            json_output,
            "KeyNotFound",
            f"No reference with key {', '.join(map(repr, missing))}",
            action="ref_directive",
        )
    selected = list(
        dict.fromkeys(
            entry.key
            for entry in coll.lib.entries.values()
            if selector is not None and selector(entry)
        )
    )
    for name in selected:
        unique_entry(coll, name, json_output, action="ref_directive")
    if remove:
        changed = [name for name in selected if coll.remove_entry_directive(name, verb, args)]
    else:
        changed = [name for name in selected if coll.add_entry_directive(name, verb, args, reason)]
    text = format_directive(verb, args, reason)
    verb_done = "Removed" if remove else "Added"
    human = [f"{verb_done} {text!r} on {len(changed)} of {len(selected)} selected entries."]
    warnings: list[dict[str, str]] = []
    if not selected:
        warnings.append({"type": "no_entries_selected", "message": "No entry matched --where"})
    elif remove and not changed:
        warnings.append(
            {"type": "directive_not_found", "message": f"No selected entry has {text!r}"}
        )
    _finish_mod(
        file,
        "ref_directive",
        coll,
        params,
        human,
        warnings=warnings,
        modified_entries=len(changed),
        keys=changed,
        selected=len(selected),
        directive={"verb": verb, "args": list(args), "reason": reason},
        removed=remove,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("directive")(_safe(directive))
