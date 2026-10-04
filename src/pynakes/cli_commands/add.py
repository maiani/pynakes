"""CLI command registration for ``pynakes ref add``."""

import typer

from pynakes import keys as keys_ops
from pynakes.cli_commands._reference import (
    parse_field_assignments,
    prompt_citation_key,
    prompt_entry_type,
    prompt_required_fields,
)
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
    bib_file_argument,
    stdin_is_interactive,
)
from pynakes.engine import Bibliography
from pynakes.lint import required_field_rules
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry


def _missing_required_fields(
    coll: Bibliography, entry_type: str, fields: dict[str, str]
) -> list[str]:
    """Return unsatisfied required-field rules for ``entry_type``.

    Each item is one rule, joined with ``/`` when the requirement has
    interchangeable alternatives (e.g. ``author/editor``). Shares the rule set
    with lint validation and interactive prompting.
    """
    present = {name.lower() for name, value in fields.items() if value.strip()}
    missing: list[str] = []
    for alternatives in required_field_rules(entry_type, library_dialect(coll.lib)):
        if not present.intersection(alternatives):
            missing.append("/".join(alternatives))
    return missing


def add(
    key: str | None = typer.Argument(
        None, help="Citation key for the new entry; omit to start interactive mode"
    ),
    file: str | None = bib_file_argument(),
    file_option: str | None = typer.Option(
        None, "--file", help="Library path when the citation-key argument is omitted"
    ),
    entry_type: str | None = typer.Option(None, "--type", help="BibTeX/BibLaTeX entry type"),
    field: list[str] = typer.Option(
        [], "--field", "-f", help="Field assignment, repeatable: name=value"
    ),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Append even if the citation key already exists"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a manually specified reference entry.

    Omitting the citation key starts an interactive prompt for the key, type,
    and required fields. That path needs an interactive terminal: with ``--json``
    or headless stdin it errors instead, so supply the key (and ``--field``) to
    add non-interactively.
    """
    interactive = key is None
    if interactive:
        if json_output:
            _emit_error(
                json_output,
                "InvalidInput",
                "No citation key given; pass a key (and --field name=value) — "
                "prompting is unavailable with --json",
            )
        if not stdin_is_interactive():
            _emit_error(
                json_output,
                "InvalidInput",
                "No citation key given and stdin is not an interactive terminal; "
                "pass a key (and --field name=value) to add non-interactively",
            )
    if file is not None and file_option is not None:
        _emit_error(
            json_output,
            "InvalidInput",
            "Specify the library once, not both positionally and with --file",
        )
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    file = _resolve_input_bib(file_option or file, json_output)
    try:
        fields = parse_field_assignments(field)
        coll = Bibliography.open(file)
        if interactive:
            key = prompt_citation_key()
        if key is not None and coll.entries.get_all(key) and not allow_duplicate:
            # A taken key is a decision for the caller, not a malformed request:
            # both continuing and choosing another key are legitimate. ``ref
            # import`` already reports it that way, and a client cannot branch
            # on the situation if its two siblings disagree about the shape.
            _emit_conflict(
                json_output,
                "CitationKeyConflict",
                f"Citation key already exists: {key}",
                key=key,
                options=[
                    {"id": "choose_key", "description": "Retry with a different citation key"},
                    {
                        "id": "allow_duplicate",
                        "description": "Retry with --allow-duplicate to add a second entry "
                        "under this key",
                    },
                ],
            )
            return
        if interactive:
            entry_type = entry_type or prompt_entry_type("article")
            fields = prompt_required_fields(coll, entry_type, fields)
        entry_type = entry_type or "article"
        if key is None:
            candidate = keys_ops.generate_key(
                BibEntry(key="", type=entry_type, fields=fields),
                coll.lib,
            )
            key = keys_ops.unique_key(candidate, set(coll.entries.keys()))
            typer.echo(f"Generated citation key: {key}")
        entry = coll.add_entry(
            entry_type,
            key,
            fields,
            allow_duplicate=allow_duplicate,
        )
    except ValueError as exc:
        _emit_error(json_output, "InvalidInput", str(exc))
        return

    human = [f"{_verb('add', params)} {entry.type} {entry.key}."]
    warnings: list[str] = []
    missing = _missing_required_fields(coll, entry.type, entry.fields)
    if missing:
        message = (
            f"Entry {entry.key} is missing required field(s) for {entry.type}: "
            f"{', '.join(missing)}."
        )
        warnings.append(message)
        human.append(f"Warning: {message}")
    _finish_mod(
        file,
        "add",
        coll,
        params,
        human,
        warnings=warnings,
        key=entry.key,
        entry_type=entry.type,
        fields=dict(entry.fields),
    )


def register(app: typer.Typer) -> None:
    """Register this command on the application."""
    app.command("add")(_safe(add))
