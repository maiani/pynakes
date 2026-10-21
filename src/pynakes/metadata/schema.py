"""pynakes' canonical metadata schema — pynakes' own keys, JabRef-unaware.

This is the pure "what pynakes itself understands" layer: which keys pynakes
owns natively, what domain category each belongs to, and how to read the
native value for concepts that also have a JabRef counterpart (``dialect``,
``sort-order``). It imports only :mod:`pynakes.metadata.core` and never
:mod:`pynakes.metadata.jabref` — resolving a native value against a JabRef
fallback, or deciding which namespace a key routes to, is compatibility
policy, not schema, and belongs on the JabRef side instead.
"""

from typing import Literal

from pynakes._lint_issue import unknown_ignore_names
from pynakes._text_utils import strip_meta_terminator
from pynakes.metadata.core import metadata_list, metadata_value
from pynakes.model import BibFile

MetadataCategory = Literal[
    "library",
    "save",
    "files",
    "groups",
    "selectors",
    "citation-key",
    "normalization",
    "formatting",
    "lint",
    "integrity",
    "usage",
    "pinax",
    "scrub",
    "queries",
    "analysis",
    "unknown",
]

CATEGORY_LIBRARY: MetadataCategory = "library"
CATEGORY_SAVE: MetadataCategory = "save"
CATEGORY_FILES: MetadataCategory = "files"
CATEGORY_GROUPS: MetadataCategory = "groups"
CATEGORY_SELECTORS: MetadataCategory = "selectors"
CATEGORY_CITATION_KEY: MetadataCategory = "citation-key"
CATEGORY_NORMALIZATION: MetadataCategory = "normalization"
CATEGORY_FORMATTING: MetadataCategory = "formatting"
CATEGORY_LINT: MetadataCategory = "lint"
CATEGORY_INTEGRITY: MetadataCategory = "integrity"
CATEGORY_USAGE: MetadataCategory = "usage"
CATEGORY_PINAX: MetadataCategory = "pinax"
CATEGORY_SCRUB: MetadataCategory = "scrub"
CATEGORY_QUERIES: MetadataCategory = "queries"
CATEGORY_ANALYSIS: MetadataCategory = "analysis"
CATEGORY_UNKNOWN: MetadataCategory = "unknown"

#: Former ``pynakes-meta`` key names, mapped to the key that replaced them. They
#: are no longer read; ``lint`` names the replacement so the fix is one rename.
RENAMED_METADATA_KEYS: dict[str, str] = {
    "files-dir": "pinax-files-dir",
    "fetch-policy": "pinax-fetch-policy",
    "protected-terms": "normalize-protected-terms",
    "journal-table": "normalize-journal-table",
    "ltwa-table": "normalize-ltwa-table",
}

# pynakes-owned metadata keys. These live in ``pynakes-meta`` by default because
# they have no JabRef equivalent or deliberately extend JabRef behavior.
PYNAKES_EXACT_KEYS: dict[str, MetadataCategory] = {
    # Native library dialect, aliasing JabRef's ``databaseType``.
    "dialect": CATEGORY_LIBRARY,
    "fields-encoding": CATEGORY_NORMALIZATION,
    # Native entry sort order, aliasing JabRef's ``saveOrderConfig``.
    "sort-order": CATEGORY_SAVE,
    # Native default citation-key pattern, aliasing JabRef's ``keypatterndefault``.
    "key-pattern": CATEGORY_CITATION_KEY,
    # Where `ref import` takes a new entry's key from: generated or provider.
    "import-key-source": CATEGORY_CITATION_KEY,
    "normalize-protect-titles": CATEGORY_NORMALIZATION,
    "normalize-title-fields": CATEGORY_NORMALIZATION,
    "normalize-author-style": CATEGORY_NORMALIZATION,
    "normalize-journal-style": CATEGORY_NORMALIZATION,
    "normalize-dois": CATEGORY_NORMALIZATION,
    "normalize-pages": CATEGORY_NORMALIZATION,
    "normalize-months": CATEGORY_NORMALIZATION,
    "normalize-invisible-characters": CATEGORY_NORMALIZATION,
    "normalize-keys": CATEGORY_NORMALIZATION,
    "normalize-identifier-case": CATEGORY_NORMALIZATION,
    "normalize-format-metadata": CATEGORY_NORMALIZATION,
    "normalize-protected-terms": CATEGORY_NORMALIZATION,
    "normalize-drop-fields": CATEGORY_NORMALIZATION,
    "normalize-journal-source": CATEGORY_NORMALIZATION,
    "normalize-journal-table": CATEGORY_NORMALIZATION,
    "normalize-ltwa-table": CATEGORY_NORMALIZATION,
    "format-indent": CATEGORY_FORMATTING,
    "format-alignment": CATEGORY_FORMATTING,
    "format-trailing-comma": CATEGORY_FORMATTING,
    "format-blank-lines": CATEGORY_FORMATTING,
    "format-field-order": CATEGORY_FORMATTING,
    "format-entry-order": CATEGORY_FORMATTING,
    "format-block-order": CATEGORY_FORMATTING,
    "format-wrap-values": CATEGORY_FORMATTING,
    "format-line-width": CATEGORY_FORMATTING,
    "format-entry-type-case": CATEGORY_FORMATTING,
    "pinax-files-dir": CATEGORY_PINAX,
    "pinax-fetch-policy": CATEGORY_PINAX,
    # How `asset fetch` reaches publisher copies, and whether it looks up
    # missing arXiv ids; both only shape a run the user already started.
    "pinax-fetch-access": CATEGORY_PINAX,
    "pinax-discover-arxiv": CATEGORY_PINAX,
    # Linked LaTeX sources that cite this library; consulted by the citation-key
    # commands so .tex edits stay consistent without re-specifying the files.
    "tex-sources": CATEGORY_USAGE,
    # Lint profile settings. ``lint-required-fields`` applies to every entry;
    # the entry-type suffix form adds requirements for one type.
    "lint-required-fields": CATEGORY_LINT,
    # Finding types and categories the `lint` command leaves out of its report.
    "lint-ignore": CATEGORY_LINT,
    # Whether verify / enrich also handle published versions of preprints
    # (the lookups still need --online).
    "verify-published": CATEGORY_INTEGRITY,
    "enrich-published": CATEGORY_INTEGRITY,
    # The least severe finding `lint` reports by default.
    "lint-severity": CATEGORY_LINT,
    # Native group tree (hierarchy of StaticGroup nodes).
    "group-tree": CATEGORY_GROUPS,
    "groups-separator": CATEGORY_GROUPS,
    # What `scrub` removes when preparing a public copy of this library.
    "scrub-fields": CATEGORY_SCRUB,
    "scrub-keep-fields": CATEGORY_SCRUB,
    "scrub-comments": CATEGORY_SCRUB,
    "scrub-metadata": CATEGORY_SCRUB,
    # Entries listing more authors than this are not linked into the co-author
    # network (`coauthors`, `analyze`'s coauthors section); 0 links every entry.
    "coauthors-max-authors": CATEGORY_ANALYSIS,
}

PYNAKES_PREFIX_KEYS: dict[str, MetadataCategory] = {
    # pynakes' normalization settings live under the canonical ``normalize-`` prefix.
    "normalize-": CATEGORY_NORMALIZATION,
    "lint-required-fields-": CATEGORY_LINT,
    # Per-entry-type key patterns, aliasing JabRef's ``keypattern_<type>``.
    "key-pattern-": CATEGORY_CITATION_KEY,
    # Saved selector queries, one key per name, run as the `query "name"` predicate.
    "query-": CATEGORY_QUERIES,
}

#: Key prefix of a saved query: ``query-<name>: <selector expression>``.
SAVED_QUERY_PREFIX = "query-"


_VALID_DIALECTS = {"bibtex", "biblatex"}
VALID_FETCH_POLICIES = {"preprint", "published", "source", "supplement", "bestpdf"}
# Matches ``pynakes.journals.JOURNAL_STYLES`` (kept in sync by the lint profile
# and normalize sharing the same persisted enum).
_VALID_JOURNAL_STYLES = {"none", "abbreviated", "full"}
# Matches ``pynakes.journals.JOURNAL_SOURCES``.
_VALID_JOURNAL_SOURCES = {"jabref", "none"}
_FORMAT_CHOICES = {
    "format-alignment": {"compact", "equals"},
    "format-field-order": {"preferred", "preserve", "alphabetical"},
    "format-entry-order": {"preserve", "key", "profile"},
    "format-block-order": {"preserve", "canonical"},
    "format-wrap-values": {"off", "stable", "canonical"},
    "format-entry-type-case": {"lower", "preserve"},
}


#: Choice-valued settings outside the ``format-*`` family: the value a command's
#: flag of the same meaning accepts.
_SETTING_CHOICES: dict[str, set[str]] = {
    "fields-encoding": {"latex", "unicode"},
    "groups-separator": {"auto", "comma", "semicolon"},
    "pinax-fetch-access": {"open", "institutional"},
    "import-key-source": {"generated", "provider"},
    "lint-severity": {"error", "warning", "info"},
}

_BOOLEAN_KEYS = {
    "pinax-discover-arxiv",
    "verify-published",
    "enrich-published",
    "format-trailing-comma",
    "format-blank-lines",
    "scrub-comments",
    "scrub-metadata",
    "normalize-months",
    "normalize-invisible-characters",
}
_BOOLEAN_VALUES = {"true", "false", "yes", "no", "on", "off", "1", "0"}


def metadata_value_choices() -> dict[str, list[str]]:
    """Return finite choices for single-valued metadata keys, keyed case-insensitively.

    Choices share the validator's registries and apply in either namespace.
    Standard Boolean metadata values are ``true``/``false``; validation also
    accepts nonstandard compatibility aliases.
    Lists (such as fetch policies), numbers, and free-form values are omitted.
    Fresh, sorted lists let clients offer choices without owning the schema.
    Existing spelling and terminators remain the caller's original value.
    """
    choices = {
        "dialect": _VALID_DIALECTS,
        "databasetype": _VALID_DIALECTS,
        "normalize-journal-style": _VALID_JOURNAL_STYLES,
        "normalize-journal-source": _VALID_JOURNAL_SOURCES,
        **_FORMAT_CHOICES,
        **_SETTING_CHOICES,
        **{key: {"true", "false"} for key in _BOOLEAN_KEYS},
    }
    return {key: sorted(values) for key, values in sorted(choices.items())}


def validate_metadata_value(key: str, value: str) -> None:
    """Validate a metadata value for a known key, raising ``ValueError`` if invalid.

    Applies to any metadata key whose value format pynakes understands:
    ``dialect``/``databaseType`` must be ``bibtex`` or ``biblatex``, the ``fetch-*``
    booleans use standard ``true``/``false`` values (supported nonstandard
    compatibility aliases remain accepted),
    ``normalize-journal-style`` must be ``none``/``abbreviated``/``full``, the
    ``format-*`` choices must come from their enum, and all other known keys
    must have a non-empty value. Unknown-key values (including JabRef-only keys
    whose grammar pynakes does not define) are accepted without validation.
    """
    normalized_key = key.strip().lower()
    stripped = strip_meta_terminator(value)

    # Dialect must be bibtex or biblatex (both the native and JabRef key).
    if normalized_key in {"dialect", "databasetype"}:
        if stripped.lower() not in _VALID_DIALECTS:
            raise ValueError(f"Invalid dialect {stripped!r}; expected 'bibtex' or 'biblatex'")
        return

    # Fetch policy must be a comma-separated list of recognised values.
    if normalized_key == "pinax-fetch-policy":
        values = [v.strip().lower() for v in stripped.replace(";", ",").split(",") if v.strip()]
        invalid = [v for v in values if v not in VALID_FETCH_POLICIES]
        if invalid:
            raise ValueError(
                f"Invalid pinax-fetch-policy value(s) {invalid!r}; "
                f"expected one or more of: {', '.join(sorted(VALID_FETCH_POLICIES))}"
            )
        return

    if normalized_key == "normalize-journal-style":
        if stripped.lower() not in _VALID_JOURNAL_STYLES:
            raise ValueError(
                f"Invalid normalize-journal-style {stripped!r}; expected one of: "
                f"{', '.join(sorted(_VALID_JOURNAL_STYLES))}"
            )
        return

    if normalized_key == "normalize-journal-source":
        if stripped.lower() not in _VALID_JOURNAL_SOURCES:
            raise ValueError(
                f"Invalid normalize-journal-source {stripped!r}; expected one of: "
                f"{', '.join(sorted(_VALID_JOURNAL_SOURCES))}"
            )
        return

    if normalized_key in _FORMAT_CHOICES or normalized_key in _SETTING_CHOICES:
        choices = _FORMAT_CHOICES.get(normalized_key) or _SETTING_CHOICES[normalized_key]
        if stripped.lower() not in choices:
            raise ValueError(
                f"Invalid {normalized_key} {stripped!r}; expected one of: "
                f"{', '.join(sorted(choices))}"
            )
        return

    if normalized_key in _BOOLEAN_KEYS:
        if stripped.lower() not in _BOOLEAN_VALUES:
            raise ValueError(f"Invalid Boolean value for {normalized_key}: {stripped!r}")
        return

    if normalized_key == "lint-ignore":
        unknown = unknown_ignore_names(list(metadata_list(stripped)))
        if unknown:
            raise ValueError(
                f"Unknown lint-ignore name(s) {unknown!r}; expected a finding type "
                "or a category (correctness, content, formatting, consistency, profile)"
            )
        if not metadata_list(stripped):
            raise ValueError("lint-ignore must name at least one finding type or category")
        return

    if normalized_key == "format-line-width":
        try:
            width = int(stripped)
        except ValueError as exc:
            raise ValueError("format-line-width must be an integer") from exc
        if width < 20:
            raise ValueError("format-line-width must be at least 20")
        return

    if normalized_key == "coauthors-max-authors":
        try:
            limit = int(stripped)
        except ValueError as exc:
            raise ValueError("coauthors-max-authors must be a non-negative integer") from exc
        if limit < 0:
            raise ValueError("coauthors-max-authors must be a non-negative integer")
        return

    if normalized_key == "format-indent":
        if stripped.lower() != "tab":
            try:
                width = int(stripped)
            except ValueError as exc:
                raise ValueError("format-indent must be a positive integer or 'tab'") from exc
            if width < 1:
                raise ValueError("format-indent must be a positive integer or 'tab'")
        return

    if normalized_key.startswith(SAVED_QUERY_PREFIX):
        # Imported here: the selector grammar sits above the metadata layer.
        from pynakes.saved_queries import validate_saved_query

        validate_saved_query(key.strip()[len(SAVED_QUERY_PREFIX) :], stripped)
        return

    # Remaining known pynakes keys: refuse empty values.
    category = metadata_category(key)
    if category != "unknown" and not stripped:
        raise ValueError(f"Value for {key!r} must not be empty")


def metadata_category(key: str) -> MetadataCategory:
    """Return the category for a pynakes-owned key, or ``"unknown"``.

    Classifies only pynakes' own keys;
    :func:`pynakes.metadata.jabref.metadata_category` layers JabRef's key
    tables on top of this for the full picture.
    """
    normalized = key.lower()
    if normalized in PYNAKES_EXACT_KEYS:
        return PYNAKES_EXACT_KEYS[normalized]
    for prefix, category in PYNAKES_PREFIX_KEYS.items():
        if normalized.startswith(prefix):
            return category
    return CATEGORY_UNKNOWN


def native_dialect(lib: BibFile) -> str | None:
    """Return the library dialect from pynakes' native ``dialect`` key, or ``None``.

    Recognizes ``bibtex``/``biblatex`` (case-insensitive); any other value, or
    the key's absence, returns ``None``. See
    :func:`pynakes.metadata.jabref.library_dialect` for the fallback-aware
    accessor that also considers JabRef's ``databaseType``.
    """
    value = metadata_value(lib, "dialect")
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"bibtex", "biblatex"} else None


def parse_sort_order_value(value: str | None) -> list[tuple[str, bool]] | None:
    """Parse a native ``sort-order`` value string into sort criteria, or ``None``.

    The grammar matches the CLI ``--sort-by`` option: each comma-separated token
    is ``field`` or ``field:asc``/``field:desc``; a lone ``original`` or ``none``
    token means "keep current order" (an explicit empty criteria list, not
    ``None``). Returns ``None`` when ``value`` is empty.
    """
    tokens = metadata_list(value)
    if not tokens:
        return None
    if len(tokens) == 1 and tokens[0].lower() in {"original", "none"}:
        return []
    criteria: list[tuple[str, bool]] = []
    for token in tokens:
        name, _, direction = token.partition(":")
        descending = direction.strip().lower() in {"desc", "descending", "true", "down"}
        criteria.append((name.strip(), descending))
    return criteria


def native_sort_order(lib: BibFile) -> list[tuple[str, bool]] | None:
    """Return the entry sort order from pynakes' native ``sort-order`` key, or ``None``.

    See :func:`parse_sort_order_value` for the value grammar and
    :func:`pynakes.metadata.jabref.library_sort_order` for the fallback-aware
    accessor that also considers JabRef's ``saveOrderConfig``.
    """
    return parse_sort_order_value(metadata_value(lib, "sort-order"))


def native_key_pattern(lib: BibFile, entry_type: str | None = None) -> str | None:
    """Return pynakes' native citation-key pattern, or ``None`` when unset.

    Reads the type-specific ``key-pattern-<entrytype>`` key first (when
    ``entry_type`` is given), then the general ``key-pattern`` key. See
    :func:`pynakes.metadata.jabref.library_key_pattern` for the fallback-aware
    accessor that also considers JabRef's ``keypattern_*``/``keypatterndefault``.
    """
    if entry_type:
        value = metadata_value(lib, f"key-pattern-{entry_type.lower()}")
        if value is not None:
            return value
    return metadata_value(lib, "key-pattern")
