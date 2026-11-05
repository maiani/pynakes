"""Bibliography validation and lint finding types.

The public API remains ``pynakes.lint``. Load checks on first use so metadata
schemas and key operations can import the shared finding/directive definitions
without loading the full validation engine during package initialization.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pynakes.lint._checks import (
        CATEGORY_FIXERS,
        DIRECTIVE_ISSUE_TYPES,
        IGNORABLE_NAMES,
        ISSUE_CATEGORIES,
        PROFILE_ISSUE_TYPES,
        SEVERITIES,
        IgnoreRule,
        LintCategory,
        LintIssue,
        LintProfile,
        LintSeverity,
        entry_ignore_rules,
        is_profile_issue,
        is_waived,
        issue_category,
        library_lint_ignores,
        library_lint_severity,
        lint,
        profile_required_fields,
        resolve_lint_profile,
        suppress_findings,
        unknown_ignore_names,
        unknown_issue_types,
    )
    from pynakes.lint._checks import (
        _lint_entry as _lint_entry,
    )
    from pynakes.lint._checks import (
        _lint_profile_entry as _lint_profile_entry,
    )
    from pynakes.lint._checks import (
        required_field_rules as required_field_rules,
    )

__all__ = [
    "CATEGORY_FIXERS",
    "DIRECTIVE_ISSUE_TYPES",
    "IGNORABLE_NAMES",
    "ISSUE_CATEGORIES",
    "PROFILE_ISSUE_TYPES",
    "SEVERITIES",
    "IgnoreRule",
    "LintCategory",
    "LintIssue",
    "LintProfile",
    "LintSeverity",
    "entry_ignore_rules",
    "is_profile_issue",
    "is_waived",
    "issue_category",
    "library_lint_ignores",
    "lint",
    "profile_required_fields",
    "resolve_lint_profile",
    "suppress_findings",
    "library_lint_severity",
    "unknown_ignore_names",
    "unknown_issue_types",
]


def __getattr__(name: str) -> Any:
    if name not in __all__ and name not in [
        "_lint_entry",
        "_lint_profile_entry",
        "required_field_rules",
    ]:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("pynakes.lint._checks"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
