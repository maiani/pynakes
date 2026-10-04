"""A lint finding and the severity and category axes that classify it.

Public through :mod:`pynakes.lint`, which re-exports every name here.
"""

from dataclasses import dataclass
from typing import Literal

LintSeverity = Literal["error", "warning", "info"]


LintCategory = Literal["correctness", "content", "layout", "consistency", "profile"]


SEVERITIES: tuple[LintSeverity, ...] = ("error", "warning", "info")


# Which command resolves a category, or ``None`` when a human must decide.
CATEGORY_FIXERS: dict[LintCategory, str | None] = {
    "correctness": None,
    "content": "normalize",
    "layout": "format",
    "consistency": None,
    "profile": None,
}


# Every finding belongs to exactly one category. ``correctness`` findings are
# structural problems no command can safely resolve; ``content`` and ``layout``
# findings name the command that fixes them; ``consistency`` findings are
# heuristic observations, not defects.
ISSUE_CATEGORIES: dict[str, LintCategory] = {
    "duplicate_field": "correctness",
    "duplicate_key": "correctness",
    "empty_key": "correctness",
    "missing_required_field": "correctness",
    "missing_reference_target": "correctness",
    "undefined_string_reference": "correctness",
    "no_entries": "correctness",
    "citation_key_pattern_mismatch": "content",
    "journal_style_mismatch": "content",
    "malformed_doi": "content",
    "malformed_groups": "content",
    "nonstandard_page_range": "content",
    "title_capitalization_unprotected": "content",
    "unknown_journal": "content",
    "unsupported_citation_key_pattern": "content",
    "noncanonical_entry_type_case": "layout",
    "noncanonical_field_name_case": "layout",
    "inconsistent_field": "consistency",
    "missing_doi": "consistency",
    "invalid_profile_setting": "profile",
    "missing_profile_required_field": "profile",
    "unknown_metadata_key": "correctness",
    "invalid_metadata_value": "correctness",
    "duplicate_metadata_block": "correctness",
    "missing_tex_source": "correctness",
}


def issue_category(issue_type: str) -> LintCategory:
    """Return the category of ``issue_type``.

    Unmapped types fall back to ``correctness`` so a new check is never silently
    treated as advisory; ``tests/test_lint.py`` asserts the mapping is complete.
    """
    return ISSUE_CATEGORIES.get(issue_type, "correctness")


@dataclass
class LintIssue:
    """A single validation finding."""

    type: str
    severity: LintSeverity
    message: str
    key: str | None = None
    field: str | None = None
    #: One-based source line of the finding's entry or metadata block, when the
    #: library was parsed from text and the check could locate it; ``None``
    #: otherwise (file-level findings, in-memory libraries).
    line: int | None = None

    @property
    def category(self) -> LintCategory:
        """Return which kind of problem this finding is."""
        return issue_category(self.type)

    @property
    def fixer(self) -> str | None:
        """Return the command that resolves this finding, if any."""
        return CATEGORY_FIXERS[self.category]

    def to_dict(self) -> dict[str, object]:
        """Serialize the finding to a JSON-friendly dict for CLI output."""
        return {
            "type": self.type,
            "severity": self.severity,
            "category": self.category,
            "fixer": self.fixer,
            "message": self.message,
            "key": self.key,
            "field": self.field,
            "line": self.line,
        }
