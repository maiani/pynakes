"""Data models representing one parsed BibTeX file."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional, Union

# A bare BibTeX string reference: an identifier with no surrounding braces or
# quotes that may resolve to a @string definition.
_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")


def resolve_field_value(value: str, strings: dict[str, str]) -> str:
    """Resolve @string references and # concatenation in a field value.

    Returns the expanded string for semantic comparison (journal lookup,
    validation) without mutating the stored value — @string references in the
    file are always preserved on write.

    Handles:
    - Bare identifier matching a @string key: ``NMI`` → ``Nature Mach. Intell.``
    - ``#`` concatenation: ``NMI # " Supplement"`` → ``Nature Mach. Intell. Supplement``
    - Everything else: returned unchanged.
    """
    if not strings:
        return value
    if "#" in value:
        parts = [p.strip() for p in value.split("#")]
        resolved = []
        for part in parts:
            if part in strings:
                resolved.append(strings[part])
            elif (part.startswith("{") and part.endswith("}")) or (
                part.startswith('"') and part.endswith('"')
            ):
                resolved.append(part[1:-1])
            else:
                resolved.append(part)
        return "".join(resolved)
    if _BARE_IDENTIFIER.match(value):
        return strings.get(value, value)
    return value


def is_string_ref(value: str, strings: dict[str, str]) -> bool:
    """Return True if *value* is a bare @string reference (not a literal)."""
    return bool(_BARE_IDENTIFIER.match(value)) and value in strings


@dataclass
class MetadataBlock:
    """Structured representation of one metadata comment block.

    pynakes recognizes two structurally identical comment namespaces:
    ``@comment{jabref-meta: key:value;}`` (JabRef's own) and
    ``@comment{pynakes-meta: key:value;}`` (pynakes' superset, for settings
    JabRef cannot represent). ``namespace`` records which one this block came
    from; everything else is identical between the two.
    """

    key: str
    value: str
    raw: str
    comment_index: int
    known: bool = False
    category: str = "unknown"
    namespace: str = "jabref"  # "jabref" | "pynakes"

    @property
    def normalized_value(self) -> str:
        """Return the metadata value without JabRef's trailing semicolon."""
        return self.value.strip().rstrip(";").strip()

    def to_dict(self) -> dict[str, object]:
        """Serialize the block to a JSON-friendly dict."""
        return {
            "key": self.key,
            "value": self.normalized_value,
            "raw_value": self.value,
            "known": self.known,
            "category": self.category,
            "namespace": self.namespace,
        }


@dataclass
class BibEntry:
    """One bibliographic record and its preservation state.

    ``fields`` is deliberately open-ended: it holds standard BibTeX/BibLaTeX
    fields and user-defined fields alike. ``raw_content`` is the original
    entry text used to retain formatting for untouched entries; mutation
    helpers in :mod:`pynakes.editing` keep it synchronized with ``fields``.
    ``modified`` selects writer reconstruction only when no surgical raw edit
    is available.
    """

    key: str
    type: str
    fields: dict[str, str]
    raw_content: Optional[str] = None
    raw_comments: list[str] = field(default_factory=list)
    jabref_metadata: dict[str, str] = field(default_factory=dict)
    modified: bool = False

    def __repr__(self) -> str:
        """Return a debug representation of the entry."""
        field_preview = ", ".join(
            f"{k}={v[:20]}..." if len(v) > 20 else f"{k}={v}"
            for k, v in list(self.fields.items())[:3]
        )
        return (
            f"BibEntry(key={self.key!r}, type={self.type!r}, "
            f"fields={{{field_preview}{'...' if len(self.fields) > 3 else ''}}}, "
            f"modified={self.modified})"
        )


class EntryStore:
    """Ordered store of BibEntry objects that tolerates duplicate keys.

    Bibliography files in the wild contain duplicate citation keys, and
    detecting/repairing them is a core feature. A plain ``dict`` keyed by
    citation key cannot represent that, so this container stores entries in an
    ordered list while exposing a dict-like read API (first match wins) for
    ergonomic access. Iterate :meth:`values` to see *every* entry, including
    duplicates; use :meth:`get_all` and :meth:`duplicate_keys` to work with the
    duplicates explicitly.
    """

    def __init__(
        self,
        entries: Union["EntryStore", dict[str, BibEntry], list[BibEntry], None] = None,
    ) -> None:
        self._entries: list[BibEntry] = []
        if entries is None:
            return
        if isinstance(entries, EntryStore):
            self._entries = list(entries._entries)
        elif isinstance(entries, dict):
            self._entries = list(entries.values())
        else:
            self._entries = list(entries)

    # --- list semantics over all entries (including duplicates) ---

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        """Iterate citation keys in order (dict-like; duplicates repeat)."""
        return (entry.key for entry in self._entries)

    def keys(self) -> list[str]:
        """Return all citation keys in order (duplicates included)."""
        return [entry.key for entry in self._entries]

    def values(self) -> list[BibEntry]:
        """Return all entries in order (duplicates included)."""
        return list(self._entries)

    def items(self) -> list[tuple[str, BibEntry]]:
        """Return ``(key, entry)`` pairs in order (duplicates included)."""
        return [(entry.key, entry) for entry in self._entries]

    # --- dict-like access (first match wins) ---

    def __contains__(self, key: str) -> bool:
        return any(entry.key == key for entry in self._entries)

    def __getitem__(self, key: str) -> BibEntry:
        for entry in self._entries:
            if entry.key == key:
                return entry
        raise KeyError(key)

    def __setitem__(self, key: str, entry: BibEntry) -> None:
        """Replace the first entry with ``key``, or append if none exists."""
        for i, existing in enumerate(self._entries):
            if existing.key == key:
                self._entries[i] = entry
                return
        self._entries.append(entry)

    def get(self, key: str, default: Optional[BibEntry] = None) -> Optional[BibEntry]:
        """Return the first entry with ``key``, or ``default``."""
        for entry in self._entries:
            if entry.key == key:
                return entry
        return default

    # --- duplicate-aware helpers ---

    def add(self, entry: BibEntry) -> None:
        """Append an entry, preserving any existing entry with the same key."""
        self._entries.append(entry)

    def remove(self, entry: BibEntry) -> None:
        """Remove one entry object from the store."""
        self._entries.remove(entry)

    def get_all(self, key: str) -> list[BibEntry]:
        """Return every entry with the given citation key, in order."""
        return [entry for entry in self._entries if entry.key == key]

    def duplicate_keys(self) -> dict[str, int]:
        """Return ``{key: count}`` for keys that appear more than once."""
        counts: dict[str, int] = {}
        for entry in self._entries:
            counts[entry.key] = counts.get(entry.key, 0) + 1
        return {key: count for key, count in counts.items() if count > 1}

    def to_dict(self) -> dict[str, dict]:
        """Serialize to a JSON-friendly dict keyed by citation key.

        Duplicate keys collapse to the last occurrence; use this for display
        and structured output, not as a lossless representation.
        """
        from dataclasses import asdict

        return {entry.key: asdict(entry) for entry in self._entries}

    def __repr__(self) -> str:
        dupes = self.duplicate_keys()
        suffix = f", duplicates={dupes}" if dupes else ""
        return f"EntryStore({len(self._entries)} entries{suffix})"


@dataclass
class BibFile:
    """The complete in-memory representation of one ``.bib`` file.

    A ``BibFile`` is a semantic view plus the preservation data needed to write
    it back safely. ``entries`` is an :class:`EntryStore`, so duplicate keys
    remain representable; top-level declarations and comments are retained in
    their own lists. JabRef metadata is available both as ordered raw blocks and
    as a compatibility mapping. Encoding and line-ending metadata let I/O
    reproduce the source file's representation.
    """

    entries: EntryStore = field(default_factory=EntryStore)
    strings: dict[str, str] = field(default_factory=dict)
    preamble: list[str] = field(default_factory=list)
    raw_comments: list[str] = field(default_factory=list)
    # ``jabref_metadata``/``jabref_metadata_blocks`` hold the JabRef namespace
    # only (back-compatible). ``pynakes_metadata``/``pynakes_metadata_blocks``
    # hold pynakes' superset namespace. Use the ``metadata`` property for the
    # effective merged view that consumers read.
    jabref_metadata: dict[str, str] = field(default_factory=dict)
    jabref_metadata_blocks: list[MetadataBlock] = field(default_factory=list)
    pynakes_metadata: dict[str, str] = field(default_factory=dict)
    pynakes_metadata_blocks: list[MetadataBlock] = field(default_factory=list)
    encoding: str = "utf-8"
    line_ending: str = "\n"

    def __post_init__(self) -> None:
        # Allow constructing from a dict or list for ergonomics/back-compat.
        if not isinstance(self.entries, EntryStore):
            self.entries = EntryStore(self.entries)

    @property
    def metadata(self) -> dict[str, str]:
        """Effective merged metadata; ``pynakes-meta`` overrides ``jabref-meta``.

        This is the view operations (``lint``, ``normalize``, key generation)
        should read: pynakes settings take precedence as the authoritative
        namespace, while JabRef-native keys remain visible.
        """
        return {**self.jabref_metadata, **self.pynakes_metadata}

    @property
    def metadata_blocks(self) -> list[MetadataBlock]:
        """All metadata blocks, both namespaces, in source order."""
        return sorted(
            [*self.jabref_metadata_blocks, *self.pynakes_metadata_blocks],
            key=lambda block: block.comment_index,
        )

    def to_dict(self) -> dict:
        """Serialize the bib file to a JSON-friendly dict."""
        return {
            "entries": self.entries.to_dict(),
            "strings": dict(self.strings),
            "preamble": list(self.preamble),
            "raw_comments": list(self.raw_comments),
            "jabref_metadata": dict(self.jabref_metadata),
            "jabref_metadata_blocks": [block.to_dict() for block in self.jabref_metadata_blocks],
            "pynakes_metadata": dict(self.pynakes_metadata),
            "pynakes_metadata_blocks": [block.to_dict() for block in self.pynakes_metadata_blocks],
            "encoding": self.encoding,
            "line_ending": self.line_ending,
        }

    def __repr__(self) -> str:
        """Return a debug representation of the bib file."""
        return (
            f"BibFile(entries={len(self.entries)}, "
            f"strings={len(self.strings)}, "
            f"preamble={len(self.preamble)}, "
            f"encoding={self.encoding!r}, "
            f"line_ending={self.line_ending!r})"
        )
