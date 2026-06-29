"""High-level bibliography normalization routine."""

from dataclasses import dataclass, field

from pynakes import authors as author_ops
from pynakes import fields as field_ops
from pynakes import journals as journal_ops
from pynakes._constants import NAME_FIELDS, TITLE_FIELDS
from pynakes._identifiers import normalize_doi
from pynakes.editing import (
    normalize_entry_field_names,
    raw_field_value,
    set_entry_field,
    set_entry_field_expression,
    set_entry_type,
)
from pynakes.formatters import FIELD_FORMATTERS
from pynakes.metadata import (
    SAVE_ORDER_KEY_FIELDS,
    library_save_actions,
    library_save_order,
    metadata_bool,
    metadata_list,
    metadata_value,
)
from pynakes.model import COMMON_STRINGS, BibFile

# JabRef saveActions formatter keys mapped to pynakes normalization concerns.
_DOI_FORMATTERS = ("clean_up_doi", "short_doi")

# Normalize settings live under the ``normalize-`` key prefix.
METADATA_PREFIX = "normalize-"
# Recognized month spellings mapped to their canonical BibTeX macro. BibTeX
# predefines only the three-letter macros ``jan``..``dec``; full names ("June")
# and common abbreviation variants ("Sept") are noncanonical — and, unbraced,
# undefined string references — that normalization rewrites to the macro. A
# trailing period (``Sept.``) is stripped before lookup.
_MONTH_NAME_MACROS = {macro: macro for macro in COMMON_STRINGS}
_MONTH_NAME_MACROS.update({name.lower(): macro for macro, name in COMMON_STRINGS.items()})
# Common abbreviation variants that are neither the macro nor the full name.
_MONTH_NAME_MACROS["sept"] = "sep"


@dataclass
class NormalizeOptions:
    """Optional overrides for the composed normalization policy.

    ``None`` delegates to compatible JabRef/pynakes metadata and then the
    built-in default. Explicit values take precedence. This object configures
    the orchestration only; individual transformations remain in their domain
    modules (titles, authors, journals, and DOIs).
    """

    protect_titles: bool | None = None
    title_fields: list[str] | None = None
    protected_terms: list[str] | None = None
    author_style: str | None = None
    journal_style: str | None = None
    journal_table: str | None = None
    ltwa_table: str | None = None
    normalize_dois: bool | None = None
    identifier_case: bool | None = None
    format_metadata: bool | None = None
    # One-off sort override using JabRef field names; each token is
    # ``field`` or ``field:asc`` / ``field:desc``. ``["original"]`` (or
    # ``["none"]``) forces "keep current order", overriding ``saveOrderConfig``.
    sort_by: list[str] | None = None


@dataclass
class NormalizeResult:
    """Per-domain counts and non-fatal warnings from normalization.

    ``operations`` is the stable compact view used by callers that need a
    single structured summary without inspecting the individual fields.
    """

    title_fields: dict[str, int] = field(default_factory=dict)
    authors: int = 0
    journals: int = 0
    dois: int = 0
    months: int = 0
    save_action_fields: int = 0
    entry_types: int = 0
    field_names: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)

    sort_entries_count: int = 0
    sort_criteria: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def operations(self) -> dict[str, object]:
        """Return the per-domain change counts as a single JSON-friendly dict."""
        return {
            "title_fields": dict(self.title_fields),
            "authors": self.authors,
            "journals": self.journals,
            "dois": self.dois,
            "months": self.months,
            "save_action_fields": self.save_action_fields,
            "entry_types": self.entry_types,
            "field_names": self.field_names,
            "sorted_entries": self.sort_entries_count,
        }


def _normalize_setting(lib: BibFile, name: str) -> str | None:
    """Look up a normalize setting by its canonical ``normalize-`` key."""
    return metadata_value(lib, f"{METADATA_PREFIX}{name}")


def _resolve_bool(lib: BibFile, option: bool | None, name: str, default: bool) -> bool:
    if option is not None:
        return option
    return metadata_bool(_normalize_setting(lib, name), default)


def _resolve_choice(
    lib: BibFile,
    option: str | None,
    name: str,
    allowed: set[str],
    default: str,
) -> str:
    if option is None or option == "metadata":
        value = _normalize_setting(lib, name)
        resolved = value.lower() if value else default
    else:
        resolved = option.lower()
    if resolved not in allowed:
        raise ValueError(
            f"Invalid {name.replace('-', ' ')} {resolved!r}; expected one of: "
            f"{', '.join(sorted(allowed | {'metadata'}))}"
        )
    return resolved


def _resolve_title_fields(lib: BibFile, option: list[str] | None) -> list[str]:
    if option:
        return option
    meta = _normalize_setting(lib, "title-fields")
    return list(metadata_list(meta)) or list(TITLE_FIELDS)


def _resolve_terms(lib: BibFile, option: list[str] | None) -> list[str]:
    terms = list(option or [])
    terms.extend(metadata_list(metadata_value(lib, "protected-terms")))
    return terms


def resolve_format_metadata(lib: BibFile, option: bool | None) -> bool:
    """Resolve whether to consolidate metadata to the file end (default on).

    An explicit CLI value wins; otherwise a ``normalize-format-metadata``
    metadata key, else the default ``True``.
    """
    return _resolve_bool(lib, option, "format-metadata", True)


def normalize_dois(lib: BibFile) -> tuple[int, list[dict[str, str]]]:
    """Normalize DOI fields, leaving invalid values untouched with warnings."""
    count = 0
    warnings: list[dict[str, str]] = []
    for entry in lib.entries.values():
        value = entry.fields.get("doi")
        if not value:
            continue
        try:
            normalized = normalize_doi(value)
        except ValueError as exc:
            warnings.append(
                {
                    "type": "invalid_doi",
                    "entry_key": entry.key,
                    "message": str(exc),
                }
            )
            continue
        if set_entry_field(entry, "doi", normalized):
            count += 1
    return count, warnings


def normalize_month_macros(lib: BibFile) -> int:
    """Normalize bare month names and standard macros to canonical BibTeX.

    BibTeX predefines ``jan`` through ``dec`` only; ``month = june`` is an
    undefined string reference, while ``month = Jan`` is valid but
    noncanonical because BibTeX macro names are case-insensitive. A declared
    custom string named ``june`` or ``jan`` is already valid and is left alone.
    If a file overrides a target standard macro (for example,
    ``@string{jun = ...}``), use a braced literal instead of changing meaning.
    """
    declared = {name.lower() for name in lib.strings}
    changed = 0
    for entry in lib.entries.values():
        if entry.raw_content is None:
            continue
        source_value = raw_field_value(entry.raw_content, "month")
        if source_value is None:
            continue
        source_name = source_value.strip().lower().rstrip(".")
        macro = _MONTH_NAME_MACROS.get(source_name)
        if macro is None or source_name in declared:
            continue
        month_name = COMMON_STRINGS[macro]
        expression = macro if macro not in declared else f"{{{month_name}}}"
        if set_entry_field_expression(entry, "month", expression, month_name):
            changed += 1
    return changed


def normalize_library(lib: BibFile, options: NormalizeOptions | None = None) -> NormalizeResult:
    """Apply the configured normalization steps to the bibliography in-place."""
    opts = options or NormalizeOptions()
    result = NormalizeResult()

    # JabRef's own saveActions, when present, drive the *defaults* for the
    # functionalities JabRef can express (author-name normalization, DOI
    # cleanup) — per the principle of using a native JabRef setting where one
    # exists. An explicit CLI option or a pynakes-meta key still overrides.
    save_actions = library_save_actions(lib)
    if save_actions is not None and save_actions.enabled:
        author_default = "jabref" if save_actions.has("normalize_names", NAME_FIELDS) else "none"
        doi_default = save_actions.has(_DOI_FORMATTERS, ("doi",))
    else:
        author_default, doi_default = "jabref", True

    if _resolve_bool(lib, opts.protect_titles, "protect-titles", True):
        terms = _resolve_terms(lib, opts.protected_terms)
        for field in _resolve_title_fields(lib, opts.title_fields):
            changed = field_ops.protect_title_capitalization(lib, field=field, terms=terms)
            if changed:
                result.title_fields[field] = changed

    author_style = _resolve_choice(
        lib, opts.author_style, "author-style", author_ops.AUTHOR_STYLES, author_default
    )
    result.authors = author_ops.normalize_authors(lib, author_style)

    if _resolve_bool(lib, opts.normalize_dois, "dois", doi_default):
        result.dois, doi_warnings = normalize_dois(lib)
        result.warnings.extend(doi_warnings)

    # Journal abbreviation/expansion is *off* by default: it is opinionated and
    # not reversible without the right table, so it runs only when a style is
    # configured explicitly (CLI ``--journal-style`` or a ``normalize-journal-style``
    # metadata key).
    journal_style = _resolve_choice(
        lib, opts.journal_style, "journal-style", journal_ops.JOURNAL_STYLES, "none"
    )
    journal_table = opts.journal_table or metadata_value(lib, "journal-table")
    ltwa_table = opts.ltwa_table or metadata_value(lib, "ltwa-table")
    journal_sources = journal_ops.load_sources(journal_table, ltwa_table)
    journal_result = journal_ops.normalize_journals(lib, journal_style, journal_sources)
    result.journals = journal_result.changed
    result.warnings.extend(journal_ops.unknown_journal_warnings(journal_result.unknown))

    # Apply the remaining JabRef saveActions field formatters (date/month/pages)
    # exactly where the file configures them. There is no pynakes-meta or CLI
    # equivalent: these run because JabRef's own saveActions ask for them.
    if save_actions is not None and save_actions.enabled:
        result.save_action_fields, formatter_warnings = _apply_save_action_formatters(
            lib, save_actions
        )
        result.warnings.extend(formatter_warnings)

    # This syntax-specific pass repairs bare full month names and canonicalizes
    # predefined macro spelling without changing literals or custom strings.
    result.months = normalize_month_macros(lib)

    if _resolve_bool(lib, opts.identifier_case, "identifier-case", True):
        result.entry_types, result.field_names = normalize_identifier_case(lib)

    criteria = _resolve_sort_criteria(lib, opts.sort_by)
    if criteria:
        sort_entries(lib, criteria)
        result.sort_criteria = criteria
        result.sort_entries_count = len(lib.entries)

    return result


def _resolve_sort_criteria(lib: BibFile, sort_by: list[str] | None) -> list[tuple[str, bool]]:
    """Resolve the entry sort order, JabRef-compatibly.

    An explicit CLI ``sort_by`` wins: each token is ``field`` or
    ``field:asc``/``field:desc`` (the JabRef field name; ``key`` is accepted for
    the citation key). A lone ``original`` or ``none`` token means "keep current
    order". With no CLI override, JabRef's ``saveOrderConfig`` metadata drives
    the order — but only when its type is ``specified``, matching JabRef, which
    leaves entries untouched for ``original``/``table``.
    """
    if sort_by:
        tokens = [token.strip() for token in sort_by if token.strip()]
        if not tokens or (len(tokens) == 1 and tokens[0].lower() in {"original", "none"}):
            return []
        criteria: list[tuple[str, bool]] = []
        for token in tokens:
            name, _, direction = token.partition(":")
            descending = direction.strip().lower() in {"desc", "descending", "true", "down"}
            criteria.append((name.strip(), descending))
        return criteria

    save_order = library_save_order(lib)
    if save_order is not None and save_order.order_type == "specified":
        return list(save_order.criteria)
    return []


def sort_entries(lib: BibFile, criteria: list[tuple[str, bool]]) -> int:
    """Reorder ``lib`` entries in-place by the given criteria.

    ``criteria`` is an ordered ``(field, descending)`` list; the first is the
    primary sort. Implemented as successive stable sorts from the least- to the
    most-significant criterion, so per-criterion ascending/descending is honored
    independently. Returns the number of entries.
    """
    for field_name, descending in reversed(criteria):
        lib.entries.reorder(
            lambda entry, f=field_name: _entry_sort_key(entry, f),
            reverse=descending,
        )
    return len(lib.entries)


def _entry_sort_key(entry, field_name: str) -> tuple:
    """Compute a stable sort key for *entry* on *field_name* (JabRef field name).

    JabRef's ``citationkey`` (and the ``bibtexkey``/``key`` aliases) sorts by the
    citation key; ``entrytype``/``type`` by the entry type; any other name is a
    bibliographic field. Entries missing the field sort last (ascending). ``year``
    is compared numerically so ``2010`` precedes ``2020``.
    """
    name = field_name.lower()
    if name in SAVE_ORDER_KEY_FIELDS:
        return (0, entry.key.lower(), "")
    if name in {"entrytype", "type"}:
        return (0, entry.type.lower(), "")
    raw = entry.fields.get(name, "")
    if not raw:
        return (1, "", "")  # missing → last
    if name == "year":
        try:
            return (0, int(raw), "")
        except ValueError:
            return (0, 0, raw.lower())
    return (0, raw.lower(), "")


def normalize_identifier_case(lib: BibFile) -> tuple[int, int]:
    """Lowercase entry types and field names while preserving entry layout."""
    entry_types = 0
    field_names = 0
    for entry in lib.entries.values():
        if set_entry_type(entry, entry.type.lower()):
            entry_types += 1
        field_names += normalize_entry_field_names(entry)
    return entry_types, field_names


def _apply_save_action_formatters(lib: BibFile, save_actions) -> tuple[int, list[dict[str, str]]]:
    """Apply supported saveActions field formatters per the file's field map."""
    changed = 0
    warnings: list[dict[str, str]] = []
    handled_elsewhere = {"normalize_names", *_DOI_FORMATTERS}
    for field_name, formatter_keys in save_actions.cleanups.items():
        unsupported = [
            key
            for key in formatter_keys
            if key not in FIELD_FORMATTERS and key not in handled_elsewhere
        ]
        warnings.extend(
            {
                "type": "unsupported_save_action_formatter",
                "field": field_name,
                "formatter": key,
                "message": f"saveActions formatter {key!r} on field {field_name!r} is not supported",
            }
            for key in unsupported
        )
        funcs = [FIELD_FORMATTERS[key] for key in formatter_keys if key in FIELD_FORMATTERS]
        if not funcs:
            continue
        for entry in lib.entries.values():
            value = entry.fields.get(field_name)
            if not value:
                continue
            new_value = value
            for func in funcs:
                new_value = func(new_value)
            if new_value != value and set_entry_field(entry, field_name, new_value):
                changed += 1
    return changed, warnings
