"""Structured support for JabRef library metadata comments.

JabRef stores library-level settings as top-level comments:

``@comment{jabref-meta: key:value;}``

The raw comments must be preserved for round-trip fidelity, but callers also
need structured access for inspection and safe edits. This module keeps both:
``MetadataBlock.raw`` is the exact comment text stored in the library,
while ``key`` and ``value`` expose the parsed payload. ``value`` deliberately
keeps JabRef's trailing semicolon when it was present; use
``MetadataBlock.normalized_value`` only for display and semantic comparisons.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from pynakes._text_utils import strip_jabref_terminator
from pynakes.model import BibFile, MetadataBlock


def metadata_value(lib: BibFile, name: str) -> str | None:
    """Return the effective metadata value for ``name`` (case-insensitive), without trailing ``;``.

    Searches the library's merged metadata (pynakes-meta overrides jabref-meta).
    Returns ``None`` when the key is absent.
    """
    lowered = {key.lower(): value for key, value in lib.metadata.items()}
    value = lowered.get(name.lower())
    if value is not None:
        return strip_jabref_terminator(value)
    return None


def metadata_values(lib: BibFile, name: str) -> tuple[str, ...]:
    """Return all metadata values for ``name`` across namespaces, in source order."""
    lowered = name.lower()
    return tuple(
        strip_jabref_terminator(block.value)
        for block in lib.metadata_blocks
        if block.key.lower() == lowered
    )


def metadata_list(value: str | None) -> tuple[str, ...]:
    """Split a metadata list value.

    Comma is the canonical write delimiter. Semicolon is accepted when reading
    legacy list values. Returns an empty tuple when ``value`` is ``None`` or
    blank; each non-empty token (after stripping whitespace) becomes one
    element.
    """
    if not value:
        return ()
    return tuple(part.strip() for part in value.replace(";", ",").split(",") if part.strip())


def format_metadata_list(values: Iterable[str]) -> str:
    """Render a list-valued metadata setting in canonical comma-separated form."""
    return ", ".join(value.strip() for value in values if value.strip())


def metadata_list_values(lib: BibFile, name: str) -> tuple[str, ...]:
    """Return a de-duplicated list metadata value merged across namespaces."""
    seen: set[str] = set()
    items: list[str] = []
    for value in metadata_values(lib, name):
        for item in metadata_list(value):
            if item in seen:
                continue
            seen.add(item)
            items.append(item)
    return tuple(items)


def metadata_bool(value: str | None, default: bool) -> bool:
    """Coerce a metadata string to ``bool``.

    Truthy spellings: ``1``, ``true``, ``yes``, ``on``, ``enabled``.
    Falsy spellings: ``0``, ``false``, ``no``, ``off``, ``disabled``.
    Anything else returns ``default``.
    """
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


MetadataCategory = Literal[
    "library",
    "save",
    "files",
    "groups",
    "selectors",
    "citation-key",
    "normalization",
    "lint",
    "usage",
    "pinax",
    "unknown",
]
MetadataOwner = Literal["jabref", "pynakes", "unknown"]

CATEGORY_LIBRARY: MetadataCategory = "library"
CATEGORY_SAVE: MetadataCategory = "save"
CATEGORY_FILES: MetadataCategory = "files"
CATEGORY_GROUPS: MetadataCategory = "groups"
CATEGORY_SELECTORS: MetadataCategory = "selectors"
CATEGORY_CITATION_KEY: MetadataCategory = "citation-key"
CATEGORY_NORMALIZATION: MetadataCategory = "normalization"
CATEGORY_LINT: MetadataCategory = "lint"
CATEGORY_USAGE: MetadataCategory = "usage"
CATEGORY_PINAX: MetadataCategory = "pinax"
CATEGORY_UNKNOWN: MetadataCategory = "unknown"

# Map values are *categories*: a coarse grouping used for inspection, docs, and
# validation messages. They are not namespaces (where a block is stored) and not
# owners (who understands the key). For example, ``databaseType`` is a JabRef key
# in the library-settings category, so it maps to ``CATEGORY_LIBRARY``.

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

# pynakes-owned metadata keys. These live in ``pynakes-meta`` by default because
# they have no JabRef equivalent or deliberately extend JabRef behavior.
PYNAKES_EXACT_KEYS: dict[str, MetadataCategory] = {
    "protected-terms": CATEGORY_NORMALIZATION,
    "journal-table": CATEGORY_NORMALIZATION,
    "ltwa-table": CATEGORY_NORMALIZATION,
    "files-dir": CATEGORY_PINAX,
    "fetch-preprint": CATEGORY_PINAX,
    "fetch-source": CATEGORY_PINAX,
    "fetch-published": CATEGORY_PINAX,
    # Linked LaTeX sources that cite this library; consulted by the citation-key
    # commands so .tex edits stay consistent without re-specifying the files.
    "tex-sources": CATEGORY_USAGE,
    # Lint profile settings. ``lint-required-fields`` applies to every entry;
    # the entry-type suffix form adds requirements for one type.
    "lint-required-fields": CATEGORY_LINT,
}

PYNAKES_PREFIX_KEYS: dict[str, MetadataCategory] = {
    # pynakes' normalization settings live under the canonical ``normalize-`` prefix.
    "normalize-": CATEGORY_NORMALIZATION,
    "lint-required-fields-": CATEGORY_LINT,
}

# The two structurally identical metadata comment namespaces.
JABREF_PREFIX = "jabref-meta:"
PYNAKES_PREFIX = "pynakes-meta:"


class DuplicateMetadataError(Exception):
    """Raised when a metadata update would be ambiguous."""

    def __init__(self, key: str, count: int):
        self.key = key
        self.count = count
        super().__init__(f"Cannot safely update {key!r}: found {count} matching blocks")


@dataclass
class MetadataUpdate:
    """One safe replacement or insertion of a top-level JabRef metadata block.

    ``old_raw`` and ``new_raw`` are retained so :class:`~pynakes.engine.Bibliography`
    can splice the comment into the original file instead of rewriting it.
    """

    key: str
    value: str
    old_raw: str | None
    new_raw: str
    created: bool
    namespace: str = "jabref"


def metadata_category(key: str) -> MetadataCategory:
    """Return the known metadata category for ``key``, or ``unknown``."""
    normalized = key.lower()
    if normalized in JABREF_EXACT_KEYS:
        return JABREF_EXACT_KEYS[normalized]
    for prefix, category in JABREF_PREFIX_KEYS.items():
        if normalized.startswith(prefix):
            return category
    if normalized in PYNAKES_EXACT_KEYS:
        return PYNAKES_EXACT_KEYS[normalized]
    for prefix, category in PYNAKES_PREFIX_KEYS.items():
        if normalized.startswith(prefix):
            return category
    return CATEGORY_UNKNOWN


def metadata_owner(key: str) -> MetadataOwner:
    """Return ``jabref``, ``pynakes``, or ``unknown`` for a metadata key."""
    normalized = key.lower()
    if normalized in JABREF_EXACT_KEYS or any(
        normalized.startswith(prefix) for prefix in JABREF_PREFIX_KEYS
    ):
        return "jabref"
    if normalized in PYNAKES_EXACT_KEYS or any(
        normalized.startswith(prefix) for prefix in PYNAKES_PREFIX_KEYS
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


def library_database_type(lib: BibFile) -> str:
    """Return the library dialect from ``databaseType`` metadata.

    Reads JabRef's ``databaseType`` key (tolerating its trailing ``;``) and
    returns ``"biblatex"`` or ``"bibtex"``. Defaults to ``"bibtex"`` when the key
    is absent or holds an unrecognized value, which is the safer baseline for
    constructed entries (``@misc`` is valid in both dialects).
    """
    for key, value in lib.metadata.items():
        if key.lower() == "databasetype":
            normalized = strip_jabref_terminator(value).lower()
            return "biblatex" if normalized == "biblatex" else "bibtex"
    return "bibtex"


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


def _make_metadata_block(
    segment: str, namespace: str, raw: str, comment_index: int
) -> MetadataBlock | None:
    """Build one block from a ``key:value`` segment, or ``None`` if malformed."""
    key, sep, value = segment.partition(":")
    if not sep:
        return None
    key = key.strip()
    if not key:
        return None
    category = metadata_category(key)
    return MetadataBlock(
        key=key,
        value=value.strip(),
        raw=raw,
        comment_index=comment_index,
        known=category != "unknown",
        category=category,
        namespace=namespace,
    )


def parse_metadata_comment(
    comment_text: str,
    *,
    raw: str | None = None,
    comment_index: int = -1,
) -> list[MetadataBlock]:
    """Parse a top-level metadata comment into one block per setting.

    ``comment_text`` is the content inside ``@comment{...}``. ``raw`` should be
    the full raw comment when available; it is used for precise replacements.

    A ``jabref-meta`` comment holds exactly one ``key:value`` (its value may span
    multiple lines, e.g. ``grouping``) and yields a single block — JabRef's own
    format is preserved verbatim. A ``pynakes-meta`` comment may carry several
    settings, one ``key:value;`` per line, and yields one block per line, all
    sharing the comment's raw text and ``comment_index``; the one-setting and
    consolidated multi-line layouts parse identically. Returns ``[]`` for a
    non-metadata comment.
    """
    stripped = comment_text.strip()
    if stripped.startswith("{"):
        stripped = stripped[1:].strip()

    lowered = stripped.lower()
    if lowered.startswith(JABREF_PREFIX):
        namespace, prefix = "jabref", JABREF_PREFIX
    elif lowered.startswith(PYNAKES_PREFIX):
        namespace, prefix = "pynakes", PYNAKES_PREFIX
    else:
        return []

    body = stripped[len(prefix) :].strip()
    if not body:
        return []

    raw_text = raw if raw is not None else f"@comment{{{comment_text}}}"

    if namespace == "jabref":
        block = _make_metadata_block(body, namespace, raw_text, comment_index)
        return [block] if block is not None else []

    # pynakes-meta: one setting per line (values are single-line).
    blocks: list[MetadataBlock] = []
    for line in body.splitlines():
        block = _make_metadata_block(line.strip(), namespace, raw_text, comment_index)
        if block is not None:
            blocks.append(block)
    return blocks


def metadata_blocks_to_dict(blocks: list[MetadataBlock]) -> dict[str, str]:
    """Return the backward-compatible flat metadata dict.

    Later blocks win, matching the historical parser behavior.
    """
    result: dict[str, str] = {}
    for block in blocks:
        result[block.key] = block.value
    return result


def format_metadata_comment(key: str, value: str, namespace: str = "jabref") -> str:
    """Render a canonical metadata comment for ``key`` and ``value``.

    ``namespace`` selects the ``jabref-meta:`` or ``pynakes-meta:`` prefix; the
    body syntax is identical in both.
    """
    value = value.strip()
    if value and not value.endswith(";"):
        value = f"{value};"
    prefix = PYNAKES_PREFIX if namespace == "pynakes" else JABREF_PREFIX
    return f"@comment{{{prefix} {key.strip()}:{value}}}"


def format_pynakes_meta_block(items: list[tuple[str, str]], line_ending: str = "\n") -> str:
    """Render pynakes settings as one consolidated multi-line ``pynakes-meta`` comment.

    ``items`` is an ordered ``(key, value)`` list; each setting gets its own
    ``key: value`` line so a single-setting change is still a one-line diff.
    JabRef ignores the ``pynakes-meta`` namespace, so pynakes uses this compact
    layout (no per-key prefix, no JabRef ``;`` terminator) rather than one comment
    per key. The reader (:func:`parse_metadata_comment`) still accepts the older
    ``key:value;`` spelling, so both layouts round-trip; this is the default
    written form. Any trailing ``;`` on a value is dropped on output.
    """
    lines = [f"@comment{{{PYNAKES_PREFIX}"]
    for key, value in items:
        value = strip_jabref_terminator(value)
        lines.append(f"{key.strip()}: {value}")
    lines.append("}")
    return line_ending.join(lines)


def consolidate_metadata(lib: BibFile, text: str, line_ending: str = "\n") -> str | None:
    """Relocate every metadata comment into one canonical section at file end.

    JabRef writes its ``@Comment{jabref-meta: ...}`` blocks contiguously at the
    bottom of the file, sorted by key. A library that has been hand-edited (or
    had entries appended after a JabRef save) ends up with metadata stranded in
    the middle. This gathers all metadata and rewrites it as one sorted section
    at the end: each ``jabref-meta`` key as its own comment, preserved verbatim
    (including JabRef's multi-line ``grouping`` formatting), followed by a single
    consolidated ``pynakes-meta`` block holding every pynakes key — since JabRef
    ignores that namespace, pynakes packs it instead of repeating the prefix.

    Returns the rewritten text, or ``None`` when the file is already in this
    canonical layout (so callers can treat it as a no-op).
    """
    jabref_blocks = lib.jabref_metadata_blocks
    pynakes_blocks = lib.pynakes_metadata_blocks
    if not jabref_blocks and not pynakes_blocks:
        return None

    # Remove every existing metadata comment from the text, deduping by physical
    # comment (consolidated pynakes blocks share one comment / comment_index).
    stripped = text
    seen: set[int] = set()
    for block in lib.metadata_blocks:
        if block.comment_index in seen:
            continue
        seen.add(block.comment_index)
        index = stripped.find(block.raw)
        if index == -1:
            # The raw text isn't where we expect (e.g. it was rewritten by a
            # prior edit); decline rather than corrupt the file.
            return None
        end = index + len(block.raw)
        if stripped[end : end + len(line_ending)] == line_ending:
            end += len(line_ending)
        stripped = stripped[:index] + stripped[end:]

    # Collapse blank-line runs left behind by the removals.
    triple = line_ending * 3
    while triple in stripped:
        stripped = stripped.replace(triple, line_ending * 2)

    # jabref-meta first, each comment verbatim and sorted by key (keeps JabRef's
    # own keys grouped, stable for repeated keys like legacy groups)...
    parts = [
        block.raw for block in sorted(jabref_blocks, key=lambda b: (b.key.lower(), b.comment_index))
    ]
    # ...then a single consolidated pynakes-meta block (last value wins per key).
    if pynakes_blocks:
        merged: dict[str, str] = {}
        for block in pynakes_blocks:
            merged[block.key] = block.value
        items = sorted(merged.items(), key=lambda kv: kv[0].lower())
        parts.append(format_pynakes_meta_block(items, line_ending))

    section = (line_ending + line_ending).join(parts)

    body = stripped.rstrip()
    if body:
        result = body + line_ending + line_ending + section + line_ending
    else:
        result = section + line_ending

    return result if result != text else None


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
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")

    if namespace is None:
        namespace = default_namespace(key, lib)
    if namespace not in {"jabref", "pynakes"}:
        raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")

    if namespace == "jabref":
        if not allow_unknown and not is_known_metadata_key(key):
            raise ValueError(
                f"Unknown JabRef metadata key {key!r}; pass --allow-unknown to write it to "
                "jabref-meta, or write it to pynakes-meta instead"
            )
        return _set_jabref_metadata(lib, key, value)

    return _set_pynakes_metadata(lib, key, value)


def _set_jabref_metadata(lib: BibFile, key: str, value: str) -> MetadataUpdate:
    """Set one ``jabref-meta`` key — one comment per key (JabRef's own format)."""
    blocks = lib.jabref_metadata_blocks

    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if len(matches) > 1:
        raise DuplicateMetadataError(key, len(matches))

    new_raw = format_metadata_comment(key, value, "jabref")
    new_blocks = parse_metadata_comment(new_raw[new_raw.find("{") + 1 : -1], raw=new_raw)
    if not new_blocks:
        raise ValueError(f"Could not render metadata key {key!r}")
    new_block = new_blocks[0]

    if not matches:
        new_block.comment_index = len(lib.raw_comments)
        lib.raw_comments.append(new_raw)
        blocks.append(new_block)
        return MetadataUpdate(key, new_block.value, None, new_raw, True, "jabref")

    old = matches[0]
    new_block.comment_index = old.comment_index
    if 0 <= old.comment_index < len(lib.raw_comments):
        lib.raw_comments[old.comment_index] = new_raw
    blocks[blocks.index(old)] = new_block
    return MetadataUpdate(key, new_block.value, old.raw, new_raw, False, "jabref")


def _set_pynakes_metadata(lib: BibFile, key: str, value: str) -> MetadataUpdate:
    """Set one ``pynakes-meta`` key inside the consolidated multi-line block.

    The setting is added to (or replaced within) a single ``pynakes-meta``
    comment rather than written as its own comment, so the file accumulates one
    compact block. Editing one key rewrites the whole comment, but since each
    setting is on its own line the unified diff still shows only the changed
    line. A new key appends to the last existing ``pynakes-meta`` comment, or
    creates one when there is none.
    """
    blocks = lib.pynakes_metadata_blocks
    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if len(matches) > 1:
        raise DuplicateMetadataError(key, len(matches))

    if matches:
        target_index: int | None = matches[0].comment_index
    elif blocks:
        target_index = blocks[-1].comment_index
    else:
        target_index = None

    # Assemble the (key, value) lines for the target comment, setting ours.
    items: list[tuple[str, str]] = []
    replaced = False
    if target_index is not None:
        for block in blocks:
            if block.comment_index != target_index:
                continue
            if block.key.lower() == key.lower():
                items.append((block.key, value))
                replaced = True
            else:
                items.append((block.key, block.value))
    if not replaced:
        items.append((key, value))

    new_raw = format_pynakes_meta_block(items, lib.line_ending)
    comment_index = target_index if target_index is not None else len(lib.raw_comments)
    new_blocks = parse_metadata_comment(
        new_raw[new_raw.find("{") + 1 : -1], raw=new_raw, comment_index=comment_index
    )

    if target_index is None:
        lib.raw_comments.append(new_raw)
        blocks.extend(new_blocks)
        old_raw: str | None = None
    else:
        old_raw = lib.raw_comments[comment_index]
        lib.raw_comments[comment_index] = new_raw
        lib.pynakes_metadata_blocks = [
            b for b in blocks if b.comment_index != comment_index
        ] + new_blocks

    set_value = next((b.value for b in new_blocks if b.key.lower() == key.lower()), value)
    return MetadataUpdate(key, set_value, old_raw, new_raw, not matches, "pynakes")


def remove_metadata(
    lib: BibFile, key: str, *, namespace: str | None = None
) -> MetadataUpdate | None:
    """Remove one metadata key, updating raw comments in place.

    ``namespace`` selects which namespace to remove from; when ``None`` the key is
    located automatically (a match in both namespaces is refused as ambiguous).
    Returns the :class:`MetadataUpdate` describing the text change (``new_raw`` is
    ``""`` when the comment is dropped entirely), or ``None`` when the key is
    absent. Each ``jabref-meta`` key is its own comment, so it is dropped whole; a
    ``pynakes-meta`` key is removed from its consolidated comment, which is
    rewritten in place (or dropped when no keys remain).
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")

    if namespace is None:
        in_jabref = any(b.key.lower() == key.lower() for b in lib.jabref_metadata_blocks)
        in_pynakes = any(b.key.lower() == key.lower() for b in lib.pynakes_metadata_blocks)
        if in_jabref and in_pynakes:
            raise DuplicateMetadataError(key, 2)
        if in_jabref:
            namespace = "jabref"
        elif in_pynakes:
            namespace = "pynakes"
        else:
            return None
    if namespace not in {"jabref", "pynakes"}:
        raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")

    if namespace == "jabref":
        return _remove_jabref_metadata(lib, key)
    return _remove_pynakes_metadata(lib, key)


def _comment_raw(lib: BibFile, block: MetadataBlock) -> str:
    """Return the live raw comment text for *block* (its stored raw as fallback)."""
    if 0 <= block.comment_index < len(lib.raw_comments):
        return lib.raw_comments[block.comment_index]
    return block.raw


def _remove_jabref_metadata(lib: BibFile, key: str) -> MetadataUpdate | None:
    """Drop the ``jabref-meta`` comment for ``key`` (one comment per key)."""
    blocks = lib.jabref_metadata_blocks
    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if not matches:
        return None
    if len(matches) > 1:
        raise DuplicateMetadataError(key, len(matches))
    old = matches[0]
    old_raw = _comment_raw(lib, old)
    # Keep the comment slot (as a blank placeholder) so existing comment_index /
    # source-layout references stay valid; the surgical text edit removes it from
    # the rendered file.
    if 0 <= old.comment_index < len(lib.raw_comments):
        lib.raw_comments[old.comment_index] = ""
    lib.jabref_metadata_blocks = [b for b in blocks if b is not old]
    return MetadataUpdate(key, "", old_raw, "", False, "jabref")


def _remove_pynakes_metadata(lib: BibFile, key: str) -> MetadataUpdate | None:
    """Remove ``key`` from its consolidated ``pynakes-meta`` comment."""
    blocks = lib.pynakes_metadata_blocks
    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if not matches:
        return None
    if len(matches) > 1:
        raise DuplicateMetadataError(key, len(matches))
    comment_index = matches[0].comment_index
    old_raw = _comment_raw(lib, matches[0])

    remaining = [
        (b.key, b.value)
        for b in blocks
        if b.comment_index == comment_index and b.key.lower() != key.lower()
    ]
    others = [b for b in blocks if b.comment_index != comment_index]

    if not remaining:
        # Last key in the comment: drop the whole comment (blank placeholder keeps
        # indices stable; the surgical edit removes it from the file).
        if 0 <= comment_index < len(lib.raw_comments):
            lib.raw_comments[comment_index] = ""
        lib.pynakes_metadata_blocks = others
        return MetadataUpdate(key, "", old_raw, "", False, "pynakes")

    new_raw = format_pynakes_meta_block(remaining, lib.line_ending)
    new_blocks = parse_metadata_comment(
        new_raw[new_raw.find("{") + 1 : -1], raw=new_raw, comment_index=comment_index
    )
    if 0 <= comment_index < len(lib.raw_comments):
        lib.raw_comments[comment_index] = new_raw
    lib.pynakes_metadata_blocks = others + new_blocks
    return MetadataUpdate(key, "", old_raw, new_raw, False, "pynakes")


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
