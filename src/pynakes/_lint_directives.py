"""Lint's side of per-entry directives (see :mod:`pynakes.directives`).

An ``ignore`` directive waives some of its entry's findings; a directive pynakes
cannot act on, or an ``ignore`` that waives nothing, is itself a finding, so a
typo or a stale waiver never goes unnoticed. Public through :mod:`pynakes.lint`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pynakes._lint_issue import NON_ENTRY_ISSUE_TYPES, LintIssue
from pynakes.directives import directive_problem, entry_directives
from pynakes.model import BibFile

#: Findings about directives themselves, which no directive can waive.
DIRECTIVE_ISSUE_TYPES = frozenset({"invalid_entry_directive", "unused_entry_directive"})


@dataclass(frozen=True)
class IgnoreRule:
    """One ``ignore`` argument: a finding type or category, optionally one field."""

    name: str
    field: str | None = None

    @classmethod
    def parse(cls, arg: str) -> IgnoreRule:
        """Parse ``NAME`` or ``NAME:FIELD`` (field names compare case-insensitively)."""
        name, _, field = arg.partition(":")
        return cls(name.strip(), field.strip().lower() or None)

    def matches(self, issue: LintIssue) -> bool:
        """Return whether this rule waives ``issue`` (its entry is checked by the caller)."""
        if self.name not in (issue.type, issue.category):
            return False
        return self.field is None or (issue.field or "").lower() == self.field


def entry_ignore_rules(lib: BibFile) -> dict[str, list[IgnoreRule]]:
    """Map each citation key to the rules of the valid ``ignore`` directives above it."""
    rules: dict[str, list[IgnoreRule]] = {}
    directives = entry_directives(lib)
    for entry in lib.entries.values():
        for directive in directives.get(id(entry), []):
            if directive.verb == "ignore" and directive_problem(directive) is None:
                rules.setdefault(entry.key, []).extend(
                    IgnoreRule.parse(arg) for arg in directive.args
                )
    return rules


def is_waived(issue: LintIssue, rules: dict[str, list[IgnoreRule]]) -> bool:
    """Return whether an ``ignore`` directive above ``issue``'s entry waives it."""
    if issue.key is None or issue.type in DIRECTIVE_ISSUE_TYPES | NON_ENTRY_ISSUE_TYPES:
        return False
    return any(rule.matches(issue) for rule in rules.get(issue.key, []))


def directive_findings(lib: BibFile, issues: list[LintIssue]) -> list[LintIssue]:
    """Report invalid directives, and ``ignore`` rules that match no finding in ``issues``."""
    findings: list[LintIssue] = []
    directives = entry_directives(lib)
    for entry in lib.entries.values():
        for directive in directives.get(id(entry), []):
            problem = directive_problem(directive)
            if problem is not None:
                findings.append(
                    LintIssue(
                        "invalid_entry_directive",
                        "warning",
                        f"Entry {entry.key!r} has an invalid directive "
                        f"{directive.text()!r}: {problem}",
                        key=entry.key,
                    )
                )
                continue
            if directive.verb != "ignore":
                continue
            own = [issue for issue in issues if issue.key == entry.key]
            for arg in directive.args:
                rule = IgnoreRule.parse(arg)
                if not any(rule.matches(issue) for issue in own):
                    findings.append(
                        LintIssue(
                            "unused_entry_directive",
                            "warning",
                            f"Entry {entry.key!r} ignores {arg!r}, but lint reports no "
                            "such finding for it; remove the directive",
                            key=entry.key,
                        )
                    )
    return findings
