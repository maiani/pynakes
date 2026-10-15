"""The ``invisible_character`` lint check (see :mod:`pynakes._invisible`)."""

from pynakes._invisible import describe, find_invisible
from pynakes._lint_issue import LintIssue
from pynakes.model import BibEntry


def lint_invisible(entry: BibEntry) -> list[LintIssue]:
    """Report each field of *entry* holding invisible characters, naming each one."""
    issues: list[LintIssue] = []
    for name, value in entry.fields.items():
        found = find_invisible(value)
        if not found:
            continue
        listed = ", ".join(f"{describe(char)} at offset {offset}" for offset, char in found)
        issues.append(
            LintIssue(
                "invisible_character",
                "warning",
                f"{entry.key}: field {name!r} contains invisible character(s): {listed}",
                key=entry.key,
                field=name,
            )
        )
    return issues
