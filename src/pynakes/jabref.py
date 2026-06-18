"""Structured support for JabRef library metadata comments.

JabRef stores library-level settings as top-level comments:

``@comment{jabref-meta: key:value;}``

The raw comments must be preserved for round-trip fidelity, but callers also
need structured access for inspection and safe edits. This module keeps both:
``JabRefMetadataBlock.raw`` is the exact comment text stored in the library,
while ``key`` and ``value`` expose the parsed payload.
"""

from dataclasses import dataclass

from pynakes.model import BibLibrary, JabRefMetadataBlock

KNOWN_EXACT_KEYS = {
    "databasetype": "library",
    "saveorderconfig": "save",
    "saveactions": "save",
    "grouping": "groups",
    "groupstree": "groups",
    "groups": "groups",
    "groupsversion": "groups",
    "groups-search-syntax-version": "groups",
    "protectedflag": "library",
    "versiondbstructure": "library",
    "keypatterndefault": "citation-key",
}

KNOWN_PREFIXES = {
    "filedirectory": "files",
    "selector_": "selectors",
    "keypattern_": "citation-key",
    "pynakes-": "pynakes",
}


class DuplicateJabRefMetadataError(Exception):
    """Raised when a metadata update would be ambiguous."""

    def __init__(self, key: str, count: int):
        self.key = key
        self.count = count
        super().__init__(f"Cannot safely update {key!r}: found {count} matching blocks")


@dataclass
class JabRefMetadataUpdate:
    """Result of a JabRef metadata update."""

    key: str
    value: str
    old_raw: str | None
    new_raw: str
    created: bool


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


def parse_jabref_metadata_comment(
    comment_text: str,
    *,
    raw: str | None = None,
    comment_index: int = -1,
) -> JabRefMetadataBlock | None:
    """Parse a top-level JabRef metadata comment.

    ``comment_text`` is the content inside ``@comment{...}``. ``raw`` should be
    the full raw comment when available; it is used for precise replacements.
    """
    prefix = "jabref-meta:"
    stripped = comment_text.strip()
    if stripped.startswith("{"):
        stripped = stripped[1:].strip()
    if not stripped.lower().startswith(prefix):
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
    )


def metadata_blocks_to_dict(blocks: list[JabRefMetadataBlock]) -> dict[str, str]:
    """Return the backward-compatible flat metadata dict.

    Later blocks win, matching the historical parser behavior.
    """
    result: dict[str, str] = {}
    for block in blocks:
        result[block.key] = block.value
    return result


def format_metadata_comment(key: str, value: str) -> str:
    """Render a canonical JabRef metadata comment for ``key`` and ``value``."""
    value = value.strip()
    if value and not value.endswith(";"):
        value = f"{value};"
    return f"@comment{{jabref-meta: {key.strip()}:{value}}}"


def set_metadata(
    lib: BibLibrary,
    key: str,
    value: str,
    *,
    allow_unknown: bool = False,
) -> JabRefMetadataUpdate:
    """Set one JabRef metadata value, updating raw comments in place.

    Unknown keys are rejected by default so automated callers do not silently
    create metadata JabRef will not understand. If multiple existing blocks
    match the key, the update is refused because choosing one would be
    ambiguous.
    """
    key = key.strip()
    if not key:
        raise ValueError("metadata key must not be empty")
    if not allow_unknown and not is_known_metadata_key(key):
        raise ValueError(
            f"Unknown JabRef metadata key {key!r}; pass --allow-unknown to set it anyway"
        )

    matches = [b for b in lib.jabref_metadata_blocks if b.key.lower() == key.lower()]
    if len(matches) > 1:
        raise DuplicateJabRefMetadataError(key, len(matches))

    new_raw = format_metadata_comment(key, value)
    new_block = parse_jabref_metadata_comment(
        new_raw[new_raw.find("{") + 1 : -1],
        raw=new_raw,
        comment_index=-1,
    )
    if new_block is None:
        raise ValueError(f"Could not render JabRef metadata key {key!r}")

    if not matches:
        new_block.comment_index = len(lib.raw_comments)
        lib.raw_comments.append(new_raw)
        lib.jabref_metadata_blocks.append(new_block)
        lib.jabref_metadata = metadata_blocks_to_dict(lib.jabref_metadata_blocks)
        return JabRefMetadataUpdate(
            key=key,
            value=new_block.value,
            old_raw=None,
            new_raw=new_raw,
            created=True,
        )

    old = matches[0]
    new_block.comment_index = old.comment_index
    if old.comment_index >= 0 and old.comment_index < len(lib.raw_comments):
        lib.raw_comments[old.comment_index] = new_raw
    old_index = lib.jabref_metadata_blocks.index(old)
    lib.jabref_metadata_blocks[old_index] = new_block
    lib.jabref_metadata = metadata_blocks_to_dict(lib.jabref_metadata_blocks)
    return JabRefMetadataUpdate(
        key=key,
        value=new_block.value,
        old_raw=old.raw,
        new_raw=new_raw,
        created=False,
    )
