"""JabRef compatibility adapter.

This module is where all JabRef-specific knowledge concentrates: its key
vocabulary, its encoded value grammars (``saveActions``, ``saveOrderConfig``,
``databaseType``), and — because "key owner" and "namespace routing" are
concepts that exist only *because* JabRef and pynakes share a file format —
the cross-namespace arbitration (:func:`metadata_owner`,
:func:`is_known_metadata_key`, :func:`default_namespace`, and the
:func:`set_metadata`/:func:`remove_metadata` routing wrappers). It also hosts
the fallback-aware accessors (:func:`library_dialect`,
:func:`library_sort_order`) that read a pynakes-native key first and a JabRef
key second. Domain code should use those, not JabRef's raw keys.

Imports :mod:`pynakes.metadata.core` (block mechanics) and
:mod:`pynakes.metadata.schema` (pynakes' own key tables); the canonical schema
never imports this module back.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from pynakes._text_utils import strip_jabref_terminator
from pynakes.metadata import core
from pynakes.metadata import schema as pynakes_schema
from pynakes.metadata.core import MetadataUpdate, metadata_value
from pynakes.metadata.schema import (
    CATEGORY_CITATION_KEY,
    CATEGORY_FILES,
    CATEGORY_GROUPS,
    CATEGORY_LIBRARY,
    CATEGORY_SAVE,
    CATEGORY_SELECTORS,
    MetadataCategory,
)
from pynakes.model import BibFile

MetadataOwner = Literal["jabref", "pynakes", "unknown"]

# JabRef-native metadata keys. These can be written to ``jabref-meta`` by
# default because JabRef understands them and should keep seeing them.
JABREF_EXACT_KEYS: dict[str, MetadataCategory] = {
    "databasetype": CATEGORY_LIBRARY,
    "saveorderconfig": CATEGORY_SAVE,
    "saveorder": CATEGORY_SAVE,
    "saveactions": CATEGORY_SAVE,
    "blgfilepath": CATEGORY_LIBRARY,
    "filedirectorylatex": CATEGORY_FILES,
    "grouping": CATEGORY_GROUPS,
    "groupstree": CATEGORY_GROUPS,
    "groups": CATEGORY_GROUPS,
    "groupsversion": CATEGORY_GROUPS,
    "groups-search-syntax-version": CATEGORY_GROUPS,
    "bibdesk static groups": CATEGORY_GROUPS,
    "protectedflag": CATEGORY_LIBRARY,
    "versiondbstructure": CATEGORY_LIBRARY,
    "keypatterndefault": CATEGORY_CITATION_KEY,
}

JABREF_PREFIX_KEYS: dict[str, MetadataCategory] = {
    "filedirectory": CATEGORY_FILES,
    "selector_": CATEGORY_SELECTORS,
    "keypattern_": CATEGORY_CITATION_KEY,
}


def metadata_category(key: str) -> MetadataCategory:
    """Return the known metadata category for ``key``, or ``"unknown"``.

    Checks JabRef's key tables first, then falls back to pynakes' own
    (:func:`pynakes.metadata.schema.metadata_category`) — the full picture
    across both namespaces.
    """
    normalized = key.lower()
    if normalized in JABREF_EXACT_KEYS:
        return JABREF_EXACT_KEYS[normalized]
    for prefix, category in JABREF_PREFIX_KEYS.items():
        if normalized.startswith(prefix):
            return category
    return pynakes_schema.metadata_category(key)


def metadata_owner(key: str) -> MetadataOwner:
    """Return ``jabref``, ``pynakes``, or ``unknown`` for a metadata key."""
    normalized = key.lower()
    if normalized in JABREF_EXACT_KEYS or any(
        normalized.startswith(prefix) for prefix in JABREF_PREFIX_KEYS
    ):
        return "jabref"
    if normalized in pynakes_schema.PYNAKES_EXACT_KEYS or any(
        normalized.startswith(prefix) for prefix in pynakes_schema.PYNAKES_PREFIX_KEYS
    ):
        return "pynakes"
    return "unknown"


def is_known_metadata_key(key: str) -> bool:
    """Return whether ``key`` is a recognized JabRef/pynakes metadata key."""
    return metadata_owner(key) != "unknown"


@dataclass
class SaveActions:
    """JabRef's ``saveActions`` field-formatter configuration.

    JabRef stores on-save cleanups as
    ``@comment{jabref-meta: saveActions:enabled;field[formatter,...]...;}``.
    ``cleanups`` maps each field to its ordered list of formatter keys. pynakes
    reads this so JabRef-configured normalization drives equivalent ``normalize``
    behavior instead of pynakes inventing redundant settings.
    """

    enabled: bool
    cleanups: dict[str, list[str]] = field(default_factory=dict)

    def has(self, formatters: str | tuple[str, ...], fields: tuple[str, ...] | None = None) -> bool:
        """Return whether any of ``formatters`` is configured (on ``fields`` if given)."""
        wanted = (formatters,) if isinstance(formatters, str) else tuple(formatters)
        for fld, keys in self.cleanups.items():
            if fields is not None and fld.lower() not in {f.lower() for f in fields}:
                continue
            if any(k in keys for k in wanted):
                return True
        return False


_SAVE_ACTION_CLEANUP = re.compile(r"([^\[\];\s]+)\s*\[([^\]]*)\]")


def parse_save_actions(value: str | None) -> SaveActions | None:
    """Parse a ``saveActions`` metadata value, or ``None`` if absent.

    Tolerant of JabRef's whitespace/newline layout: the leading token before the
    first ``;`` is the ``enabled``/``disabled`` flag, and each ``field[f1,f2]``
    group anywhere in the body is a field-to-formatters cleanup.
    """
    if not value or not value.strip():
        return None
    head, _, _ = value.strip().partition(";")
    enabled = head.strip().lower() == "enabled"
    cleanups: dict[str, list[str]] = {}
    for fld, formatters in _SAVE_ACTION_CLEANUP.findall(value):
        keys = [f.strip() for f in formatters.split(",") if f.strip()]
        if keys:
            cleanups.setdefault(fld, []).extend(keys)
    return SaveActions(enabled=enabled, cleanups=cleanups)


def library_save_actions(lib: BibFile) -> SaveActions | None:
    """Return the parsed ``saveActions`` from a library's merged metadata, if any."""
    for key, value in lib.metadata.items():
        if key.lower() == "saveactions":
            return parse_save_actions(value)
    return None


# JabRef's citation-key field name; ``bibtexkey`` is its accepted legacy spelling.
SAVE_ORDER_KEY_FIELDS = {"citationkey", "bibtexkey", "key"}
SAVE_ORDER_TYPES = {"specified", "original", "table"}


@dataclass
class SaveOrder:
    """JabRef's ``saveOrderConfig`` entry-ordering configuration.

    JabRef stores the on-save sort order as
    ``@comment{jabref-meta: saveOrderConfig:<type>;<field>;<descending>;...;}``,
    where ``type`` is ``specified``, ``original``, or ``table`` and each
    following ``field;descending`` pair is one sort criterion (``descending`` is
    the string ``true`` or ``false``). pynakes reads this so a library JabRef
    would save in a given order is sorted the same way by ``normalize``.
    """

    order_type: str
    criteria: list[tuple[str, bool]] = field(default_factory=list)


def parse_save_order(value: str | None) -> SaveOrder | None:
    """Parse a ``saveOrderConfig`` metadata value, or ``None`` if absent.

    Mirrors JabRef's own parser: the first ``;``-separated token is the order
    type and each subsequent ``field;descending`` pair is a criterion. An
    unrecognized leading token with an odd token count is tolerated as
    ``specified`` (JabRef's fallback); anything else degrades to ``original``
    (keep existing order). The serializer's trailing ``;`` is ignored.
    """
    if not value or not value.strip():
        return None
    tokens = [token.strip() for token in strip_jabref_terminator(value).split(";")]
    while tokens and tokens[-1] == "":
        tokens.pop()
    if not tokens:
        return None

    head = tokens[0].lower()
    if head in SAVE_ORDER_TYPES:
        order_type = head
    elif len(tokens) > 1 and len(tokens) % 2 == 1:
        order_type = "specified"  # JabRef's lenient fallback for a missing type
    else:
        return SaveOrder("original", [])

    criteria: list[tuple[str, bool]] = []
    # Pairs start after the leading type token; ignore a dangling half-pair.
    for index in range(1, len(tokens) - 1, 2):
        field_name = tokens[index]
        if not field_name:
            continue
        descending = tokens[index + 1].strip().lower() == "true"
        criteria.append((field_name, descending))
    return SaveOrder(order_type, criteria)


def library_save_order(lib: BibFile) -> SaveOrder | None:
    """Return the parsed ``saveOrderConfig`` from merged metadata, if any.

    Reads JabRef's current ``saveOrderConfig`` key, falling back to the
    reserved ``saveOrder`` alias.
    """
    for name in ("saveOrderConfig", "saveOrder"):
        value = metadata_value(lib, name)
        if value is not None:
            return parse_save_order(value)
    return None


def raw_database_type(lib: BibFile) -> str | None:
    """Return the library's raw JabRef ``databaseType`` value, or ``None`` if absent.

    Tolerates JabRef's trailing ``;`` and normalizes to ``"biblatex"`` or
    ``"bibtex"`` (any unrecognized value is treated as ``"bibtex"``, the safer
    baseline since ``@misc`` is valid in both dialects). This is the raw JabRef
    reader; :func:`library_dialect` layers pynakes' native ``dialect`` key on
    top of it.
    """
    for key, value in lib.metadata.items():
        if key.lower() == "databasetype":
            normalized = strip_jabref_terminator(value).lower()
            return "biblatex" if normalized == "biblatex" else "bibtex"
    return None


def library_dialect(lib: BibFile) -> str:
    """Return the library dialect: native ``dialect`` first, else JabRef ``databaseType``.

    Defaults to ``"bibtex"`` when neither is set, the safer baseline for
    constructed entries (``@misc`` is valid in both dialects). Replaces the
    former ``library_database_type``.
    """
    native = pynakes_schema.native_dialect(lib)
    if native is not None:
        return native
    raw = raw_database_type(lib)
    return raw if raw is not None else "bibtex"


def library_sort_order(lib: BibFile) -> list[tuple[str, bool]] | None:
    """Return the effective entry sort order: native ``sort-order`` first, else JabRef.

    Falls back to JabRef's ``saveOrderConfig``, honored only when its type is
    ``specified`` (matching JabRef's own semantics — ``original``/``table``
    leave entries untouched). Returns ``None`` when neither is configured.
    """
    native = pynakes_schema.native_sort_order(lib)
    if native is not None:
        return native
    save_order = library_save_order(lib)
    if save_order is not None and save_order.order_type == "specified":
        return list(save_order.criteria)
    return None


def raw_key_pattern(lib: BibFile, entry_type: str) -> str | None:
    """Return the raw JabRef citation-key pattern for ``entry_type``, or ``None``.

    Reads JabRef's type-specific ``keypattern_<entrytype>`` first, then the
    ``keypatterndefault`` fallback (both tolerating the trailing ``;``). This is
    the raw JabRef reader; :func:`library_key_pattern` layers pynakes' native
    ``key-pattern`` keys on top of it.
    """
    type_key = f"keypattern_{entry_type.lower()}"
    for key, value in lib.metadata.items():
        if key.lower() == type_key:
            return strip_jabref_terminator(value)
    for key, value in lib.metadata.items():
        if key.lower() == "keypatterndefault":
            return strip_jabref_terminator(value)
    return None


def library_key_pattern(lib: BibFile, entry_type: str) -> str | None:
    """Return the effective citation-key pattern: native ``key-pattern`` first, else JabRef.

    Reads pynakes' native ``key-pattern-<entrytype>``/``key-pattern`` keys first,
    falling back to JabRef's ``keypattern_<entrytype>``/``keypatterndefault``.
    Returns ``None`` when neither is configured (callers then use pynakes'
    built-in ``AuthorYearTitle`` default).
    """
    native = pynakes_schema.native_key_pattern(lib, entry_type)
    if native is not None:
        return native
    return raw_key_pattern(lib, entry_type)


def library_is_jabref_tracked(lib: BibFile) -> bool:
    """Whether the library maintains a ``jabref-meta`` projection.

    Presence-based: a file that already carries any ``jabref-meta`` block follows
    JabRef's convention, so pynakes keeps writing JabRef-native keys there. A
    greenfield pynakes-native file carries none — its settings live in
    ``pynakes-meta`` — until :func:`pynakes.engine.Bibliography.adopt_jabref`
    establishes the projection. This is interop on demand, not parity by default.
    """
    return bool(lib.jabref_metadata_blocks)


def default_namespace(key: str, lib: BibFile | None = None) -> str:
    """Return the namespace a key should be written to by default.

    pynakes-owned keys (and anything JabRef cannot represent) always go to
    ``pynakes-meta``. A JabRef-native key goes to ``jabref-meta`` only when the
    file is *JabRef-tracked* — i.e. it already carries ``jabref-meta`` blocks (see
    :func:`library_is_jabref_tracked`). Without file context (``lib is None``) the
    answer is by owner, the static "where does this key belong" view.

    The effect: a pynakes-native file stays free of ``jabref-meta`` until the user
    opts in via ``adopt-jabref``; an existing JabRef library keeps its convention.
    """
    if metadata_owner(key) != "jabref":
        return "pynakes"
    if lib is not None and not library_is_jabref_tracked(lib):
        return "pynakes"
    return "jabref"


# Aliased concepts: a pynakes-native key and the JabRef key encoding the same
# setting. Reads are native-first (the ``library_*`` accessors above); writes to
# the native key are mirrored into ``jabref-meta`` on JabRef-tracked files (see
# :func:`project_aliased_to_jabref`) so JabRef never sees a stale value.
ALIASED_EXACT: dict[str, str] = {
    "dialect": "databaseType",
    "sort-order": "saveOrderConfig",
    "key-pattern": "keypatterndefault",
}
ALIASED_PREFIX: dict[str, str] = {
    "key-pattern-": "keypattern_",
}


def format_save_order(criteria: list[tuple[str, bool]] | None) -> str:
    """Serialize sort criteria into JabRef's ``saveOrderConfig`` value grammar.

    Empty/``None`` criteria (pynakes' "keep current order") serialize to JabRef's
    ``original``; otherwise a ``specified;field;true|false;...`` sequence.
    """
    if not criteria:
        return "original"
    parts = ["specified"]
    for field_name, descending in criteria:
        parts.append(field_name)
        parts.append("true" if descending else "false")
    return ";".join(parts)


def _jabref_key_for_native(native_key: str) -> str | None:
    """Return the JabRef key mirroring ``native_key``, or ``None`` if unaliased."""
    lowered = native_key.lower()
    if lowered in ALIASED_EXACT:
        return ALIASED_EXACT[lowered]
    for prefix, jabref_prefix in ALIASED_PREFIX.items():
        if lowered.startswith(prefix):
            return jabref_prefix + lowered[len(prefix) :]
    return None


def _jabref_value_for_native(native_key: str, native_value: str) -> str:
    """Translate a native value to its JabRef-encoded form for mirroring."""
    if native_key.lower() == "sort-order":
        return format_save_order(pynakes_schema.parse_sort_order_value(native_value))
    # ``dialect`` and the ``key-pattern`` family share their value grammar with
    # their JabRef counterparts, so the value passes through unchanged.
    return native_value.strip()


def jabref_projection(native_key: str, native_value: str) -> tuple[str, str] | None:
    """Return the ``(jabref_key, jabref_value)`` mirroring an aliased native setting.

    Returns ``None`` when ``native_key`` has no JabRef counterpart. Used to build
    a JabRef projection outside the live-edit path (e.g. ``init --jabref``);
    :func:`project_aliased_to_jabref` is the in-place edit equivalent.
    """
    jabref_key = _jabref_key_for_native(native_key)
    if jabref_key is None:
        return None
    return jabref_key, _jabref_value_for_native(native_key, strip_jabref_terminator(native_value))


def project_aliased_to_jabref(lib: BibFile, update: MetadataUpdate) -> MetadataUpdate | None:
    """Mirror an aliased pynakes-native write into the ``jabref-meta`` projection.

    When ``update`` set one of the aliased native keys (``dialect``,
    ``sort-order``, ``key-pattern``/``key-pattern-<type>``) in ``pynakes-meta``
    and ``lib`` is JabRef-tracked, write the equivalent JabRef key so JabRef
    never sees a stale value. Returns the JabRef-side :class:`MetadataUpdate`, or
    ``None`` when no mirror applies — an unaliased key, a non-``pynakes`` write,
    or a file that is not JabRef-tracked (a pynakes-native library gains no
    ``jabref-meta`` it did not ask for).
    """
    if update.namespace != "pynakes":
        return None
    jabref_key = _jabref_key_for_native(update.key)
    if jabref_key is None or not library_is_jabref_tracked(lib):
        return None
    jabref_value = _jabref_value_for_native(update.key, strip_jabref_terminator(update.value))
    return core.set_in_namespace(
        lib, jabref_key, jabref_value, "jabref", classify=metadata_category
    )


def aliased_drift_warnings(lib: BibFile) -> list[str]:
    """Return warnings for aliased concepts set in both namespaces with differing values.

    pynakes reads aliased concepts native-first, so a ``pynakes-meta`` value
    silently wins over a differing ``jabref-meta`` one (e.g. JabRef edited
    ``databaseType`` after pynakes set ``dialect``). This surfaces each such
    divergence so it is visible and fixable — re-setting the native key mirrors
    it back into ``jabref-meta`` (see :func:`project_aliased_to_jabref`).
    """
    warnings: list[str] = []

    native_dialect = pynakes_schema.native_dialect(lib)
    raw_dialect = raw_database_type(lib)
    if native_dialect is not None and raw_dialect is not None and raw_dialect != native_dialect:
        warnings.append(
            f"metadata drift: pynakes-meta 'dialect' is {native_dialect!r} but jabref-meta "
            f"'databaseType' is {raw_dialect!r}; pynakes uses {native_dialect!r}. "
            f"Run 'metadata set dialect {native_dialect}' to re-sync JabRef."
        )

    native_order = pynakes_schema.native_sort_order(lib)
    jabref_order = library_save_order(lib)
    if (
        native_order is not None
        and jabref_order is not None
        and jabref_order.order_type == "specified"
        and list(jabref_order.criteria) != native_order
    ):
        warnings.append(
            "metadata drift: pynakes-meta 'sort-order' and jabref-meta 'saveOrderConfig' "
            "disagree; pynakes uses 'sort-order'. Re-set 'sort-order' to re-sync JabRef."
        )

    return warnings


def set_metadata(
    lib: BibFile,
    key: str,
    value: str,
    *,
    namespace: str | None = None,
    allow_unknown: bool = False,
) -> MetadataUpdate:
    """Set one metadata value, updating raw comments in place.

    ``namespace`` selects the target comment: ``"jabref"`` or ``"pynakes"``.
    When ``None`` (the default), the key is routed by :func:`default_namespace`
    using the file's context — a JabRef-native key lands in ``jabref-meta`` only
    when the file is already JabRef-tracked, otherwise it (and every pynakes key)
    goes to ``pynakes-meta``. Writes into ``jabref-meta`` still
    reject keys JabRef will not understand unless ``allow_unknown`` is set;
    ``pynakes-meta`` accepts any key, since it is pynakes' own namespace. If
    multiple existing blocks in the target namespace match the key, the update
    is refused because choosing one would be ambiguous.

    Raises ``ValueError`` when ``value`` is not valid for the given key (e.g. a
    ``dialect`` that is not ``"bibtex"`` or ``"biblatex"``).
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")

    if namespace is None:
        namespace = default_namespace(key, lib)
    if namespace not in {"jabref", "pynakes"}:
        raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")

    if namespace == "jabref" and not allow_unknown and not is_known_metadata_key(key):
        raise ValueError(
            f"Unknown JabRef metadata key {key!r}; pass --allow-unknown to write it to "
            "jabref-meta, or write it to pynakes-meta instead"
        )

    pynakes_schema.validate_metadata_value(key, value)

    return core.set_in_namespace(lib, key, value, namespace, classify=metadata_category)


def remove_metadata(
    lib: BibFile, key: str, *, namespace: str | None = None
) -> MetadataUpdate | None:
    """Remove one metadata key, updating raw comments in place.

    ``namespace`` selects which namespace to remove from; when ``None`` the key is
    located automatically (a match in both namespaces is refused as ambiguous).
    Returns the :class:`~pynakes.metadata.core.MetadataUpdate` describing the
    text change (``new_raw`` is ``""`` when the comment is dropped entirely), or
    ``None`` when the key is absent. Each ``jabref-meta`` key is its own comment,
    so it is dropped whole; a ``pynakes-meta`` key is removed from its
    consolidated comment, which is rewritten in place (or dropped when no keys
    remain).
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")

    if namespace is None:
        in_jabref = any(b.key.lower() == key.lower() for b in lib.jabref_metadata_blocks)
        in_pynakes = any(b.key.lower() == key.lower() for b in lib.pynakes_metadata_blocks)
        if in_jabref and in_pynakes:
            raise core.DuplicateMetadataError(key, 2)
        if in_jabref:
            namespace = "jabref"
        elif in_pynakes:
            namespace = "pynakes"
        else:
            return None
    if namespace not in {"jabref", "pynakes"}:
        raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")

    return core.remove_in_namespace(lib, key, namespace, classify=metadata_category)


@dataclass
class JabRefAdoptReport:
    """Outcome of :meth:`pynakes.engine.Bibliography.adopt_jabref`.

    ``moved_keys`` are JabRef-native keys relocated from ``pynakes-meta`` into
    ``jabref-meta``; ``database_type_added`` is set when a ``databaseType`` block
    was written to anchor tracking; ``was_tracked`` reflects whether the file
    already carried ``jabref-meta`` before the call.
    """

    moved_keys: list[str] = field(default_factory=list)
    database_type_added: bool = False
    was_tracked: bool = False

    @property
    def changed(self) -> bool:
        """Whether the call modified the file."""
        return bool(self.moved_keys) or self.database_type_added
