"""Validation checks for a BibTeX library.

Reports issues as a flat list of :class:`LintIssue` objects, each tagged with a
severity (``error``, ``warning``, or ``info``), a category, the offending entry
key, and a message, plus the source line of the finding's entry or metadata
block when the library was parsed from text. Checks: duplicate keys, missing
required fields (by entry type), undefined BibTeX string references, cross-entry
field consistency (a field most entries of a type define but some omit),
malformed or missing DOIs, malformed JabRef ``groups`` formatting, noncanonical
entry-type / field-name casing, unresolved journal titles, metadata-comment
schema drift (unknown pynakes keys, invalid values, duplicate blocks), and
deviations from the library's stored metadata profile.

``lint`` only diagnoses; it never rewrites a library. The category of a finding
names which command resolves it — ``normalize`` for content conventions and
``format`` for layout — while ``correctness`` and ``consistency`` findings need
a human decision. Severity ranks urgency: layout and consistency findings are
``info`` so that they cannot bury a structural ``error``.

BibLaTeX required-field validation follows the official BibLaTeX manual on
CTAN, section 2.1 "Entry Types" and entry-type aliases:
https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pynakes._identifiers import normalize_doi
from pynakes.bibtex_parser import parse_raw_string_definition
from pynakes.editing import raw_field_names, raw_field_value
from pynakes.fields import TITLE_FIELDS, title_capitalization_is_protected
from pynakes.identity import identity_class
from pynakes.journals import (
    DEFAULT_JOURNAL_SOURCE,
    JOURNAL_FIELDS,
    JournalSources,
    expected_journal_title,
    load_sources,
)
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    generate_key_from_pattern,
    is_key_regeneration_exempt,
    planned_regenerated_keys,
)
from pynakes.metadata import (
    library_dialect,
    library_key_pattern,
    metadata_bool,
    metadata_category,
    metadata_list,
    metadata_value,
    validate_metadata_value,
)
from pynakes.model import BibEntry, BibFile, MetadataBlock, undefined_string_references
from pynakes.usage import tex_sources_from_metadata, validate_tex_sources

RequiredRules = dict[str, list[tuple[str, ...]]]

# Required fields by entry type. Each requirement is a tuple of acceptable field
# names (any one satisfies it), to tolerate compatibility aliases such as
# journal/journaltitle, year/date, and school/institution.
_BIBTEX_REQUIRED: RequiredRules = {
    "article": [("author",), ("title",), ("journal", "journaltitle"), ("year", "date")],
    "book": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "inbook": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "incollection": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "conference": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "manual": [("title",)],
    "phdthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "mastersthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "thesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "techreport": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "unpublished": [("author",), ("title",), ("note",)],
}

_BIBLATEX_REQUIRED: RequiredRules = {
    # BibLaTeX default data model, section 2.1.1 "Entry Types".
    # Source of truth: the official BibLaTeX manual from CTAN, section 2.1:
    # https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
    "article": [("author",), ("title",), ("journaltitle", "journal"), ("year", "date")],
    "book": [("author",), ("title",), ("year", "date")],
    "mvbook": [("author",), ("title",), ("year", "date")],
    "inbook": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "booklet": [("author", "editor"), ("title",), ("year", "date")],
    "collection": [("editor",), ("title",), ("year", "date")],
    "mvcollection": [("editor",), ("title",), ("year", "date")],
    "incollection": [("author",), ("title",), ("editor",), ("booktitle",), ("year", "date")],
    "dataset": [("author", "editor"), ("title",), ("year", "date")],
    "manual": [("author", "editor"), ("title",), ("year", "date")],
    "misc": [("author", "editor"), ("title",), ("year", "date")],
    "online": [("author", "editor"), ("title",), ("year", "date"), ("doi", "eprint", "url")],
    "patent": [("author",), ("title",), ("number",), ("year", "date")],
    "periodical": [("editor",), ("title",), ("year", "date")],
    "proceedings": [("title",), ("year", "date")],
    "mvproceedings": [("title",), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "report": [("author",), ("title",), ("type",), ("institution", "school"), ("year", "date")],
    "thesis": [("author",), ("title",), ("type",), ("institution", "school"), ("year", "date")],
    "unpublished": [("author",), ("title",), ("year", "date")],
}

_BIBLATEX_REQUIREMENT_ALIASES: dict[str, str] = {
    # Soft aliases from the BibLaTeX manual, section 2.1.1.
    "bookinbook": "inbook",
    "suppbook": "inbook",
    "suppcollection": "incollection",
    "suppperiodical": "article",
    "reference": "collection",
    "mvreference": "mvcollection",
    "inreference": "incollection",
    "review": "article",
    "software": "misc",
    # Hard aliases from the BibLaTeX manual, section 2.1.2. These are resolved by biber.
    "conference": "inproceedings",
    "electronic": "online",
    "www": "online",
}

_BIBLATEX_ALIAS_REQUIRED: RequiredRules = {
    "mastersthesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "phdthesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "techreport": [("author",), ("title",), ("institution", "school"), ("year", "date")],
}

# Entry types for which a missing DOI is worth a (low-severity) warning.
_DOI_EXPECTED = {"article", "inproceedings"}


def required_field_rules(entry_type: str, dialect: str) -> tuple[tuple[str, ...], ...]:
    """Return built-in required fields for ``entry_type`` in ``dialect``.

    Each returned tuple contains interchangeable field names, any one of which
    satisfies that requirement. The immutable result is also used by
    interactive entry editing so prompting and lint validation share one source
    of truth.

    For BibLaTeX, derived from the official BibLaTeX manual on CTAN, section 2.1:
    https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
    """
    etype = entry_type.lower()
    if dialect != "biblatex":
        return tuple(_BIBTEX_REQUIRED.get(etype, []))
    if etype in _BIBLATEX_ALIAS_REQUIRED:
        return tuple(_BIBLATEX_ALIAS_REQUIRED[etype])
    return tuple(_BIBLATEX_REQUIRED.get(_BIBLATEX_REQUIREMENT_ALIASES.get(etype, etype), []))


# Fields excluded from the cross-entry consistency check: structural/reference
# fields and JabRef-internal management fields that legitimately vary per entry.
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

# Fields whose absence is never a defect, only a difference in how rich the
# metadata source was. A record from a discipline database legitimately lacks
# the publisher decoration that DOI content negotiation supplies, so comparing
# these across peers reports provenance, not a bibliographic gap. Fields that
# a type genuinely requires are already excluded by ``required_field_rules``.
_CONSISTENCY_DECORATION_FIELDS = frozenset(
    {
        "abstract",
        "copyright",
        "day",
        "eissn",
        "isbn",
        "issn",
        "keywords",
        "language",
        "month",
        "pagetotal",
        "publisher",
        "url",
        "urldate",
    }
)

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


def is_profile_issue(issue: "LintIssue") -> bool:
    """Return whether a finding is a stored-profile conformance deviation."""
    return issue.type in PROFILE_ISSUE_TYPES


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
    "undefined_string_reference": "correctness",
    "no_entries": "correctness",
    "citation_key_pattern_mismatch": "content",
    "journal_style_mismatch": "content",
    "malformed_doi": "content",
    "malformed_groups": "content",
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


# Findings whose ``key`` names a metadata setting or an on-disk file rather
# than a citation key, so the entry-line lookup must never apply to them.
_LINE_EXEMPT_TYPES = frozenset(
    {
        "unknown_metadata_key",
        "invalid_metadata_value",
        "duplicate_metadata_block",
        "missing_tex_source",
    }
)


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


def lint(lib: BibFile, base_dir: str | Path | None = None) -> list[LintIssue]:
    """Run all validation checks and return the issues found.

    ``base_dir`` (normally the ``.bib``'s folder) resolves the library's
    ``tex-sources`` metadata so a source path that no longer exists on disk is
    reported; without it, that check is skipped since relative paths cannot be
    resolved.
    """
    issues: list[LintIssue] = []
    profile = resolve_lint_profile(lib)
    journal_sources = None
    dialect = library_dialect(lib)

    # A value outside the journal-style enum is reported by ``_lint_metadata``
    # as ``invalid_metadata_value`` (the schema is the single validator); here
    # only a well-formed non-default style needs its sources loaded.
    if profile.journal_style in {"abbreviated", "full"}:
        try:
            journal_sources = load_sources(
                profile.journal_table, profile.ltwa_table, profile.journal_source
            )
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

    for key, indices in lib.entries.duplicate_key_instances().items():
        if not key.strip():
            # Empty keys are reported per-entry below, not as a duplicate set.
            continue
        line_refs = ", ".join(f"#{i}" for i in indices)
        issues.append(
            LintIssue(
                "duplicate_key",
                "error",
                f"Citation key {key!r} appears {len(indices)} times (entry {line_refs})",
                key=key,
                line=lib.entries.values()[indices[0]].start_line,
            )
        )

    issues.extend(_lint_undefined_string_definitions(lib))

    try:
        expected_keys = {id(entry): key for entry, key in planned_regenerated_keys(lib)}
    except UnsupportedCitationKeyPatternError:
        # `_lint_key_pattern` reports the unsupported pattern per affected
        # entry. Do not let that one profile error prevent the remaining lint
        # checks from running.
        expected_keys = {}
    for entry in lib.entries.values():
        fields = lib.resolved_fields(entry)
        issues.extend(_lint_duplicate_fields(entry))
        issues.extend(_lint_undefined_string_references(entry, lib))
        issues.extend(_lint_entry(entry, fields, dialect=dialect))
        issues.extend(
            _lint_profile_entry(
                entry,
                lib,
                profile,
                journal_sources,
                fields,
                expected_key=expected_keys.get(id(entry)),
                key_pattern_exempt=is_key_regeneration_exempt(entry),
            )
        )

    issues.extend(_lint_metadata(lib))
    issues.extend(_lint_field_consistency(lib, dialect=dialect))
    if base_dir is not None:
        issues.extend(_lint_tex_sources(lib, base_dir))

    # Locate entry-level findings that could not stamp themselves. The first
    # occurrence of a key wins: with duplicates the finding already names the
    # instance indices in its message, and one line is enough to navigate by.
    # Metadata findings carry their block's line (their keys name metadata
    # settings, which may collide with citation keys) and tex-source findings
    # are about files on disk, so both are exempt here.
    first_line_by_key: dict[str, int] = {}
    for entry in lib.entries.values():
        if entry.start_line is not None and entry.key not in first_line_by_key:
            first_line_by_key[entry.key] = entry.start_line
    for issue in issues:
        if issue.line is None and issue.key and issue.type not in _LINE_EXEMPT_TYPES:
            issue.line = first_line_by_key.get(issue.key)
    return issues


def _lint_tex_sources(lib: BibFile, base_dir: str | Path) -> list[LintIssue]:
    """Flag ``tex-sources`` metadata entries that don't exist on disk."""
    sources = tex_sources_from_metadata(lib, base_dir)
    return [
        LintIssue("missing_tex_source", "warning", warning["message"], field="tex-sources")
        for warning in validate_tex_sources(sources)
    ]


def _lint_metadata(lib: BibFile) -> list[LintIssue]:
    """Audit top-level metadata comments for schema drift and duplicate blocks.

    Unknown keys are reported for the ``pynakes-meta`` namespace only: pynakes
    owns it and claims to understand every key it writes, while ``jabref-meta``
    is JabRef's vocabulary and pynakes only catalogues a subset of it. Values
    are validated for every known key whose grammar pynakes defines (dialect,
    fetch-policy tokens, formatting choices, journal style). Repeated blocks for
    one key within a namespace make the effective metadata ambiguous and are
    reported — except the JabRef flat ``groups:`` format, which legitimately
    repeats the ``groups`` key once per group line.
    """
    counts: dict[tuple[str, str], list[MetadataBlock]] = {}
    issues: list[LintIssue] = []

    for block in lib.metadata_blocks:
        namespace_key = (block.namespace, block.key.lower())
        # The JabRef flat ``groups:`` format is one block per group by design;
        # excluding it keeps a normal JabRef library from reading as drift.
        if not (block.namespace == "jabref" and block.key.lower() == "groups"):
            counts.setdefault(namespace_key, []).append(block)

        if metadata_category(block.key) == "unknown":
            if block.namespace == "pynakes":
                issues.append(
                    LintIssue(
                        "unknown_metadata_key",
                        "warning",
                        f"Metadata key {block.key!r} in pynakes-meta is not recognized by the "
                        "pynakes key schema",
                        key=block.key,
                        field=block.key,
                        line=block.start_line,
                    )
                )
            continue

        try:
            validate_metadata_value(block.key, block.value)
        except ValueError as exc:
            issues.append(
                LintIssue(
                    "invalid_metadata_value",
                    "warning",
                    f"Metadata key {block.key!r} in {block.namespace}-meta has an invalid "
                    f"value: {exc}",
                    key=block.key,
                    field=block.key,
                    line=block.start_line,
                )
            )

    for (namespace, _key), blocks in counts.items():
        if len(blocks) > 1:
            key = blocks[0].key
            issues.append(
                LintIssue(
                    "duplicate_metadata_block",
                    "warning",
                    f"{namespace}-meta contains {len(blocks)} blocks for key {key!r}; "
                    "the path preserves them but the effective metadata is ambiguous",
                    key=key,
                    field=key,
                    line=blocks[0].start_line,
                )
            )

    return issues


def _lint_duplicate_fields(entry: BibEntry) -> list[LintIssue]:
    """Report repeated field assignments that the semantic mapping cannot represent.

    The round-trip parser retains the complete entry source, but ``BibEntry.fields``
    intentionally exposes a mapping. A canonical rewrite must therefore refuse a
    repeated field instead of silently keeping only the mapping's final value.
    """
    if entry.raw_content is None:
        return []
    names = raw_field_names(entry.raw_content)
    counts: dict[str, int] = {}
    spelling: dict[str, str] = {}
    for name in names:
        normalized = name.lower()
        counts[normalized] = counts.get(normalized, 0) + 1
        spelling.setdefault(normalized, name)
    return [
        LintIssue(
            "duplicate_field",
            "error",
            f"Entry {entry.key!r} contains field {spelling[name]!r} {count} times",
            key=entry.key,
            field=name,
        )
        for name, count in counts.items()
        if count > 1
    ]


def _lint_field_consistency(lib: BibFile, *, dialect: str = "bibtex") -> list[LintIssue]:
    """Report fields a majority of comparable entries define but some omit.

    Entries are grouped by entry type **and**
    :func:`~pynakes.identity.identity_class`, so a preprint is compared with
    preprints and a book with books rather than with published articles that
    carry issue and publisher metadata by construction. A field is flagged only
    when a strict majority of the group carries it and this entry does not.
    Required fields, JabRef structural/management fields, and publisher
    decoration whose absence is never a defect are excluded. Findings are
    advisory ``info`` in the ``consistency`` category.
    """
    by_group: dict[tuple[str, str], list[BibEntry]] = {}
    for entry in lib.entries.values():
        if entry.key.strip():
            by_group.setdefault((entry.type.lower(), identity_class(entry)), []).append(entry)

    issues: list[LintIssue] = []
    for (etype, _identity), entries in by_group.items():
        total = len(entries)
        if total < 3:
            continue
        required = {
            name for alternatives in required_field_rules(etype, dialect) for name in alternatives
        }
        resolved = [lib.resolved_fields(entry) for entry in entries]

        present_counts: dict[str, int] = {}
        for fields in resolved:
            for name, value in fields.items():
                if value and value.strip():
                    present_counts[name] = present_counts.get(name, 0) + 1

        majority = {
            name
            for name, count in present_counts.items()
            if count < total
            and count * 2 > total
            and name not in required
            and name not in _CONSISTENCY_SKIP_FIELDS
            and name not in _CONSISTENCY_DECORATION_FIELDS
        }

        for entry, fields in zip(entries, resolved):
            for name in sorted(majority):
                if not fields.get(name, "").strip():
                    issues.append(
                        LintIssue(
                            "inconsistent_field",
                            "info",
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
        # In-memory entries have only semantic field values; treating them as
        # source expressions would create false positives.
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


# ---------------------------------------------------------------------------
# _lint_entry helpers
# ---------------------------------------------------------------------------


def _lint_empty_key(entry: BibEntry) -> list[LintIssue]:
    """Report an empty citation key."""
    if entry.key.strip():
        return []
    title = entry.fields.get("title", "").strip() or "?"
    return [
        LintIssue(
            "empty_key",
            "error",
            f"{entry.type.lower()} entry has an empty citation key (title: {title!r})",
            key=entry.key,
        )
    ]


def _lint_doi(entry: BibEntry, fields: dict[str, str]) -> list[LintIssue]:
    """Check the DOI field for validity; warn when expected but absent."""
    etype = entry.type.lower()
    doi = fields.get("doi", "").strip()
    if doi:
        try:
            normalize_doi(doi)
            return []
        except ValueError:
            return [
                LintIssue(
                    "malformed_doi",
                    "warning",
                    f"Entry {entry.key!r} has a malformed DOI: {doi!r}",
                    key=entry.key,
                    field="doi",
                )
            ]
    if etype in _DOI_EXPECTED:
        return [
            LintIssue(
                "missing_doi",
                "info",
                f"Entry {entry.key!r} ({etype}) has no DOI",
                key=entry.key,
                field="doi",
            )
        ]
    return []


def _lint_groups(entry: BibEntry) -> list[LintIssue]:
    """Check the groups field for malformed semicolon-separated values."""
    groups = entry.fields.get("groups")
    if groups and groups.strip() and any(not s.strip() for s in groups.split(";")):
        return [
            LintIssue(
                "malformed_groups",
                "warning",
                f"Entry {entry.key!r} has a malformed groups field: {groups!r}",
                key=entry.key,
                field="groups",
            )
        ]
    return []


def _lint_required_fields(entry: BibEntry, fields: dict[str, str], dialect: str) -> list[LintIssue]:
    """Report missing required fields for the entry type."""
    etype = entry.type.lower()
    return [
        LintIssue(
            "missing_required_field",
            "error",
            f"{etype} entry {entry.key!r} is missing required field {' or '.join(alternatives)}",
            key=entry.key,
            field=alternatives[0],
        )
        for alternatives in required_field_rules(etype, dialect)
        if not any(fields.get(name, "").strip() for name in alternatives)
    ]


def _lint_entry(
    entry: BibEntry,
    fields: dict[str, str] | None = None,
    *,
    dialect: str = "bibtex",
) -> list[LintIssue]:
    """Run structural checks on a single entry; return all findings."""
    if fields is None:
        fields = entry.fields
    etype = entry.type.lower()

    issues: list[LintIssue] = []
    if entry.type != etype:
        issues.append(
            LintIssue(
                "noncanonical_entry_type_case",
                "info",
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
                    "info",
                    f"Entry {entry.key!r} uses mixed-case field name {name!r}; use {canonical!r}",
                    key=entry.key,
                    field=canonical,
                )
            )

    issues += _lint_empty_key(entry)
    issues += _lint_required_fields(entry, fields, dialect)
    issues += _lint_doi(entry, fields)
    issues += _lint_groups(entry)
    return issues


# ---------------------------------------------------------------------------
# _lint_profile_entry helpers
# ---------------------------------------------------------------------------


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
