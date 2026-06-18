"""Data models for BibTeX library representation."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class JabRefMetadataBlock:
    """Structured representation of one ``jabref-meta`` comment block."""

    key: str
    value: str
    raw: str
    comment_index: int
    known: bool = False
    category: str = "unknown"

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
        }


@dataclass
class BibEntry:
    """Represents a single BibTeX entry."""

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


class EntryCollection:
    """Ordered collection of BibEntry objects that tolerates duplicate keys.

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
        entries: Union["EntryCollection", dict[str, BibEntry], list[BibEntry], None] = None,
    ) -> None:
        self._entries: list[BibEntry] = []
        if entries is None:
            return
        if isinstance(entries, EntryCollection):
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
        return f"EntryCollection({len(self._entries)} entries{suffix})"


@dataclass
class BibLibrary:
    """Represents a complete BibTeX library."""

    entries: EntryCollection = field(default_factory=EntryCollection)
    strings: dict[str, str] = field(default_factory=dict)
    preamble: list[str] = field(default_factory=list)
    raw_comments: list[str] = field(default_factory=list)
    jabref_metadata: dict[str, str] = field(default_factory=dict)
    jabref_metadata_blocks: list[JabRefMetadataBlock] = field(default_factory=list)
    encoding: str = "utf-8"
    line_ending: str = "\n"

    def __post_init__(self) -> None:
        # Allow constructing from a dict or list for ergonomics/back-compat.
        if not isinstance(self.entries, EntryCollection):
            self.entries = EntryCollection(self.entries)

    def to_dict(self) -> dict:
        """Serialize the library to a JSON-friendly dict."""
        return {
            "entries": self.entries.to_dict(),
            "strings": dict(self.strings),
            "preamble": list(self.preamble),
            "raw_comments": list(self.raw_comments),
            "jabref_metadata": dict(self.jabref_metadata),
            "jabref_metadata_blocks": [block.to_dict() for block in self.jabref_metadata_blocks],
            "encoding": self.encoding,
            "line_ending": self.line_ending,
        }

    def __repr__(self) -> str:
        """Return a debug representation of the library."""
        return (
            f"BibLibrary(entries={len(self.entries)}, "
            f"strings={len(self.strings)}, "
            f"preamble={len(self.preamble)}, "
            f"encoding={self.encoding!r}, "
            f"line_ending={self.line_ending!r})"
        )
