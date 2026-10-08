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
from pathlib import Path

from pynakes._identifiers import normalize_doi
from pynakes._lint_issue import (
    CATEGORY_FIXERS,
    ISSUE_CATEGORIES,
    SEVERITIES,
    LintCategory,
    LintIssue,
    LintSeverity,
    issue_category,
)
from pynakes._lint_profile import (
    PROFILE_ISSUE_TYPES,
    LintProfile,
    _lint_profile_entry,
    is_profile_issue,
    profile_required_fields,
    resolve_lint_profile,
)
from pynakes._lint_required import required_field_rules
from pynakes.bibtex_parser import parse_raw_string_definition
from pynakes.canonical import EntryTypeCase, resolve_entry_type_case
from pynakes.editing import raw_field_names, raw_field_value
from pynakes.formatters import normalize_page_numbers
from pynakes.identity import identity_class
from pynakes.journals import (
    load_sources,
)
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    entry_reference_keys,
    is_key_regeneration_exempt,
    planned_regenerated_keys,
)
from pynakes.metadata import (
    library_dialect,
    metadata_category,
    validate_metadata_value,
)
from pynakes.model import BibEntry, BibFile, MetadataBlock, undefined_string_references
from pynakes.usage import tex_sources_from_metadata, validate_tex_sources

__all__ = [
    "CATEGORY_FIXERS",
    "ISSUE_CATEGORIES",
    "PROFILE_ISSUE_TYPES",
    "SEVERITIES",
    "LintCategory",
    "LintIssue",
    "LintProfile",
    "LintSeverity",
    "is_profile_issue",
    "issue_category",
    "lint",
    "profile_required_fields",
    "resolve_lint_profile",
]

# Entry types for which a missing DOI is worth a (low-severity) warning. This is
# lint's own policy, not a requirement either format states, so it stays here
# rather than in the spec tables.
_DOI_EXPECTED = {"article", "inproceedings"}

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

# Fields whose absence is not a gap when the entry carries an equivalent.
# A modern article is located by DOI or article number, not by a page range —
# Physical Review and many others stopped issuing page ranges altogether — so
# reporting its missing ``pages`` is noise the reader cannot act on. The
# finding still fires for an entry with no locator at all, which is the case
# where a missing page range genuinely leaves the reference incomplete.
_CONSISTENCY_ALTERNATIVES: dict[str, frozenset[str]] = {
    "pages": frozenset({"articleno", "artnum", "eid", "numpages", "doi"}),
}


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
    try:
        type_case = resolve_entry_type_case(lib)
    except ValueError:
        # ``_lint_metadata`` reports the invalid value; check against the default.
        type_case = "lower"

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
        issues.extend(_lint_entry(entry, fields, dialect=dialect, type_case=type_case))
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

    issues.extend(_lint_reference_targets(lib))
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
                if fields.get(name, "").strip():
                    continue
                alternatives = _CONSISTENCY_ALTERNATIVES.get(name, frozenset())
                if any(fields.get(alt, "").strip() for alt in alternatives):
                    continue
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


def _lint_pages(entry: BibEntry, fields: dict[str, str]) -> list[LintIssue]:
    """Report a page range punctuated with anything but BibTeX's ``--``.

    A Unicode en-dash in ``pages`` renders under UTF-8 plus ``inputenc`` and is
    visually near-identical to a hyphen, so it survives review and propagates
    — while breaking under 8-bit ``bibtex`` with some styles. It reaches a
    library through an import from a provider that spells ranges that way, or
    through a paste from a publisher page.

    The finding fires exactly when ``normalize`` would rewrite the value, so
    lint never reports something the named fix would leave alone: a single
    hyphen (``12-14``) is flagged along with the dashes, and an article number
    or a ``7,41,73--97`` list is not.
    """
    value = fields.get("pages", "")
    if not value.strip():
        return []
    normalized = normalize_page_numbers(value)
    if normalized == value:
        return []
    return [
        LintIssue(
            "nonstandard_page_range",
            "warning",
            f"Entry {entry.key!r} has a page range {value!r} that BibTeX spells {normalized!r}",
            key=entry.key,
            field="pages",
        )
    ]


def _lint_reference_targets(lib: BibFile) -> list[LintIssue]:
    """Report a ``crossref``/``xdata``/... naming a key the library lacks."""
    present = set(lib.entries.keys())
    return [
        LintIssue(
            "missing_reference_target",
            "warning",
            f"Entry {entry.key!r} has {field} = {{{target}}}, but no entry has that key",
            key=entry.key,
            field=field,
        )
        for entry in lib.entries.values()
        for field, target in entry_reference_keys(entry)
        if target not in present
    ]


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
    type_case: EntryTypeCase = "lower",
) -> list[LintIssue]:
    """Run structural checks on a single entry; return all findings.

    ``type_case`` is the library's ``format-entry-type-case``: a type is
    reported exactly when ``format`` would recase it, so never under
    ``preserve``.
    """
    if fields is None:
        fields = entry.fields
    etype = entry.type.lower()

    issues: list[LintIssue] = []
    if type_case == "lower" and entry.type != etype:
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
    issues += _lint_pages(entry, fields)
    issues += _lint_groups(entry)
    return issues
