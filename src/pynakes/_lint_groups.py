"""Diagnose group memberships using the same separator as group operations."""

from pynakes._lint_issue import LintIssue
from pynakes.groups import library_groups_separator
from pynakes.model import BibFile


def lint_groups(lib: BibFile) -> list[LintIssue]:
    """Report ambiguous separators or empty memberships without stopping lint."""
    try:
        delimiter = library_groups_separator(lib)
    except ValueError as exc:
        return [LintIssue("malformed_groups", "warning", str(exc), field="groups")]
    return [
        LintIssue(
            "malformed_groups",
            "warning",
            f"Entry {entry.key!r} has a malformed groups field: {value!r}",
            key=entry.key,
            field="groups",
        )
        for entry in lib.entries.values()
        if (value := entry.fields.get("groups"))
        and value.strip()
        and any(not part.strip() for part in value.split(delimiter))
    ]
