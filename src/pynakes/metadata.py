"""Structured support for JabRef library metadata comments.

JabRef stores library-level settings as top-level comments:

``@comment{jabref-meta: key:value;}``

The raw comments must be preserved for round-trip fidelity, but callers also
need structured access for inspection and safe edits. This module keeps both:
``JabRefMetadataBlock.raw`` is the exact comment text stored in the library,
while ``key`` and ``value`` expose the parsed payload.
"""

import re
from dataclasses import dataclass, field

from pynakes.model import BibFile, JabRefMetadataBlock

KNOWN_EXACT_KEYS = {
    "databasetype": "library",
    "saveorderconfig": "save",
    "saveorder": "save",
    "saveactions": "save",
    "blgfilepath": "library",
    "grouping": "groups",
    "groupstree": "groups",
    "groups": "groups",
    "groupsversion": "groups",
    "groups-search-syntax-version": "groups",
    "protectedflag": "library",
    "versiondbstructure": "library",
    "keypatterndefault": "citation-key",
    # pynakes normalization settings written with the canonical bare prefix.
    "protected-terms": "pynakes",
    "journal-table": "pynakes",
    "ltwa-table": "pynakes",
}

KNOWN_PREFIXES = {
    "filedirectory": "files",
    "selector_": "selectors",
    "keypattern_": "citation-key",
    # pynakes' own settings: the canonical ``normalize-`` prefix and the older
    # ``pynakes-`` spelling (which also covers the ``pynakes-normalize-`` alias).
    "normalize-": "pynakes",
    "pynakes-": "pynakes",
}

# The two structurally identical metadata comment namespaces.
JABREF_PREFIX = "jabref-meta:"
PYNAKES_PREFIX = "pynakes-meta:"

# Categories that JabRef itself understands. Keys in these categories are
# written to ``jabref-meta`` by default (maximum JabRef compatibility); keys
# JabRef cannot represent (pynakes-specific or unrecognized) go to
# ``pynakes-meta``.
JABREF_CATEGORIES = {"library", "save", "groups", "citation-key", "files", "selectors"}


class DuplicateJabRefMetadataError(Exception):
    """Raised when a metadata update would be ambiguous."""

    def __init__(self, key: str, count: int):
        self.key = key
        self.count = count
        super().__init__(f"Cannot safely update {key!r}: found {count} matching blocks")


@dataclass
class JabRefMetadataUpdate:
    """One safe replacement or insertion of a top-level JabRef metadata block.

    ``old_raw`` and ``new_raw`` are retained so :class:`~pynakes.engine.Collection`
    can splice the comment into the original file instead of rewriting it.
    """

    key: str
    value: str
    old_raw: str | None
    new_raw: str
    created: bool
    namespace: str = "jabref"


def metadata_category(key: str) -> str:
    """Return the known metadata category for ``key``, or ``unknown``."""
    normalized = key.lower()
    if normalized in KNOWN_EXACT_KEYS:
        return KNOWN_EXACT_KEYS[normalized]
    for prefix, category in KNOWN_PREFIXES.items():
        if normalized.startswith(prefix):
            return category
    return "unknown"


def is_known_metadata_key(key: str) -> bool:
    """Return whether ``key`` is a recognized JabRef/pynakes metadata key."""
    return metadata_category(key) != "unknown"


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


def default_namespace(key: str) -> str:
    """Return the namespace a key should be written to by default.

    JabRef-native keys go to ``jabref`` (so JabRef keeps seeing them); settings
    JabRef cannot represent (pynakes-specific or unrecognized) go to
    ``pynakes``. This maximizes JabRef compatibility while letting pynakes own
    the keys JabRef has no place for.
    """
    return "jabref" if metadata_category(key) in JABREF_CATEGORIES else "pynakes"


def parse_jabref_metadata_comment(
    comment_text: str,
    *,
    raw: str | None = None,
    comment_index: int = -1,
) -> JabRefMetadataBlock | None:
    """Parse a top-level JabRef metadata comment.

    ``comment_text`` is the content inside ``@comment{...}``. ``raw`` should be
    the full raw comment when available; it is used for precise replacements.
    Both the ``jabref-meta:`` and ``pynakes-meta:`` namespaces are recognized.
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
        return None

    body = stripped[len(prefix) :].strip()
    if not body:
        return None

    key, sep, value = body.partition(":")
    if not sep:
        return None

    key = key.strip()
    value = value.strip()
    category = metadata_category(key)
    return JabRefMetadataBlock(
        key=key,
        value=value,
        raw=raw if raw is not None else f"@comment{{{comment_text}}}",
        comment_index=comment_index,
        known=category != "unknown",
        category=category,
        namespace=namespace,
    )


def metadata_blocks_to_dict(blocks: list[JabRefMetadataBlock]) -> dict[str, str]:
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


def consolidate_metadata(lib: BibFile, text: str, line_ending: str = "\n") -> str | None:
    """Relocate every metadata comment into one canonical section at file end.

    JabRef writes its ``@Comment{jabref-meta: ...}`` blocks contiguously at the
    bottom of the file, sorted by key. A library that has been hand-edited (or
    had entries appended after a JabRef save) ends up with metadata stranded in
    the middle. This gathers all jabref-meta/pynakes-meta blocks — preserving
    each block's content verbatim, including JabRef's multi-line ``grouping``
    formatting — and rewrites them as a single sorted section at the end,
    separated from the entries and from each other by one blank line.

    Returns the rewritten text, or ``None`` when the file is already in this
    canonical layout (so callers can treat it as a no-op).
    """
    blocks = lib.metadata_blocks
    if not blocks:
        return None

    stripped = text
    for block in blocks:
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

    # jabref-meta first (keeps JabRef's own keys grouped), then pynakes-meta;
    # alphabetical by key within each, stable for repeated keys (legacy groups).
    ordered = sorted(
        enumerate(blocks),
        key=lambda pair: (0 if pair[1].namespace == "jabref" else 1, pair[1].key.lower(), pair[0]),
    )
    section = (line_ending + line_ending).join(block.raw for _, block in ordered)

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
) -> JabRefMetadataUpdate:
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

    if namespace == "jabref" and not allow_unknown and not is_known_metadata_key(key):
        raise ValueError(
            f"Unknown JabRef metadata key {key!r}; pass --allow-unknown to write it to "
            "jabref-meta, or write it to pynakes-meta instead"
        )

    blocks = lib.jabref_metadata_blocks if namespace == "jabref" else lib.pynakes_metadata_blocks

    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if len(matches) > 1:
        raise DuplicateJabRefMetadataError(key, len(matches))

    new_raw = format_metadata_comment(key, value, namespace)
    new_block = parse_jabref_metadata_comment(
        new_raw[new_raw.find("{") + 1 : -1],
        raw=new_raw,
        comment_index=-1,
    )
    if new_block is None:
        raise ValueError(f"Could not render metadata key {key!r}")

    def _refresh() -> None:
        if namespace == "jabref":
            lib.jabref_metadata = metadata_blocks_to_dict(lib.jabref_metadata_blocks)
        else:
            lib.pynakes_metadata = metadata_blocks_to_dict(lib.pynakes_metadata_blocks)

    if not matches:
        new_block.comment_index = len(lib.raw_comments)
        lib.raw_comments.append(new_raw)
        blocks.append(new_block)
        _refresh()
        return JabRefMetadataUpdate(
            key=key,
            value=new_block.value,
            old_raw=None,
            new_raw=new_raw,
            created=True,
            namespace=namespace,
        )

    old = matches[0]
    new_block.comment_index = old.comment_index
    if old.comment_index >= 0 and old.comment_index < len(lib.raw_comments):
        lib.raw_comments[old.comment_index] = new_raw
    blocks[blocks.index(old)] = new_block
    _refresh()
    return JabRefMetadataUpdate(
        key=key,
        value=new_block.value,
        old_raw=old.raw,
        new_raw=new_raw,
        created=False,
        namespace=namespace,
    )
