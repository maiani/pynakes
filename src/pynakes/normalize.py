"""High-level bibliography normalization routine."""

from dataclasses import dataclass, field

from pynakes import authors as author_ops
from pynakes import fields as field_ops
from pynakes import journals as journal_ops
from pynakes._calendar import MONTH_ABBR_TO_NAME, MONTH_NUM_TO_ABBR, month_name_to_int
from pynakes._identifiers import normalize_doi
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
from pynakes.metadata import metadata_bool, metadata_list, metadata_value
from pynakes.metadata.jabref import (
    SAVE_ORDER_KEY_FIELDS,
    library_save_actions,
    library_sort_order,
    metadata_category,
    native_key_for_jabref,
    native_value_for_jabref,
)
from pynakes.model import BibEntry, BibFile, MetadataBlock

# JabRef saveActions formatter keys mapped to pynakes normalization concerns.
# ``normalize_names`` is handled via the author-style path.
_DOI_SAVE_ACTION = "clean_up_doi"
_PAGES_SAVE_ACTION = "normalize_page_numbers"

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
    normalize_keys: bool | None = None
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
    dropped_fields: int = 0
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
    warnings: list[dict[str, str]] = field(default_factory=list)

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
            "dropped_fields": self.dropped_fields,
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


def normalize_library(lib: BibFile, options: NormalizeOptions | None = None) -> NormalizeResult:
    """Apply the configured normalization steps to the bibliography in-place."""
    opts = options or NormalizeOptions()
    result = NormalizeResult()

    # Adopt JabRef metadata as pynakes-native when the native equivalent is
    # absent. This ensures that a library created or maintained in JabRef gains
    # the corresponding pynakes-native keys silently — no explicit migration
    # step required. Synthetic blocks share the jabref block's raw/comment_index
    # so the post-normalize consolidation step can find and reposition them.
    for block in lib.metadata_blocks:
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

    for drop_field in _resolve_drop_fields(lib, opts.drop_fields):
        result.dropped_fields += field_ops.clear_field(lib, drop_field)

    if _resolve_bool(lib, opts.protect_titles, "protect-titles", True):
        terms = _resolve_terms(lib, opts.protected_terms)
        for field in _resolve_title_fields(lib, opts.title_fields):
            changed = field_ops.protect_title_capitalization(lib, field=field, terms=terms)
            if changed:
                result.title_fields[field] = changed
    else:
        _record_skip(result, "titles", "title protection is off")

    author_style = _resolve_choice(
        lib, opts.author_style, "author-style", author_ops.AUTHOR_STYLES, author_default
    )
    result.authors = author_ops.normalize_authors(lib, author_style)
    if author_style == "none":
        _record_skip(result, "authors", "author style is 'none'")

    if _resolve_bool(lib, opts.normalize_dois, "dois", doi_default):
        result.dois, doi_warnings = normalize_dois(lib)
        result.warnings.extend(doi_warnings)
    else:
        _record_skip(result, "dois", "DOI normalization is off")

    if _resolve_bool(lib, opts.normalize_pages, "pages", pages_default):
        result.pages = normalize_pages(lib)
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
    journal_sources = journal_ops.load_sources(journal_table, ltwa_table, journal_source)
    journal_result = journal_ops.normalize_journals(lib, journal_style, journal_sources)
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
    if save_actions is not None and save_actions.enabled:
        result.save_action_fields, formatter_warnings = _apply_save_action_formatters(
            lib, save_actions
        )
        result.warnings.extend(formatter_warnings)

    # This syntax-specific pass repairs bare full month names and canonicalizes
    # predefined macro spelling without changing literals or custom strings.
    result.months = normalize_month_macros(lib)

    if _resolve_bool(lib, opts.identifier_case, "identifier-case", True):
        result.entry_types, result.field_names = normalize_identifier_case(
            lib, entry_types=resolve_entry_type_case(lib) == "lower"
        )
    else:
        _record_skip(result, "identifier_case", "identifier-case normalization is off")

    criteria = _resolve_sort_criteria(lib, opts.sort_by)
    if criteria:
        sort_entries(lib, criteria)
        result.sort_criteria = criteria
        result.sort_entries_count = len(lib.entries)

    if _resolve_bool(lib, opts.normalize_keys, "keys", False):
        renames = _regenerate_keys(lib)
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


def _resolve_sort_criteria(lib: BibFile, sort_by: list[str] | None) -> list[tuple[str, bool]]:
    """Resolve the entry sort order.

    An explicit CLI ``sort_by`` wins: each token is ``field`` or
    ``field:asc``/``field:desc`` (the JabRef field name; ``key`` is accepted for
    the citation key). A lone ``original`` or ``none`` token means "keep current
    order". With no CLI override, :func:`~pynakes.metadata.jabref.library_sort_order`
    drives the order: pynakes' native ``sort-order`` key first, else JabRef's
    ``saveOrderConfig`` (only when its type is ``specified``, matching JabRef,
    which leaves entries untouched for ``original``/``table``).
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

    return list(library_sort_order(lib) or [])


def sort_entries(lib: BibFile, criteria: list[tuple[str, bool]]) -> int:
    """Reorder ``lib`` entries in-place by the given criteria.

    ``criteria`` is an ordered ``(field, descending)`` list; the first is the
    primary sort. Implemented as successive stable sorts from the least- to the
    most-significant criterion, so per-criterion ascending/descending is honored
    independently. After sorting, crossref parents are placed after all of their
    children (a BibTeX 0.99 processing requirement). Returns the number of entries.
    """
    for field_name, descending in reversed(criteria):
        lib.entries.reorder(
            lambda entry, f=field_name: _entry_sort_key(entry, f),
            reverse=descending,
        )
    _sink_crossref_parents(lib)
    return len(lib.entries)


def _sink_crossref_parents(lib: BibFile) -> None:
    """Place entries that are crossref parents after all of their children.

    BibTeX 0.99 requires a cross-referenced entry to occur later in the database
    than every entry that cross-references it. Duplicate parent keys resolve to
    their first occurrence, matching the rest of pynakes' duplicate-key behavior.
    """
    original = list(lib.entries.values())
    first_by_key: dict[str, BibEntry] = {}
    for entry in original:
        first_by_key.setdefault(entry.key, entry)

    children_by_parent: dict[int, list[BibEntry]] = {}
    parent_by_child: dict[int, BibEntry] = {}
    for entry in original:
        parent_key = entry.fields.get("crossref", "").strip()
        parent = first_by_key.get(parent_key)
        if parent is not None and parent is not entry:
            children_by_parent.setdefault(id(parent), []).append(entry)
            parent_by_child[id(entry)] = parent

    # Crossref cycles are malformed, but normalization must still be idempotent.
    # Collapse each cycle into one stable component whose members retain their
    # incoming order; ordinary children of cycle members are still emitted first.
    cycle_components: list[list[BibEntry]] = []
    cycle_by_entry: dict[int, int] = {}
    processed: set[int] = set()
    for start in original:
        path: list[BibEntry] = []
        positions: dict[int, int] = {}
        current = start
        while id(current) not in processed and id(current) not in positions:
            positions[id(current)] = len(path)
            path.append(current)
            parent = parent_by_child.get(id(current))
            if parent is None:
                break
            current = parent
        if id(current) in positions:
            members = path[positions[id(current)] :]
            member_ids = {id(member) for member in members}
            members = [entry for entry in original if id(entry) in member_ids]
            component_index = len(cycle_components)
            cycle_components.append(members)
            for member in members:
                cycle_by_entry[id(member)] = component_index
        processed.update(id(entry) for entry in path)

    ordered: list[BibEntry] = []
    emitted: set[int] = set()
    visiting: set[int] = set()
    emitted_cycles: set[int] = set()
    visiting_cycles: set[int] = set()

    def emit(entry: BibEntry) -> None:
        identity = id(entry)
        if identity in emitted:
            return
        cycle_index = cycle_by_entry.get(identity)
        if cycle_index is not None:
            if cycle_index in emitted_cycles or cycle_index in visiting_cycles:
                return
            visiting_cycles.add(cycle_index)
            members = cycle_components[cycle_index]
            member_ids = {id(member) for member in members}
            for member in members:
                for child in children_by_parent.get(id(member), []):
                    if id(child) not in member_ids:
                        emit(child)
            visiting_cycles.remove(cycle_index)
            for member in members:
                if id(member) not in emitted:
                    ordered.append(member)
                    emitted.add(id(member))
            emitted_cycles.add(cycle_index)
            return
        if identity in visiting:  # malformed crossref cycle: retain stable order
            return
        visiting.add(identity)
        for child in children_by_parent.get(identity, []):
            emit(child)
        visiting.remove(identity)
        if identity not in emitted:
            ordered.append(entry)
            emitted.add(identity)

    for entry in original:
        emit(entry)
    lib.entries.set_order(ordered)


def _entry_sort_key(entry: BibEntry, field_name: str) -> tuple:
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
