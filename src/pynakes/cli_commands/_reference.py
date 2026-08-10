"""Shared CLI helpers for individual-reference commands."""

import re

import typer

from pynakes.cli_common import InvalidInputError, _emit_conflict, _emit_error
from pynakes.engine import Bibliography
from pynakes.lint import required_field_rules
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry

_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")

#: Offered whenever a requested citation key identifies more than one entry.
#: The commands that address entries by key refuse to guess which physical
#: entry was meant, so both options are ways for the caller to disambiguate.
_DUPLICATE_KEY_OPTIONS = [
    {
        "id": "repair_duplicates",
        "description": "Run keys repair, then retry with the resulting unique key",
    },
    {
        "id": "inspect_all",
        "description": "Inspect the library to review every duplicate instance",
    },
]

_FIELD_LABELS = {
    "booktitle": "Book title",
    "journaltitle": "Journal title",
}


def parse_field_assignments(assignments: list[str]) -> dict[str, str]:
    """Parse repeatable ``name=value`` options into validated field values."""
    fields: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Field assignment must use name=value syntax: {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        if not _FIELD_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid field name: {name!r}")
        if name.lower() in {"key", "type"}:
            raise ValueError(f"{name!r} is not a field; use the citation key or --type")
        fields[name] = value.strip()
    return fields


def prompt_entry_type(default: str) -> str:
    """Prompt for a non-empty reference type, using ``default`` on Enter."""
    while True:
        value = typer.prompt("Reference type", default=default).strip()
        if value:
            return value.lower()
        typer.echo("Reference type cannot be empty.")


def prompt_citation_key() -> str | None:
    """Prompt for a citation key, returning ``None`` to request generation."""
    value = typer.prompt(
        "Citation key (leave blank to generate)",
        default="",
        show_default=False,
    )
    return value.strip() or None


def prompt_required_fields(
    coll: Bibliography,
    entry_type: str,
    fields: dict[str, str],
    *,
    existing: BibEntry | None = None,
    clear_fields: list[str] | None = None,
) -> dict[str, str]:
    """Prompt only for unsupplied required fields for an entry type.

    New entries skip requirements already satisfied by explicit ``--field``
    values. Existing entries show their current values as defaults so Enter
    preserves them; unchanged defaults are not added to the edit operation.
    Alternative requirements (for example ``author`` or ``editor``) reuse the
    field already present, otherwise the first canonical alternative is used.
    """
    prompted = dict(fields)
    supplied = {name.lower() for name in fields}
    cleared = {name.lower() for name in clear_fields or []}
    existing_fields = {
        name.lower(): (name, value) for name, value in (existing.fields.items() if existing else [])
    }

    for alternatives in required_field_rules(entry_type, library_dialect(coll.lib)):
        if supplied.intersection(alternatives) or cleared.intersection(alternatives):
            continue

        current = next(
            (
                existing_fields[name]
                for name in alternatives
                if name in existing_fields and existing_fields[name][1].strip()
            ),
            None,
        )
        name, default = current if current is not None else (alternatives[0], None)
        label = _FIELD_LABELS.get(name.lower(), name.replace("_", " ").capitalize())

        while True:
            value = typer.prompt(label, default=default).strip()
            if value:
                break
            typer.echo(f"{label} cannot be empty.")

        if existing is None or current is None or value != default:
            prompted[name] = value

    return prompted


def unique_entry(coll: Bibliography, key: str, json_output: bool, *, action: str) -> BibEntry:
    """Return one uniquely keyed entry or emit the CLI error/conflict envelope."""
    matches = coll.entries.get_all(key)
    if not matches:
        _emit_error(json_output, "KeyNotFound", f"No reference with key {key!r}", action=action)
    if len(matches) > 1:
        _emit_conflict(
            json_output,
            "DuplicateCitationKey",
            f"Citation key {key!r} identifies {len(matches)} references",
            action=action,
            key=key,
            options=_DUPLICATE_KEY_OPTIONS,
        )
    return matches[0]


def parse_key_list(values: list[str]) -> list[str]:
    """Parse repeated and comma-separated ``--keys`` values into unique keys.

    ``--keys a,b --keys c`` and ``--keys a,b,c`` are the same request. Order is
    the order given, and a key repeated across the values appears once, so a
    caller pasting a candidate list from two searches gets one summary per
    reference rather than one per mention.
    """
    keys: list[str] = []
    for value in values:
        for key in value.split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    if not keys:
        raise InvalidInputError("--keys requires at least one citation key")
    return keys


def unique_entries(
    coll: Bibliography, keys: list[str], json_output: bool, *, action: str
) -> list[BibEntry]:
    """Return one entry per key, or emit the CLI error/conflict envelope.

    Reports *every* unresolvable key at once rather than failing on the first
    one, so a caller fixes one round of mistakes instead of rediscovering them
    key by key. Unknown keys are an exit-1 ``KeyNotFound`` error and duplicated
    keys an exit-2 ``DuplicateCitationKey`` conflict, matching what
    :func:`unique_entry` reports for a single key.
    """
    matches = {key: coll.entries.get_all(key) for key in keys}

    missing = [key for key, found in matches.items() if not found]
    if missing:
        listed = ", ".join(repr(key) for key in missing)
        _emit_error(
            json_output,
            "KeyNotFound",
            f"No reference with key {listed}"
            if len(missing) == 1
            else f"No references with keys {listed}",
            action=action,
            keys=missing,
        )

    duplicated = [key for key, found in matches.items() if len(found) > 1]
    if duplicated:
        listed = ", ".join(repr(key) for key in duplicated)
        if len(duplicated) == 1:
            message = f"Citation key {listed} identifies {len(matches[duplicated[0]])} references"
        else:
            message = f"Citation keys {listed} identify more than one reference each"
        _emit_conflict(
            json_output,
            "DuplicateCitationKey",
            message,
            action=action,
            keys=duplicated,
            options=_DUPLICATE_KEY_OPTIONS,
        )

    return [matches[key][0] for key in keys]
