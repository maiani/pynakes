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
)
from pynakes.directives import EntryDirective, directive_problem, format_directive
from pynakes.engine import Bibliography


def directive(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Citation key of the entry the directive applies to"),
    words: list[str] = typer.Argument(
        ...,
        metavar="DIRECTIVE...",
        help="The directive: a verb and its arguments, e.g. ignore missing_doi",
    ),
    reason: str | None = typer.Option(
        None, "--reason", help="Why the directive is there; written after ' -- '"
    ),
    remove: bool = typer.Option(
        False,
        "--remove",
        help="Remove these arguments from the entry's directives of this verb "
        "(all of them when only the verb is given)",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add or remove a per-entry directive: a ``% pynakes:`` line above the entry.

    ``ref directive refs.bib Newton1687 ignore missing_doi --reason "no DOI"``
    writes ``% pynakes: ignore missing_doi -- no DOI`` directly above the entry,
    and ``lint`` then leaves that finding out. Arguments already present are not
    repeated. ``--remove`` takes them out again; a directive left with no
    arguments is removed whole. See the per-entry directives guide for the verbs.
    """
    verb = words[0].lower()
    args = tuple(part for word in words[1:] for part in word.replace(",", " ").split())
    if remove and reason is not None:
        _emit_error(json_output, "InvalidInput", "--reason cannot be combined with --remove")
    if not remove:
        problem = directive_problem(EntryDirective(verb, args))
        if problem is not None:
            _emit_error(json_output, "InvalidInput", f"Invalid directive: {problem}")
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    unique_entry(coll, key, json_output, action="ref_directive")
    text = format_directive(verb, args, reason)
    warnings: list[dict[str, str]] = []
    if remove:
        changed = coll.remove_entry_directive(key, verb, args) > 0
        human = [f"Removed {text!r} from {key}." if changed else f"{key} has no {text!r}."]
        if not changed:
            warnings.append(
                {"type": "directive_not_found", "message": f"{key} has no {text!r} directive"}
            )
    else:
        changed = coll.add_entry_directive(key, verb, args, reason)
        human = [f"Added {text!r} to {key}." if changed else f"{key} already has {text!r}."]
    _finish_mod(
        file,
        "ref_directive",
        coll,
        params,
        human,
        warnings=warnings,
        modified_entries=int(changed),
        key=key,
        directive={"verb": verb, "args": list(args), "reason": reason},
        removed=remove,
    )


def register(app: typer.Typer) -> None:
    """Register this command on the reference Typer application."""
    app.command("directive")(_safe(directive))
