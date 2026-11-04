"""Discoverable metadata settings, joined to the schema and live CLI options."""

from pynakes.canonical import CanonicalLayout
from pynakes.fields import TITLE_FIELDS
from pynakes.metadata.schema import (
    DEPRECATED_METADATA_KEYS,
    PYNAKES_EXACT_KEYS,
    PYNAKES_PREFIX_KEYS,
    metadata_value_choices,
)
from pynakes.normalize import ENCODING_FIELDS

# Meaning, default when absent, accepted format, overriding command/flag.
# None means unset, not an unknown default. Conditional defaults are explicit.
_DETAILS: dict[str, tuple[str, object, str, str | None]] = {
    "normalize-proper-nouns": (
        "Protect internal capitalized names in sentence-case titles.",
        False,
        "Boolean",
        "normalize --proper-nouns",
    ),
    "dialect": (
        "Bibliography dialect.",
        "bibtex (init creates biblatex)",
        "choice",
        "init --dialect",
    ),
    "fields-encoding": (
        "Legacy fields encode target; normalize does not read it.",
        None,
        "choice",
        "fields encode --to",
    ),
    "sort-order": (
        "Entry ordering for normalize and new references.",
        "original",
        "field[:asc|desc],... or original/none",
        "normalize --sort-by",
    ),
    "key-pattern": (
        "Default citation-key pattern.",
        "[auth][year][veryshorttitle]",
        "JabRef citation-key pattern",
        "init --key-pattern",
    ),
    "import-key-source": (
        "Source of an imported citation key.",
        "generated",
        "choice",
        "ref import --key-source",
    ),
    "normalize-protect-titles": (
        "Brace-protect capitalization-sensitive title tokens.",
        True,
        "Boolean",
        "normalize --title-protection",
    ),
    "normalize-title-fields": (
        "Title fields to protect.",
        list(TITLE_FIELDS),
        "field list",
        "normalize --title-field",
    ),
    "normalize-protected-terms": (
        "Additional case-sensitive terms to protect.",
        [],
        "term list",
        "normalize --term",
    ),
    "normalize-drop-fields": (
        "Fields removed during normalization.",
        [],
        "field list",
        "normalize --drop-field",
    ),
    "normalize-author-style": (
        "Name-list normalization style.",
        "jabref; follows enabled JabRef saveActions when present",
        "jabref, conservative, bibtex, biblatex, none",
        "normalize --author-style",
    ),
    "normalize-journal-style": (
        "Journal name style.",
        "none",
        "choice",
        "normalize --journal-style",
    ),
    "normalize-journal-source": (
        "Base journal mapping source.",
        "jabref",
        "choice",
        "normalize --journal-source",
    ),
    "normalize-journal-table": (
        "Additional exact journal mappings.",
        None,
        "CSV/TSV path relative to bibliography",
        "normalize --journal-table",
    ),
    "normalize-ltwa-table": (
        "Journal word abbreviation mappings.",
        None,
        "CSV/TSV path relative to bibliography",
        "normalize --ltwa-table",
    ),
    "normalize-encoding": (
        "Prose-field character encoding conversion.",
        "off",
        "choice",
        "normalize --encoding",
    ),
    "normalize-encoding-fields": (
        "Fields converted by the encoding step.",
        list(ENCODING_FIELDS),
        "field list",
        "normalize --encoding-field",
    ),
    "normalize-dois": (
        "Strip DOI prefixes and labels.",
        "true; follows enabled JabRef saveActions when present",
        "Boolean",
        "normalize --doi-normalization",
    ),
    "normalize-pages": (
        "Normalize page ranges.",
        "true; defers to JabRef normalize_page_numbers when configured",
        "Boolean",
        "normalize --pages",
    ),
    "normalize-months": (
        "Convert month names to BibTeX month macros.",
        True,
        "Boolean",
        "normalize --months",
    ),
    "normalize-invisible-characters": (
        "Remove invisible characters from field values.",
        True,
        "Boolean",
        "normalize --invisible-characters",
    ),
    "normalize-keys": ("Regenerate citation keys.", False, "Boolean", "normalize --key-generation"),
    "normalize-identifier-case": (
        "Lowercase entry types and field names.",
        True,
        "Boolean",
        "normalize --identifier-case",
    ),
    "normalize-format-metadata": (
        "Consolidate metadata layout.",
        True,
        "Boolean",
        "normalize --metadata-formatting",
    ),
    "pinax-files-dir": (
        "Materials directory inside the bibliography directory.",
        None,
        "relative path inside bibliography directory",
        None,
    ),
    "pinax-fetch-policy": (
        "Material kinds requested by asset fetch.",
        "bestpdf",
        "list: preprint,published,source,supplement,bestpdf",
        "asset fetch --material",
    ),
    "pinax-fetch-access": (
        "Access mode for publisher copies.",
        "open",
        "choice",
        "asset fetch --access",
    ),
    "pinax-discover-arxiv": (
        "Look up missing arXiv identifiers during an authorized fetch.",
        False,
        "Boolean",
        "asset fetch --discover",
    ),
    "tex-sources": (
        "Associated TeX source paths.",
        [],
        "file/directory list relative to bibliography",
        None,
    ),
    "biblink-parents": (
        "Parent bibliography declarations.",
        [],
        "PATH constraint=field-subset|key-subset flow=down|up|both|none; ...",
        None,
    ),
    "biblink-children": (
        "Child bibliography declarations.",
        [],
        "PATH constraint=field-subset|key-subset flow=down|up|both|none; ...",
        None,
    ),
    "lint-required-fields": ("Additional required fields for every entry.", [], "field list", None),
    "lint-ignore": (
        "Suppress named lint findings or categories.",
        [],
        "finding/category list",
        "lint --ignore",
    ),
    "lint-severity": ("Minimum reported lint severity.", "info", "choice", "lint --severity"),
    "verify-published": (
        "Check for published preprint versions with online verification.",
        False,
        "Boolean",
        "verify --published",
    ),
    "enrich-published": (
        "Promote published preprint versions with online enrichment.",
        False,
        "Boolean",
        "enrich --published",
    ),
    "group-tree": ("Library group hierarchy.", None, "pipe-delimited group nodes", None),
    "groups-separator": (
        "Delimiter used for group memberships.",
        "auto",
        "choice",
        "--groups-separator",
    ),
    "scrub-fields": (
        "Additional private fields to remove.",
        [],
        "field name/glob list; extends built-in private fields",
        "scrub --drop-field",
    ),
    "scrub-keep-fields": (
        "Fields retained by scrub.",
        [],
        "field name/glob list; * keeps every field",
        "scrub --keep-field",
    ),
    "scrub-comments": (
        "Remove free comment blocks in public copies.",
        True,
        "Boolean",
        "scrub --keep-comments",
    ),
    "scrub-metadata": (
        "Remove metadata blocks in public copies.",
        True,
        "Boolean",
        "scrub --keep-metadata",
    ),
    "coauthors-max-authors": (
        "Maximum authors per entry for network links; zero is unlimited.",
        100,
        "non-negative integer",
        "coauthors --max-authors",
    ),
    "normalize-": (
        "Reserved normalization-setting family; only documented members have behavior.",
        None,
        "setting-specific value",
        None,
    ),
    "lint-required-fields-": (
        "Additional required fields for the suffixed entry type.",
        [],
        "field list",
        None,
    ),
    "key-pattern-": (
        "Citation-key pattern for the suffixed entry type.",
        "key-pattern",
        "JabRef citation-key pattern",
        None,
    ),
    "query-": ("Saved selector named by the suffix.", None, "single-line --where expression", None),
}

_FORMAT_DETAILS = {
    "indent": ("Indentation inside entries.", "indent", "positive integer or tab"),
    "alignment": ("Field/value alignment.", "alignment", "choice"),
    "trailing-comma": ("Include a comma after the final field.", "trailing_comma", "Boolean"),
    "blank-lines": ("Separate entries with blank lines.", "blank_line_entries", "Boolean"),
    "field-order": ("Order of fields within an entry.", "field_order", "choice"),
    "block-order": ("Top-level block layout.", "block_order", "choice"),
    "wrap-values": ("Value wrapping policy.", "wrap_values", "choice"),
    "line-width": ("Target width for value wrapping.", "line_width", "integer >= 20"),
    "entry-type-case": ("Capitalization of entry type identifiers.", "entry_type_case", "choice"),
}


def settings_catalogue() -> dict[str, dict]:
    """Describe every exact key and prefix; finite choices come from validation.

    Defaults describe an unconfigured library; JabRef aliases/saveActions can
    supply fallback values. Prefix rows name a family rather than a literal key.
    CLI options may extend list settings (as their help states).
    """
    details = dict(_DETAILS)
    layout = CanonicalLayout()
    for suffix, (meaning, attribute, value_format) in _FORMAT_DETAILS.items():
        default = getattr(layout, attribute)
        if suffix == "indent":
            default = len(default)
        details[f"format-{suffix}"] = (meaning, default, value_format, f"format --{suffix}")
    choices = metadata_value_choices()
    result = {}
    for key, category in {**PYNAKES_EXACT_KEYS, **PYNAKES_PREFIX_KEYS}.items():
        meaning, default, value_format, override = details[key]
        result[key] = {
            "category": category,
            "meaning": meaning,
            "default": default,
            "format": value_format,
            "choices": choices.get(key, ["false", "true"] if value_format == "Boolean" else []),
            "cli_override": override,
            "prefix": key in PYNAKES_PREFIX_KEYS,
        }
        if key in DEPRECATED_METADATA_KEYS:
            result[key]["deprecated"] = DEPRECATED_METADATA_KEYS[key]
    return dict(sorted(result.items()))
