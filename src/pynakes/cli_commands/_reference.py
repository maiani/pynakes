"""Shared CLI helpers for individual-reference commands."""

import re

from pynakes.cli_common import _emit_conflict, _emit_error
from pynakes.engine import Bibliography
from pynakes.model import BibEntry

_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")


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
            options=[
                {
                    "id": "repair_duplicates",
                    "description": "Run keys repair, then retry with the resulting unique key",
                },
                {
                    "id": "inspect_all",
                    "description": "Inspect the library to review every duplicate instance",
                },
            ],
        )
    return matches[0]
