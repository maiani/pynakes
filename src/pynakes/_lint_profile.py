"""The stored metadata profile lint verifies, and the checks that verify it.

Public through :mod:`pynakes.lint`, which re-exports the non-underscore names.
"""

from dataclasses import dataclass

from pynakes._lint_issue import IGNORABLE_NAMES, LintIssue
from pynakes.fields import TITLE_FIELDS, title_capitalization_is_protected
from pynakes.journals import (
    DEFAULT_JOURNAL_SOURCE,
    JOURNAL_FIELDS,
    JournalSources,
    expected_journal_title,
)
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    generate_key_from_pattern,
)
from pynakes.metadata import (
    library_key_pattern,
    metadata_bool,
    metadata_list,
    metadata_value,
)
from pynakes.model import BibEntry, BibFile

# Profile findings remain warnings for interactive use, but ``lint --strict``
# treats them as a failed conformance gate. Metadata drift belongs here too: an
# unknown ``pynakes-meta`` key, a value the key's grammar rejects, or duplicate
# blocks for one key all mean the library's persisted settings are not what
# pynakes will apply.
PROFILE_ISSUE_TYPES = frozenset(
    {
        "citation_key_pattern_mismatch",
        "journal_style_mismatch",
        "missing_profile_required_field",
        "title_capitalization_unprotected",
        "unsupported_citation_key_pattern",
        "invalid_profile_setting",
        "unknown_journal",
        "unknown_metadata_key",
        "invalid_metadata_value",
        "duplicate_metadata_block",
    }
)


@dataclass(frozen=True)
class LintProfile:
    """The metadata settings that define lintable library conformance."""

    journal_style: str = "none"
    journal_source: str = DEFAULT_JOURNAL_SOURCE
    journal_table: str | None = None
    ltwa_table: str | None = None
    protect_titles: bool = False
    title_fields: tuple[str, ...] = TITLE_FIELDS
    protected_terms: tuple[str, ...] = ()


def resolve_lint_profile(lib: BibFile) -> LintProfile:
    """Resolve the same persisted normalization settings that lint can verify."""
    journal_style = (metadata_value(lib, "normalize-journal-style") or "none").lower()
    journal_source = (
        metadata_value(lib, "normalize-journal-source") or DEFAULT_JOURNAL_SOURCE
    ).lower()
    title_fields = (
        metadata_list(metadata_value(lib, "normalize-title-fields")) or LintProfile.title_fields
    )
    protected_terms = metadata_list(metadata_value(lib, "normalize-protected-terms"))
    protect_titles = metadata_bool(
        metadata_value(lib, "normalize-protect-titles"),
        bool(protected_terms),
    )
    return LintProfile(
        journal_style=journal_style,
        journal_source=journal_source,
        journal_table=metadata_value(lib, "normalize-journal-table"),
        ltwa_table=metadata_value(lib, "normalize-ltwa-table"),
        # Normalization protects titles by default, but lint enforces only a
        # stored title preference. This keeps unprofiled libraries advisory.
        protect_titles=protect_titles,
        title_fields=tuple(field.lower() for field in title_fields),
        protected_terms=protected_terms,
    )


def profile_required_fields(lib: BibFile, entry_type: str) -> tuple[str, ...]:
    """Return additional required fields configured by the lint profile.

    ``lint-required-fields`` applies to every entry and
    ``lint-required-fields-<entrytype>`` adds type-specific requirements.
    """
    global_fields = metadata_list(metadata_value(lib, "lint-required-fields"))
    type_fields = metadata_list(metadata_value(lib, f"lint-required-fields-{entry_type.lower()}"))
    return global_fields + type_fields


def library_lint_ignores(lib: BibFile) -> frozenset[str]:
    """Return the finding types and categories the library's ``lint-ignore`` names.

    Unknown names are dropped here; ``lint`` reports them as
    ``invalid_metadata_value``. ``lint`` itself returns every finding: the
    command applies the ignores, so callers that gate on a finding (``format``
    refusing a repeated field) never see it suppressed.
    """
    names = metadata_list(metadata_value(lib, "lint-ignore"))
    return frozenset(name for name in names if name in IGNORABLE_NAMES)


def is_profile_issue(issue: "LintIssue") -> bool:
    """Return whether a finding is a stored-profile conformance deviation."""
    return issue.type in PROFILE_ISSUE_TYPES


def _lint_key_pattern(
    entry: BibEntry,
    lib: BibFile,
    expected_key: str | None = None,
    *,
    exempt: bool = False,
) -> list[LintIssue]:
    """Check the entry's citation key against the configured key pattern.

    Uses the native-first :func:`pynakes.metadata.library_key_pattern`, so a
    pynakes ``key-pattern`` takes precedence over a JabRef ``keypattern_*``.
    ``exempt`` entries (see :func:`pynakes.keys.is_key_regeneration_exempt`)
    are never checked: ``keys generate`` would not touch their key either, so
    flagging a "mismatch" here would just report the entry's real key as
    wrong against a pattern it was never going to receive.
    """
    if exempt:
        return []
    pattern = library_key_pattern(lib, entry.type)
    if not pattern:
        return []
    try:
        expected_key = expected_key or generate_key_from_pattern(entry, pattern)
    except UnsupportedCitationKeyPatternError as exc:
        return [
            LintIssue(
                "unsupported_citation_key_pattern",
                "warning",
                f"Entry {entry.key!r} cannot be checked against key pattern {pattern!r}: {exc}",
                key=entry.key,
            )
        ]
    if entry.key != expected_key:
        return [
            LintIssue(
                "citation_key_pattern_mismatch",
                "warning",
                f"Entry {entry.key!r} does not match configured citation-key pattern "
                f"{pattern!r}; expected {expected_key!r}",
                key=entry.key,
            )
        ]
    return []


def _lint_journal_style(
    entry: BibEntry,
    fields: dict[str, str],
    profile: LintProfile,
    journal_sources: JournalSources | None,
) -> list[LintIssue]:
    """Check entry journal fields against the configured journal style."""
    if profile.journal_style not in {"abbreviated", "full"} or journal_sources is None:
        return []
    issues: list[LintIssue] = []
    for field in JOURNAL_FIELDS:
        title = fields.get(field)
        if not title:
            continue
        expected_title = expected_journal_title(
            title, entry, profile.journal_style, journal_sources
        )
        if expected_title is None:
            issues.append(
                LintIssue(
                    "unknown_journal",
                    "warning",
                    f"Entry {entry.key!r} field {field!r} has no known "
                    f"{profile.journal_style!r} journal mapping for {title!r}",
                    key=entry.key,
                    field=field,
                )
            )
        elif expected_title != title:
            issues.append(
                LintIssue(
                    "journal_style_mismatch",
                    "warning",
                    f"Entry {entry.key!r} field {field!r} is not in configured "
                    f"{profile.journal_style!r} journal style; expected {expected_title!r}",
                    key=entry.key,
                    field=field,
                )
            )
    return issues


def _lint_consistency(
    entry: BibEntry, lib: BibFile, profile: LintProfile, fields: dict[str, str]
) -> list[LintIssue]:
    """Check profile-required fields and title-capitalisation protection."""
    issues: list[LintIssue] = []
    for field in profile_required_fields(lib, entry.type):
        normalized = field.lower()
        if not fields.get(normalized, "").strip():
            issues.append(
                LintIssue(
                    "missing_profile_required_field",
                    "warning",
                    f"{entry.type.lower()} entry {entry.key!r} is missing profile-required field "
                    f"{normalized!r}",
                    key=entry.key,
                    field=normalized,
                )
            )
    if profile.protect_titles:
        for field in profile.title_fields:
            title = fields.get(field)
            if title and not title_capitalization_is_protected(
                title, list(profile.protected_terms)
            ):
                issues.append(
                    LintIssue(
                        "title_capitalization_unprotected",
                        "warning",
                        f"Entry {entry.key!r} field {field!r} is not brace-protected as required "
                        "by normalize-protect-titles",
                        key=entry.key,
                        field=field,
                    )
                )
    return issues


def _lint_profile_entry(
    entry: BibEntry,
    lib: BibFile,
    profile: LintProfile,
    journal_sources: JournalSources | None,
    fields: dict[str, str] | None = None,
    expected_key: str | None = None,
    *,
    key_pattern_exempt: bool = False,
) -> list[LintIssue]:
    """Check one entry against persisted preferences without changing it."""
    if fields is None:
        fields = entry.fields
    return (
        _lint_key_pattern(entry, lib, expected_key, exempt=key_pattern_exempt)
        + _lint_consistency(entry, lib, profile, fields)
        + _lint_journal_style(entry, fields, profile, journal_sources)
    )
