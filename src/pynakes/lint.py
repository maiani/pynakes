"""Validation checks for a BibTeX library.

Reports issues as a flat list of :class:`LintIssue` objects, each tagged with a
severity (``error`` or ``warning``), the offending entry key, and a message.
Checks: duplicate keys, missing required fields (by entry type), malformed or
missing DOIs, and malformed JabRef ``groups`` formatting.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pynakes.model import BibLibrary

# A bare DOI: ``10.<registrant>/<suffix>``. URL prefixes are stripped first.
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_URL_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)

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


def lint(lib: BibLibrary) -> list[LintIssue]:
    """Run all validation checks and return the issues found."""
    issues: list[LintIssue] = []

    for key, count in lib.entries.duplicate_keys().items():
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
        if not _DOI_RE.match(_DOI_URL_RE.sub("", doi)):
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
