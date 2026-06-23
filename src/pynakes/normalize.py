"""High-level bibliography normalization routine."""

from dataclasses import dataclass, field

from pynakes import authors as author_ops
from pynakes import doi as doi_ops
from pynakes import fields as field_ops
from pynakes import journals as journal_ops
from pynakes.editing import normalize_entry_field_names, set_entry_field, set_entry_type
from pynakes.formatters import FIELD_FORMATTERS
from pynakes.metadata import library_save_actions
from pynakes.model import BibFile

# JabRef saveActions formatter keys mapped to pynakes normalization concerns.
_NAME_FIELDS = ("author", "editor")
_DOI_FORMATTERS = ("clean_up_doi", "short_doi")

# Normalize settings live under the ``normalize-`` key prefix.
METADATA_PREFIX = "normalize-"
TITLE_FIELDS = ("title", "booktitle", "maintitle", "subtitle")


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
    save_action_fields: int = 0
    entry_types: int = 0
    field_names: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def operations(self) -> dict[str, object]:
        return {
            "title_fields": dict(self.title_fields),
            "authors": self.authors,
            "journals": self.journals,
            "dois": self.dois,
            "save_action_fields": self.save_action_fields,
            "entry_types": self.entry_types,
            "field_names": self.field_names,
        }


def _metadata_value(lib: BibFile, name: str) -> str | None:
    """Return the metadata value for ``name`` (case-insensitive), or ``None``."""
    lowered = {key.lower(): value for key, value in lib.metadata.items()}
    value = lowered.get(name.lower())
    if value is not None:
        return value.rstrip(";").strip()
    return None


def _normalize_setting(lib: BibFile, name: str) -> str | None:
    """Look up a normalize setting by its canonical ``normalize-`` key."""
    return _metadata_value(lib, f"{METADATA_PREFIX}{name}")


def _split_metadata_list(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace(";", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _metadata_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _resolve_bool(lib: BibFile, option: bool | None, name: str, default: bool) -> bool:
    if option is not None:
        return option
    return _metadata_bool(_normalize_setting(lib, name), default)


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
    metadata = _normalize_setting(lib, "title-fields")
    return _split_metadata_list(metadata) or list(TITLE_FIELDS)


def _resolve_terms(lib: BibFile, option: list[str] | None) -> list[str]:
    terms = list(option or [])
    terms.extend(_split_metadata_list(_metadata_value(lib, "protected-terms")))
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
            normalized = doi_ops.normalize_doi(value)
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


def normalize_library(lib: BibFile, options: NormalizeOptions | None = None) -> NormalizeResult:
    """Apply the standard daily-driver normalization routine in-place."""
    opts = options or NormalizeOptions()
    result = NormalizeResult()

    # JabRef's own saveActions, when present, drive the *defaults* for the
    # functionalities JabRef can express (author-name normalization, DOI
    # cleanup) — per the principle of using a native JabRef setting where one
    # exists. An explicit CLI option or a pynakes-meta key still overrides.
    save_actions = library_save_actions(lib)
    if save_actions is not None and save_actions.enabled:
        author_default = "jabref" if save_actions.has("normalize_names", _NAME_FIELDS) else "none"
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
    # metadata key). The standalone ``journals`` commands are unaffected.
    journal_style = _resolve_choice(
        lib, opts.journal_style, "journal-style", journal_ops.JOURNAL_STYLES, "none"
    )
    journal_table = opts.journal_table or _metadata_value(lib, "journal-table")
    ltwa_table = opts.ltwa_table or _metadata_value(lib, "ltwa-table")
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

    if _resolve_bool(lib, opts.identifier_case, "identifier-case", True):
        result.entry_types, result.field_names = normalize_identifier_case(lib)

    return result


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
