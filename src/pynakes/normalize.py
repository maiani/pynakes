"""High-level bibliography normalization routine."""

from collections.abc import Collection
from dataclasses import dataclass, field

from pynakes import authors as author_ops
from pynakes import fields as field_ops
from pynakes import journals as journal_ops
from pynakes._calendar import MONTH_ABBR_TO_NAME, MONTH_NUM_TO_ABBR, month_name_to_int
from pynakes._identifiers import normalize_doi
from pynakes._invisible import remove_invisible
from pynakes._markup import TITLE_LIKE_FIELDS
from pynakes._normalize_sort import _resolve_sort_criteria, sort_entries
from pynakes._normalize_steps import (
    NOT_IN_ONLY,
    WHOLE_FILE,
    WHOLE_FILE_STEPS,
    entry_view,
    step_name,
)
from pynakes.authors import NAME_FIELDS
from pynakes.canonical import resolve_entry_type_case
from pynakes.editing import (
    normalize_entry_field_names,
    raw_field_value,
    set_entry_field,
    set_entry_field_expression,
    set_entry_type,
)
from pynakes.fields import TITLE_FIELDS
from pynakes.formatters import FIELD_FORMATTERS, normalize_page_numbers
from pynakes.keys import regenerate_keys as _regenerate_keys
from pynakes.keys import regenerate_selected_keys
from pynakes.metadata import metadata_bool, metadata_list, metadata_value
from pynakes.metadata.jabref import (
    library_save_actions,
    metadata_category,
    native_key_for_jabref,
    native_value_for_jabref,
)
from pynakes.model import BibFile, MetadataBlock

# JabRef saveActions formatter keys mapped to pynakes normalization concerns.
# ``normalize_names`` is handled via the author-style path.
_DOI_SAVE_ACTION = "clean_up_doi"
_PAGES_SAVE_ACTION = "normalize_page_numbers"
_HTML_SAVE_ACTIONS = ("html_to_latex", "html_to_unicode")

# Normalize settings live under the ``normalize-`` key prefix.
METADATA_PREFIX = "normalize-"


def _month_name_to_macro(token: str) -> str | None:
    """Map a month name to its three-letter BibTeX macro (``jan``..``dec``), or ``None``.

    Handles full names (``June``), three-letter macros (``jun``), variant
    abbreviations (``Sept.``), and the nonstandard ``sept``.
    """
    cleaned = token.strip().rstrip(".")
    if cleaned.lower() == "sept":
        return "sep"
    num = month_name_to_int(cleaned)
    if num is None:
        return None
    return MONTH_NUM_TO_ABBR.get(f"{num:02d}")


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
    drop_fields: list[str] | None = None
    author_style: str | None = None
    journal_style: str | None = None
    journal_source: str | None = None
    journal_table: str | None = None
    ltwa_table: str | None = None
    normalize_dois: bool | None = None
    normalize_pages: bool | None = None
    normalize_months: bool | None = None
    remove_invisible: bool | None = None
    #: ``latex``, ``unicode`` or ``off``; ``None``/``metadata`` defers to the
    #: ``normalize-encoding`` setting, and the step is off when neither says.
    encoding: str | None = None
    encoding_fields: list[str] | None = None
    normalize_keys: bool | None = None
    identifier_case: bool | None = None
    format_metadata: bool | None = None
    # One-off sort override using JabRef field names; each token is
    # ``field`` or ``field:asc`` / ``field:desc``. ``["original"]`` (or
    # ``["none"]``) forces "keep current order", overriding ``saveOrderConfig``.
    sort_by: list[str] | None = None
    # Run only these steps (names from :data:`STEPS`); ``None`` runs them all.
    only: list[str] | None = None


@dataclass
class NormalizeResult:
    """Per-domain counts and non-fatal warnings from normalization.

    ``operations`` is the stable compact view used by callers that need a
    single structured summary without inspecting the individual fields.
    """

    title_fields: dict[str, int] = field(default_factory=dict)
    #: Entries whose title-like fields had provider markup converted to LaTeX.
    title_markup: int = 0
    dropped_fields: int = 0
    #: Entries whose field values had invisible characters removed.
    invisible_characters: int = 0
    #: Per field, the entries whose text was converted to LaTeX or Unicode.
    encoded_fields: dict[str, int] = field(default_factory=dict)
    authors: int = 0
    journals: int = 0
    dois: int = 0
    pages: int = 0
    months: int = 0
    save_action_fields: int = 0
    entry_types: int = 0
    field_names: int = 0
    keys: int = 0
    renamed_keys: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str | dict[str, str]] = field(default_factory=list)

    sort_entries_count: int = 0
    sort_criteria: list[tuple[str, bool]] = field(default_factory=list)

    #: Steps that did not run, mapped to why — so a caller can tell "ran and
    #: changed nothing" from "never ran". A count of ``0`` alone cannot say
    #: which, and the steps that are off by default (journal style, key
    #: regeneration) are exactly the ones a reader is most likely to
    #: misread as "checked, nothing to do".
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def operations(self) -> dict[str, object]:
        """Return the per-domain change counts as a single JSON-friendly dict."""
        return {
            "title_fields": dict(self.title_fields),
            "title_markup": self.title_markup,
            "dropped_fields": self.dropped_fields,
            "invisible_characters": self.invisible_characters,
            "encoded_fields": dict(self.encoded_fields),
            "authors": self.authors,
            "journals": self.journals,
            "dois": self.dois,
            "pages": self.pages,
            "months": self.months,
            "save_action_fields": self.save_action_fields,
            "entry_types": self.entry_types,
            "field_names": self.field_names,
            "keys": self.keys,
            "sorted_entries": self.sort_entries_count,
            "skipped": dict(self.skipped),
        }


#: Every step a library can turn off, mapped to the CLI invocation that turns
#: it on and the metadata key that configures it. A report's ``skipped`` reason
#: and the CLI's summary are both built from this, so a step cannot end up
#: described one way in the human output and another in the envelope.
SKIPPABLE_STEPS: dict[str, tuple[str, str]] = {
    "titles": ("--title-protection on", "normalize-protect-titles"),
    "authors": ("--author-style jabref", "normalize-author-style"),
    "journals": ("--journal-style abbreviated|full", "normalize-journal-style"),
    "dois": ("--doi-normalization on", "normalize-dois"),
    "pages": ("--pages on", "normalize-pages"),
    "months": ("--months on", "normalize-months"),
    "invisible_characters": ("--invisible-characters on", "normalize-invisible-characters"),
    "encoding": ("--encoding latex|unicode", "normalize-encoding"),
    "identifier_case": ("--identifier-case on", "normalize-identifier-case"),
    "keys": ("--key-generation on", "normalize-keys"),
}


def skipped_step_flag(step: str) -> str:
    """Return the bare CLI flag that turns ``step`` on, for a compact summary."""
    return SKIPPABLE_STEPS[step][0].split()[0]


def _record_skip(result: NormalizeResult, step: str, state: str) -> None:
    """Record that ``step`` did not run, and how to make it run.

    ``state`` says why in the library's own terms; the advice is appended from
    :data:`SKIPPABLE_STEPS` so every skipped step points somewhere actionable.
    """
    invocation, metadata_key = SKIPPABLE_STEPS[step]
    result.skipped[step] = f"{state}; set {invocation} or the {metadata_key} metadata key"


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


#: Fields of human-readable text the encoding step converts unless the
#: ``normalize-encoding-fields`` setting or ``--encoding-field`` names others.
#: Identifiers, links, and paths (``doi``, ``url``, ``file``, ``eprint``) are
#: never in it: converting them would change what they point to.
ENCODING_FIELDS: tuple[str, ...] = (
    "author",
    "editor",
    "title",
    "booktitle",
    "journal",
    "series",
    "publisher",
    "address",
    "institution",
    "organization",
    "school",
    "note",
    "abstract",
    "keywords",
)


def _resolve_encoding_fields(lib: BibFile, option: list[str] | None) -> list[str]:
    if option:
        return option
    return list(metadata_list(_normalize_setting(lib, "encoding-fields"))) or list(ENCODING_FIELDS)


def _resolve_title_fields(lib: BibFile, option: list[str] | None) -> list[str]:
    if option:
        return option
    meta = _normalize_setting(lib, "title-fields")
    return list(metadata_list(meta)) or list(TITLE_FIELDS)


def _resolve_terms(lib: BibFile, option: list[str] | None) -> list[str]:
    terms = list(option or [])
    terms.extend(metadata_list(metadata_value(lib, "normalize-protected-terms")))
    return terms


def _resolve_drop_fields(lib: BibFile, option: list[str] | None) -> list[str]:
    """Field names to strip from every entry: CLI-given plus the library's own list.

    Off by default (empty), like ``journal_style``: dropping a field is
    opinionated and not reversible, so it only runs for fields named
    explicitly, either via ``--drop-field`` or a persisted
    ``normalize-drop-fields`` metadata key (e.g. to always strip ``abstract``).
    """
    names = list(option or [])
    names.extend(metadata_list(metadata_value(lib, "normalize-drop-fields")))
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def resolve_format_metadata(lib: BibFile, option: bool | None) -> bool:
    """Resolve whether to consolidate metadata layout (default on).

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


def normalize_pages(lib: BibFile) -> int:
    """Rewrite page ranges to BibTeX's ``start--end``, returning the count changed.

    Crossref hands out ranges punctuated with a Unicode en-dash (``1052–1055``).
    It renders under UTF-8 + ``inputenc`` but breaks under 8-bit ``bibtex`` with
    some styles, and — being visually near-identical to a hyphen — it survives
    review and propagates. Delegates to the JabRef-compatible
    :func:`~pynakes.formatters.normalize_page_numbers`, which leaves anything
    that is not a simple range alone, so an article number or a
    ``7,41,73--97`` list is untouched.

    On by default, unlike journal-style conversion: ``--`` is the format's own
    convention for the same value, not an editorial preference.
    """
    count = 0
    for entry in lib.entries.values():
        value = entry.fields.get("pages")
        if not value:
            continue
        normalized = normalize_page_numbers(value)
        if normalized != value and set_entry_field(entry, "pages", normalized):
            count += 1
    return count


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
        source_name = source_value.strip().rstrip(".")
        macro = _month_name_to_macro(source_name)
        source_lower = source_name.lower()
        if macro is None or source_lower in declared:
            continue
        month_name = MONTH_ABBR_TO_NAME[macro]
        expression = macro if macro not in declared else f"{{{month_name}}}"
        if set_entry_field_expression(entry, "month", expression, month_name):
            changed += 1
    return changed


def normalize_library(
    lib: BibFile,
    options: NormalizeOptions | None = None,
    *,
    keys: Collection[str] | None = None,
) -> NormalizeResult:
    """Apply the configured normalization steps to the bibliography in-place.

    ``options.only`` runs just the named steps. ``keys`` limits the run to those
    citation keys; the whole-file steps in :data:`WHOLE_FILE_STEPS` then do not
    run, since sorting or consolidating a file is not something a few of its
    entries can do. Each step that did not run is recorded in ``skipped``.
    """
    opts = options or NormalizeOptions()
    result = NormalizeResult()
    only = None if opts.only is None else {step_name(step) for step in opts.only}

    def runs(step: str) -> bool:
        if only is not None and step not in only:
            result.skipped[step] = NOT_IN_ONLY
            return False
        if keys is not None and step in WHOLE_FILE_STEPS:
            result.skipped[step] = WHOLE_FILE
            return False
        return True

    selection = lib if keys is None else entry_view(lib, keys)

    # Adopt JabRef metadata as pynakes-native when the native equivalent is
    # absent. This ensures that a library created or maintained in JabRef gains
    # the corresponding pynakes-native keys silently — no explicit migration
    # step required. Synthetic blocks share the jabref block's raw/comment_index
    # so the post-normalize consolidation step can find and reposition them.
    for block in lib.metadata_blocks if runs("metadata") else ():
        if block.namespace != "jabref":
            continue
        native_key = native_key_for_jabref(block.key)
        if native_key is None:
            continue
        if metadata_value(lib, native_key) is not None:
            continue
        native_value = native_value_for_jabref(block.key, block.value)
        if not native_value:
            continue
        lib.pynakes_metadata_blocks.append(
            MetadataBlock(
                key=native_key,
                value=native_value,
                raw=block.raw,
                comment_index=block.comment_index,
                known=True,
                category=metadata_category(native_key),
                namespace="pynakes",
            )
        )
        result.warnings.append(f"Adopted JabRef {block.key} as pynakes-native {native_key}")

    # JabRef's own saveActions, when present, drive the *defaults* for the
    # functionalities JabRef can express (author-name normalization, DOI
    # cleanup) — per the principle of using a native JabRef setting where one
    # exists. An explicit CLI option or a pynakes-meta key still overrides.
    save_actions = library_save_actions(lib)
    if save_actions is not None and save_actions.enabled:
        author_default = "jabref" if save_actions.has("normalize_names", NAME_FIELDS) else "none"
        doi_default = save_actions.has(_DOI_SAVE_ACTION, ("doi",))
        # A file whose own saveActions already run ``normalize_page_numbers``
        # owns that step: the built-in pass would apply the identical formatter
        # first and leave the configured one nothing to do, which is double
        # work and a misleading ``save_action_fields`` count.
        pages_default = not save_actions.has(_PAGES_SAVE_ACTION, ("pages",))
    else:
        author_default, doi_default, pages_default = "jabref", True, True

    if runs("drop_fields"):
        for drop_field in _resolve_drop_fields(lib, opts.drop_fields):
            result.dropped_fields += field_ops.clear_field(selection, drop_field)

    # Characters that render as nothing (a stray byte-order mark, a zero-width
    # space) have no place in a field; lint names each one (invisible_character).
    if not runs("invisible_characters"):
        pass
    elif _resolve_bool(lib, opts.remove_invisible, "invisible-characters", True):
        result.invisible_characters = remove_invisible(selection)
    else:
        _record_skip(result, "invisible_characters", "invisible-character removal is off")

    # Before title protection, so the braces it adds are the ones a converted
    # value keeps. Off unless asked: which encoding a library wants is its own
    # choice, and the deprecated ``fields-encoding`` setting is not read here.
    if runs("encoding"):
        target = _resolve_choice(lib, opts.encoding, "encoding", {"latex", "unicode", "off"}, "off")
        if target == "off":
            _record_skip(result, "encoding", "text encoding conversion is off")
        else:
            for name in _resolve_encoding_fields(lib, opts.encoding_fields):
                encoded = field_ops.encode_field(selection, name, to=target)
                if encoded["changed_entries"]:
                    result.encoded_fields[name] = encoded["changed_entries"]
                result.warnings.extend(encoded["warnings"])

    titles_run = runs("titles")
    if titles_run:
        # Markup is never wanted in a title, so this runs whatever the
        # protection setting, and before protection so braces never land
        # between tags. A field the file's own JabRef saveActions convert from
        # HTML is left to them, as pages are.
        owned = (
            [name for name in TITLE_LIKE_FIELDS if save_actions.has(_HTML_SAVE_ACTIONS, (name,))]
            if save_actions is not None and save_actions.enabled
            else []
        )
        result.title_markup = field_ops.convert_title_markup(selection, skip_fields=owned)
    if not titles_run:
        pass
    elif _resolve_bool(lib, opts.protect_titles, "protect-titles", True):
        terms = _resolve_terms(lib, opts.protected_terms)
        for field in _resolve_title_fields(lib, opts.title_fields):
            changed = field_ops.protect_title_capitalization(selection, field=field, terms=terms)
            if changed:
                result.title_fields[field] = changed
    else:
        _record_skip(result, "titles", "title protection is off")

    if runs("authors"):
        author_style = _resolve_choice(
            lib, opts.author_style, "author-style", author_ops.AUTHOR_STYLES, author_default
        )
        result.authors = author_ops.normalize_authors(selection, author_style)
        if author_style == "none":
            _record_skip(result, "authors", "author style is 'none'")

    if not runs("dois"):
        pass
    elif _resolve_bool(lib, opts.normalize_dois, "dois", doi_default):
        result.dois, doi_warnings = normalize_dois(selection)
        result.warnings.extend(doi_warnings)
    else:
        _record_skip(result, "dois", "DOI normalization is off")

    if not runs("pages"):
        pass
    elif _resolve_bool(lib, opts.normalize_pages, "pages", pages_default):
        result.pages = normalize_pages(selection)
    elif not pages_default:
        result.skipped["pages"] = (
            "the library's own JabRef saveActions already run normalize_page_numbers "
            "on pages, so the built-in pass would have nothing left to do"
        )
    else:
        _record_skip(result, "pages", "page normalization is off")

    # Journal abbreviation/expansion is *off* by default: it is opinionated and
    # not reversible without the right table, so it runs only when a style is
    # configured explicitly (CLI ``--journal-style`` or a ``normalize-journal-style``
    # metadata key).
    if runs("journals"):
        journal_style = _resolve_choice(
            lib, opts.journal_style, "journal-style", journal_ops.JOURNAL_STYLES, "none"
        )
        journal_source = _resolve_choice(
            lib,
            opts.journal_source,
            "journal-source",
            journal_ops.JOURNAL_SOURCES,
            journal_ops.DEFAULT_JOURNAL_SOURCE,
        )
        journal_table = opts.journal_table or metadata_value(lib, "normalize-journal-table")
        ltwa_table = opts.ltwa_table or metadata_value(lib, "normalize-ltwa-table")
        # The bundled tables hold 66,000 rows; load them only for a style that
        # reads them, as lint does.
        journal_sources = (
            journal_ops.load_sources(journal_table, ltwa_table, journal_source)
            if journal_style != "none"
            else None
        )
        journal_result = journal_ops.normalize_journals(selection, journal_style, journal_sources)
        result.journals = journal_result.changed
        result.warnings.extend(journal_ops.unknown_journal_warnings(journal_result.unknown))
        if journal_style == "none":
            _record_skip(
                result,
                "journals",
                "no journal style is configured, so journal titles were left as they are",
            )

    # Apply the remaining JabRef saveActions field formatters (date/month/pages)
    # exactly where the file configures them. There is no pynakes-meta or CLI
    # equivalent: these run because JabRef's own saveActions ask for them.
    if save_actions is not None and save_actions.enabled and runs("save_actions"):
        result.save_action_fields, formatter_warnings = _apply_save_action_formatters(
            selection, save_actions
        )
        result.warnings.extend(formatter_warnings)

    # This syntax-specific pass repairs bare full month names and canonicalizes
    # predefined macro spelling without changing literals or custom strings.
    if not runs("months"):
        pass
    elif _resolve_bool(lib, opts.normalize_months, "months", True):
        result.months = normalize_month_macros(selection)
    else:
        _record_skip(result, "months", "month normalization is off")

    if not runs("identifier_case"):
        pass
    elif _resolve_bool(lib, opts.identifier_case, "identifier-case", True):
        result.entry_types, result.field_names = normalize_identifier_case(
            selection, entry_types=resolve_entry_type_case(lib) == "lower"
        )
    else:
        _record_skip(result, "identifier_case", "identifier-case normalization is off")

    if runs("sort"):
        criteria = _resolve_sort_criteria(lib, opts.sort_by)
        if criteria:
            sort_entries(lib, criteria)
            result.sort_criteria = criteria
            result.sort_entries_count = len(lib.entries)

    if not runs("keys"):
        pass
    elif _resolve_bool(lib, opts.normalize_keys, "keys", False):
        if keys is None:
            renames = _regenerate_keys(lib)
        else:
            renames, duplicated = regenerate_selected_keys(lib, keys)
            result.warnings.extend(
                f"Left duplicated key {key!r} as it is; repair duplicates first"
                for key in duplicated
            )
        result.keys = len(renames)
        result.renamed_keys = renames
        if renames:
            details = "; ".join(f"{old} -> {new}" for old, new in renames[:5])
            if len(renames) > 5:
                details += f" (and {len(renames) - 5} more)"
            result.warnings.append(f"Regenerated {len(renames)} key(s): {details}")
    else:
        _record_skip(result, "keys", "citation keys are never regenerated unless asked")

    return result


def normalize_identifier_case(lib: BibFile, *, entry_types: bool = True) -> tuple[int, int]:
    """Lowercase entry types and field names while preserving entry layout.

    ``entry_types=False`` leaves each type's spelling alone, as a library whose
    ``format-entry-type-case`` is ``preserve`` asks; field names are still
    lowercased. Returns the counts of recased types and field names.
    """
    recased_types = 0
    field_names = 0
    for entry in lib.entries.values():
        if entry_types and set_entry_type(entry, entry.type.lower()):
            recased_types += 1
        field_names += normalize_entry_field_names(entry)
    return recased_types, field_names


def _apply_save_action_formatters(lib: BibFile, save_actions) -> tuple[int, list[dict[str, str]]]:
    """Apply supported saveActions field formatters per the file's field map."""
    changed = 0
    warnings: list[dict[str, str]] = []
    handled_elsewhere = {"normalize_names", _DOI_SAVE_ACTION}
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
