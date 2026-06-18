"""High-level bibliography normalization routine."""

from dataclasses import dataclass, field

from pynakes import authors as author_ops
from pynakes import doi as doi_ops
from pynakes import fields as field_ops
from pynakes import journals as journal_ops
from pynakes.editing import set_entry_field
from pynakes.model import BibLibrary

METADATA_PREFIX = "pynakes-normalize-"
TITLE_FIELDS = ("title", "booktitle", "maintitle", "subtitle")


@dataclass
class NormalizeOptions:
    protect_titles: bool | None = None
    title_fields: list[str] | None = None
    protected_terms: list[str] | None = None
    author_style: str | None = None
    journal_style: str | None = None
    journal_table: str | None = None
    ltwa_table: str | None = None
    normalize_dois: bool | None = None


@dataclass
class NormalizeResult:
    title_fields: dict[str, int] = field(default_factory=dict)
    authors: int = 0
    journals: int = 0
    dois: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def operations(self) -> dict[str, object]:
        return {
            "title_fields": dict(self.title_fields),
            "authors": self.authors,
            "journals": self.journals,
            "dois": self.dois,
        }


def _metadata_value(lib: BibLibrary, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for key, value in lib.jabref_metadata.items():
        if key.lower() in wanted:
            return value.rstrip(";").strip()
    return None


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


def _resolve_bool(lib: BibLibrary, option: bool | None, name: str, default: bool) -> bool:
    if option is not None:
        return option
    return _metadata_bool(
        _metadata_value(lib, f"{METADATA_PREFIX}{name}", f"normalize-{name}"),
        default,
    )


def _resolve_choice(
    lib: BibLibrary,
    option: str | None,
    name: str,
    allowed: set[str],
    default: str,
) -> str:
    if option is None or option == "metadata":
        value = _metadata_value(lib, f"{METADATA_PREFIX}{name}", f"normalize-{name}")
        resolved = value.lower() if value else default
    else:
        resolved = option.lower()
    if resolved not in allowed:
        raise ValueError(
            f"Invalid {name.replace('-', ' ')} {resolved!r}; expected one of: "
            f"{', '.join(sorted(allowed | {'metadata'}))}"
        )
    return resolved


def _resolve_title_fields(lib: BibLibrary, option: list[str] | None) -> list[str]:
    if option:
        return option
    metadata = _metadata_value(lib, f"{METADATA_PREFIX}title-fields", "normalize-title-fields")
    return _split_metadata_list(metadata) or list(TITLE_FIELDS)


def _resolve_terms(lib: BibLibrary, option: list[str] | None) -> list[str]:
    terms = list(option or [])
    terms.extend(
        _split_metadata_list(_metadata_value(lib, "pynakes-protected-terms", "protected-terms"))
    )
    return terms


def normalize_dois(lib: BibLibrary) -> tuple[int, list[dict[str, str]]]:
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


def normalize_library(lib: BibLibrary, options: NormalizeOptions | None = None) -> NormalizeResult:
    """Apply the standard daily-driver normalization routine in-place."""
    opts = options or NormalizeOptions()
    result = NormalizeResult()

    if _resolve_bool(lib, opts.protect_titles, "protect-titles", True):
        terms = _resolve_terms(lib, opts.protected_terms)
        for field in _resolve_title_fields(lib, opts.title_fields):
            changed = field_ops.protect_title_capitalization(lib, field=field, terms=terms)
            if changed:
                result.title_fields[field] = changed

    author_style = _resolve_choice(
        lib, opts.author_style, "author-style", author_ops.AUTHOR_STYLES, "jabref"
    )
    result.authors = author_ops.normalize_authors(lib, author_style)

    if _resolve_bool(lib, opts.normalize_dois, "dois", True):
        result.dois, doi_warnings = normalize_dois(lib)
        result.warnings.extend(doi_warnings)

    journal_style = _resolve_choice(
        lib, opts.journal_style, "journal-style", journal_ops.JOURNAL_STYLES, "abbreviated"
    )
    journal_table = opts.journal_table or _metadata_value(
        lib, "pynakes-journal-table", "journal-table"
    )
    ltwa_table = opts.ltwa_table or _metadata_value(lib, "pynakes-ltwa-table", "ltwa-table")
    journal_sources = journal_ops.load_sources(journal_table, ltwa_table)
    journal_result = journal_ops.normalize_journals(lib, journal_style, journal_sources)
    result.journals = journal_result.changed
    result.warnings.extend(
        {
            "type": "unknown_journal",
            "message": f"No journal abbreviation source resolved {title!r}",
            "journal": title,
        }
        for title in journal_result.unknown
    )

    return result
