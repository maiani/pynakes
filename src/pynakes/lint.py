"""Validation checks for a BibTeX library.

Reports issues as a flat list of :class:`LintIssue` objects, each tagged with a
severity (``error`` or ``warning``), the offending entry key, and a message.
Checks: duplicate keys, missing required fields (by entry type), malformed or
missing DOIs, malformed JabRef ``groups`` formatting, and noncanonical
entry-type / field-name casing.
"""

from dataclasses import dataclass
from typing import Optional

from pynakes.doi import normalize_doi
from pynakes.editing import raw_field_names
from pynakes.model import BibFile

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


@dataclass
class LintIssue:
    """A single validation finding."""

    type: str
    severity: str  # "error" | "warning"
    message: str
    key: Optional[str] = None
    field: Optional[str] = None

    def to_dict(self) -> dict:
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

    for entry in lib.entries.values():
        issues.extend(_lint_entry(entry))

    return issues


def _lint_entry(entry) -> list[LintIssue]:
    issues: list[LintIssue] = []
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
        if not any(entry.fields.get(name, "").strip() for name in alternatives):
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

    doi = entry.fields.get("doi", "").strip()
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
