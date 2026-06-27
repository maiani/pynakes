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
from dataclasses import dataclass, field
from typing import Literal

from pynakes.model import BibFile, MetadataBlock

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


def library_database_type(lib: BibFile) -> str:
    """Return the library dialect from ``databaseType`` metadata.

    Reads JabRef's ``databaseType`` key (tolerating its trailing ``;``) and
    returns ``"biblatex"`` or ``"bibtex"``. Defaults to ``"bibtex"`` when the key
    is absent or holds an unrecognized value, which is the safer baseline for
    constructed entries (``@misc`` is valid in both dialects).
    """
    for key, value in lib.metadata.items():
        if key.lower() == "databasetype":
            normalized = value.strip().rstrip(";").strip().lower()
            return "biblatex" if normalized == "biblatex" else "bibtex"
    return "bibtex"


def default_namespace(key: str) -> str:
    """Return the namespace a key should be written to by default.

    JabRef-native keys go to ``jabref`` (so JabRef keeps seeing them); settings
    JabRef cannot represent (pynakes-specific or unrecognized) go to
    ``pynakes``. This maximizes JabRef compatibility while letting pynakes own
    the keys JabRef has no place for.
    """
    return "jabref" if metadata_owner(key) == "jabref" else "pynakes"


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
        value = value.strip().rstrip(";").strip()
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
    When ``None`` (the default), the key is routed automatically — JabRef-native
    keys to ``jabref-meta`` (maximum compatibility), everything else to
    ``pynakes-meta`` (pynakes' superset). Writes into ``jabref-meta`` still
    reject keys JabRef will not understand unless ``allow_unknown`` is set;
    ``pynakes-meta`` accepts any key, since it is pynakes' own namespace. If
    multiple existing blocks in the target namespace match the key, the update
    is refused because choosing one would be ambiguous.
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")

    if namespace is None:
        namespace = default_namespace(key)
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
