"""Validation checks for a BibTeX library.

Reports issues as a flat list of :class:`LintIssue` objects, each tagged with a
severity (``error`` or ``warning``), the offending entry key, and a message.
Checks: duplicate keys, missing required fields (by entry type), undefined
BibTeX string references, cross-entry field consistency (a field most entries
of a type define but some omit), malformed or missing DOIs, malformed JabRef
``groups`` formatting, noncanonical entry-type / field-name casing, unresolved
journal titles, and deviations from the library's stored metadata profile.
"""

import csv
from dataclasses import dataclass
from typing import Optional

from pynakes.bibtex_parser import parse_raw_string_definition
from pynakes.editing import raw_field_names, raw_field_value
from pynakes.fields import title_capitalization_is_protected
from pynakes.importer import normalize_doi
from pynakes.journals import JOURNAL_FIELDS, JournalSources, expected_journal_title, load_sources
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    generate_key_from_pattern,
    get_jabref_key_pattern,
)
from pynakes.model import BibEntry, BibFile, undefined_string_references

# Required fields by entry type. Each requirement is a tuple of acceptable
# field names (any one satisfies it), to tolerate BibTeX/BibLaTeX variants
# (e.g. journal/journaltitle, year/date).
_REQUIRED: dict[str, list[tuple[str, ...]]] = {
    "article": [("author",), ("title",), ("journal", "journaltitle"), ("year", "date")],
    "book": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "inbook": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "conference": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "phdthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "mastersthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "thesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
}

# Entry types for which a missing DOI is worth a (low-severity) warning.
_DOI_EXPECTED = {"article", "inproceedings"}

# Fields excluded from the cross-entry consistency check: structural/reference
# fields (not bibliographic data) and JabRef-internal management fields that
# legitimately vary from entry to entry (group membership, file links, dates).
_CONSISTENCY_SKIP_FIELDS = frozenset(
    {
        "crossref",
        "xref",
        "xdata",
        "entryset",
        "entrysubtype",
        "ids",
        "related",
        "relatedtype",
        "relatedstring",
        "relatedoptions",
        "sortkey",
        "options",
        "presort",
        "groups",
        "file",
        "owner",
        "timestamp",
        "creationdate",
        "modificationdate",
        "comment",
        "priority",
        "ranking",
        "readstatus",
        "relevance",
        "printed",
        "qualityassured",
        "__markedentry",
        "marked",
    }
)

# Profile findings remain warnings for interactive use, but ``lint --strict``
# treats them as a failed conformance gate. Ordinary advisory lint warnings
# (such as a missing DOI) remain advisory even in strict mode.
PROFILE_ISSUE_TYPES = frozenset(
    {
        "citation_key_pattern_mismatch",
        "journal_style_mismatch",
        "missing_profile_required_field",
        "title_capitalization_unprotected",
        "unsupported_citation_key_pattern",
        "invalid_profile_setting",
        "unknown_journal",
    }
)


@dataclass(frozen=True)
class LintProfile:
    """The metadata settings that define lintable library conformance."""

    journal_style: str = "none"
    journal_table: str | None = None
    ltwa_table: str | None = None
    protect_titles: bool = False
    title_fields: tuple[str, ...] = ("title", "booktitle", "maintitle", "subtitle")
    protected_terms: tuple[str, ...] = ()


def _metadata_value(lib: BibFile, name: str) -> str | None:
    """Return the effective metadata value for ``name``, without ``;``."""
    metadata = {key.lower(): value for key, value in lib.metadata.items()}
    value = metadata.get(name.lower())
    if value is not None:
        return value.rstrip(";").strip()
    return None


def _metadata_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.replace(";", ",").split(",") if part.strip())


def _metadata_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes", "on", "enabled"}:
        return True
    if value.lower() in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def resolve_lint_profile(lib: BibFile) -> LintProfile:
    """Resolve the same persisted normalization settings that lint can verify."""
    journal_style = (_metadata_value(lib, "normalize-journal-style") or "none").lower()
    title_fields = (
        _metadata_list(_metadata_value(lib, "normalize-title-fields")) or LintProfile.title_fields
    )
    protected_terms = _metadata_list(_metadata_value(lib, "protected-terms"))
    protect_titles = _metadata_bool(
        _metadata_value(lib, "normalize-protect-titles"),
        bool(protected_terms),
    )
    return LintProfile(
        journal_style=journal_style,
        journal_table=_metadata_value(lib, "journal-table"),
        ltwa_table=_metadata_value(lib, "ltwa-table"),
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
    global_fields = _metadata_list(_metadata_value(lib, "lint-required-fields"))
    type_fields = _metadata_list(_metadata_value(lib, f"lint-required-fields-{entry_type.lower()}"))
    return global_fields + type_fields


def is_profile_issue(issue: "LintIssue") -> bool:
    """Return whether a finding is a stored-profile conformance deviation."""
    return issue.type in PROFILE_ISSUE_TYPES


@dataclass
class LintIssue:
    """A single validation finding."""

    type: str
    severity: str  # "error" | "warning"
    message: str
    key: Optional[str] = None
    field: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize the finding to a JSON-friendly dict for CLI output."""
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "key": self.key,
            "field": self.field,
        }


def lint(lib: BibFile) -> list[LintIssue]:
    """Run all validation checks and return the issues found."""
    issues: list[LintIssue] = []
    profile = resolve_lint_profile(lib)
    journal_sources = None

    if profile.journal_style not in {"none", "abbreviated", "full"}:
        issues.append(
            LintIssue(
                "invalid_profile_setting",
                "warning",
                "Profile normalize-journal-style must be one of 'none', 'abbreviated', or 'full'; "
                f"got {profile.journal_style!r}",
            )
        )
    elif profile.journal_style != "none":
        try:
            journal_sources = load_sources(profile.journal_table, profile.ltwa_table)
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            issues.append(
                LintIssue(
                    "invalid_profile_setting",
                    "warning",
                    f"Could not load journal sources from the metadata profile: {exc}",
                )
            )

    if len(lib.entries) == 0:
        # An empty parse usually means the wrong file or non-BibTeX content was
        # passed; a clean "0 issues" bill of health would be misleading.
        issues.append(
            LintIssue(
                "no_entries",
                "warning",
                "No BibTeX entries were found (is this the right file?)",
            )
        )

    for key, count in lib.entries.duplicate_keys().items():
        if not key.strip():
            # Empty keys are reported per-entry below, not as a duplicate set.
            continue
        issues.append(
            LintIssue(
                "duplicate_key",
                "error",
                f"Citation key {key!r} appears {count} times",
                key=key,
            )
        )

    issues.extend(_lint_undefined_string_definitions(lib))

    for entry in lib.entries.values():
        fields = lib.resolved_fields(entry)
        issues.extend(_lint_undefined_string_references(entry, lib))
        issues.extend(_lint_entry(entry, fields))
        issues.extend(_lint_profile_entry(entry, lib, profile, journal_sources, fields))

    issues.extend(_lint_field_consistency(lib))

    return issues


def _lint_field_consistency(lib: BibFile) -> list[LintIssue]:
    """Report fields a majority of same-type entries define but some omit.

    This is the analogue of JabRef's consistency check, scoped to be useful as
    an always-on linter: a field is flagged for an entry only when a strict
    majority of the entries of that entry type carry it (after inheritance) and
    this entry does not. Required fields (reported separately) and JabRef
    structural/management fields are excluded. Findings are advisory warnings;
    they do not fail ``lint --strict``. A field common to *all* same-type
    entries, or unique to a few, is not an inconsistency.
    """
    by_type: dict[str, list[BibEntry]] = {}
    for entry in lib.entries.values():
        if entry.key.strip():
            by_type.setdefault(entry.type.lower(), []).append(entry)

    issues: list[LintIssue] = []
    for etype, entries in by_type.items():
        total = len(entries)
        if total < 3:
            # A majority among one or two entries is uninformative.
            continue
        required = {name for alternatives in _REQUIRED.get(etype, []) for name in alternatives}
        resolved = [lib.resolved_fields(entry) for entry in entries]

        present_counts: dict[str, int] = {}
        for fields in resolved:
            for name, value in fields.items():
                if value and value.strip():
                    present_counts[name] = present_counts.get(name, 0) + 1

        majority = {
            name
            for name, count in present_counts.items()
            if count < total  # not common to all -> a real divergence
            and count * 2 > total  # held by a strict majority
            and name not in required
            and name not in _CONSISTENCY_SKIP_FIELDS
        }

        for entry, fields in zip(entries, resolved):
            for name in sorted(majority):
                if not fields.get(name, "").strip():
                    issues.append(
                        LintIssue(
                            "inconsistent_field",
                            "warning",
                            f"{etype} entry {entry.key!r} is missing field {name!r}, which "
                            f"{present_counts[name]} of {total} {etype} entries define",
                            key=entry.key,
                            field=name,
                        )
                    )

    return issues


def _lint_undefined_string_definitions(lib: BibFile) -> list[LintIssue]:
    """Report undefined references inside preserved ``@string`` declarations."""
    issues: list[LintIssue] = []
    for raw in lib.raw_strings:
        definition = parse_raw_string_definition(raw)
        if definition is None:
            continue
        name, value = definition
        for reference in undefined_string_references(value, lib.strings):
            issues.append(
                LintIssue(
                    "undefined_string_reference",
                    "error",
                    f"BibTeX @string {name!r} references undefined string name {reference!r}",
                    field=name,
                )
            )
    return issues


def _lint_undefined_string_references(entry: BibEntry, lib: BibFile) -> list[LintIssue]:
    """Report undefined string names in one entry's original field expressions."""
    if entry.raw_content is None:
        # In-memory entries have only semantic field values. The writer will
        # brace-quote those values, so treating them as source expressions here
        # would create false positives.
        return []

    issues: list[LintIssue] = []
    for field in entry.fields:
        value = raw_field_value(entry.raw_content, field)
        if value is None:
            continue
        for reference in undefined_string_references(value, lib.strings):
            issues.append(
                LintIssue(
                    "undefined_string_reference",
                    "error",
                    f"Entry {entry.key!r} field {field!r} references undefined BibTeX string "
                    f"name {reference!r}",
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
) -> list[LintIssue]:
    """Check one entry against persisted preferences without changing it."""
    issues: list[LintIssue] = []
    fields = fields or entry.fields

    pattern = get_jabref_key_pattern(lib, entry.type)
    if pattern:
        try:
            expected_key = generate_key_from_pattern(entry, pattern)
        except UnsupportedCitationKeyPatternError as exc:
            issues.append(
                LintIssue(
                    "unsupported_citation_key_pattern",
                    "warning",
                    f"Entry {entry.key!r} cannot be checked against key pattern {pattern!r}: {exc}",
                    key=entry.key,
                )
            )
        else:
            if entry.key != expected_key:
                issues.append(
                    LintIssue(
                        "citation_key_pattern_mismatch",
                        "warning",
                        f"Entry {entry.key!r} does not match configured citation-key pattern "
                        f"{pattern!r}; expected {expected_key!r}",
                        key=entry.key,
                    )
                )

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

    if profile.journal_style in {"abbreviated", "full"} and journal_sources is not None:
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


def _lint_entry(
    entry: BibEntry,
    fields: dict[str, str] | None = None,
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    fields = fields or entry.fields
    etype = entry.type.lower()

    if entry.type != etype:
        issues.append(
            LintIssue(
                "noncanonical_entry_type_case",
                "warning",
                f"Entry {entry.key!r} uses mixed-case entry type {entry.type!r}; use {etype!r}",
                key=entry.key,
            )
        )

    field_names = raw_field_names(entry.raw_content) if entry.raw_content else entry.fields.keys()
    for name in field_names:
        canonical = name.lower()
        if name != canonical:
            issues.append(
                LintIssue(
                    "noncanonical_field_name_case",
                    "warning",
                    f"Entry {entry.key!r} uses mixed-case field name {name!r}; use {canonical!r}",
                    key=entry.key,
                    field=canonical,
                )
            )

    if not entry.key.strip():
        issues.append(
            LintIssue(
                "empty_key",
                "error",
                f"{etype} entry has an empty citation key "
                f"(title: {entry.fields.get('title', '').strip() or '?'!r})",
                key=entry.key,
            )
        )

    for alternatives in _REQUIRED.get(etype, []):
        if not any(fields.get(name, "").strip() for name in alternatives):
            issues.append(
                LintIssue(
                    "missing_required_field",
                    "error",
                    f"{etype} entry {entry.key!r} is missing required field "
                    f"{' or '.join(alternatives)}",
                    key=entry.key,
                    field=alternatives[0],
                )
            )

    doi = fields.get("doi", "").strip()
    if doi:
        try:
            normalize_doi(doi)
        except ValueError:
            issues.append(
                LintIssue(
                    "malformed_doi",
                    "warning",
                    f"Entry {entry.key!r} has a malformed DOI: {doi!r}",
                    key=entry.key,
                    field="doi",
                )
            )
    elif etype in _DOI_EXPECTED:
        issues.append(
            LintIssue(
                "missing_doi",
                "warning",
                f"Entry {entry.key!r} ({etype}) has no DOI",
                key=entry.key,
                field="doi",
            )
        )

    groups = entry.fields.get("groups")
    if groups and groups.strip() and any(not s.strip() for s in groups.split(";")):
        issues.append(
            LintIssue(
                "malformed_groups",
                "warning",
                f"Entry {entry.key!r} has a malformed groups field: {groups!r}",
                key=entry.key,
                field="groups",
            )
        )

    return issues
