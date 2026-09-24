"""Remove private content from a library before it is released publicly.

A working bibliography carries more than bibliographic record: reading state and
priorities, local filesystem paths, personal notes, the group tree that
organizes someone's own library, and the settings blocks the tooling keeps. None
of that belongs in the ``.bib`` uploaded with a preprint, shipped in a submission
bundle, or committed to a public repository — and what exactly counts as private
is the library owner's call, not this module's.

Three kinds of content are scrubbed, each independently switchable:

- **entry fields** — bookkeeping (``owner``, ``timestamp``), reading state
  (``priority``, ``readstatus``), personal annotation (``annote``, ``comment``),
  local paths (``file``, ``bdsk-file-N``), and group membership (``groups``).
  :data:`DEFAULT_PRIVATE_FIELDS` is the default set; a library extends or
  narrows it via options or its own ``scrub-fields`` / ``scrub-keep-fields``
  metadata. Names are matched case-insensitively and may use ``*`` globs.
- **metadata blocks** — every ``jabref-meta``/``pynakes-meta`` comment: the
  group tree, save configuration, selectors, and the Pinax material directory
  (a local path).
- **free comments** — ``@comment{...}`` blocks and ``%`` lines that are not
  metadata, where working notes tend to accumulate.

Fields are removed through :mod:`pynakes.editing`, so only the removed line
changes in an entry. Comment slots are blanked in place rather than deleted so
existing ``comment_index``/layout references stay valid; the engine turns a
blanked slot into a surgical source deletion that also folds away the blank line
it would otherwise leave behind. Everything not named stays byte-for-byte
identical, which is what makes the released file reviewable as a diff of its
source.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from pynakes.editing import remove_entry_field
from pynakes.metadata import metadata_bool, metadata_list_values, metadata_value
from pynakes.model import BibFile

#: Entry fields removed unless a library says otherwise. Bibliographic content
#: is never in this set: ``abstract``, ``keywords``, and ``note`` carry meaning
#: a reader may want and are dropped only when asked for explicitly.
DEFAULT_PRIVATE_FIELDS: tuple[str, ...] = (
    # Reference-manager bookkeeping.
    "owner",
    "timestamp",
    "creationdate",
    "modificationdate",
    "__markedentry",
    # Personal annotation and reading state.
    "annote",
    "annotation",
    "comment",
    "review",
    "priority",
    "ranking",
    "readstatus",
    "relevance",
    "printed",
    "qualityassured",
    # Local filesystem paths.
    "file",
    "pdf",
    "local-url",
    "bdsk-file-*",
    # Organizational membership in someone's own library.
    "groups",
)

#: Additional private field names/globs declared by the library itself.
SCRUB_FIELDS_KEY = "scrub-fields"
#: Field names/globs this library keeps despite the default set (``*`` keeps all).
SCRUB_KEEP_FIELDS_KEY = "scrub-keep-fields"
#: Whether scrubbing removes free comment blocks (default true).
SCRUB_COMMENTS_KEY = "scrub-comments"
#: Whether scrubbing removes metadata blocks (default true).
SCRUB_METADATA_KEY = "scrub-metadata"


@dataclass(frozen=True)
class ScrubOptions:
    """What one scrub run removes.

    Each of ``fields``, ``comments``, and ``metadata`` is a three-state switch:
    ``None`` defers to the library's own ``scrub-*`` metadata and then to the
    default (on), while ``True``/``False`` is an explicit caller decision.
    ``fields`` has no metadata off-switch of its own — ``scrub-fields`` holds a
    list of extra names, so a library turns field scrubbing off with
    ``scrub-keep-fields: *``. ``extra_fields`` and ``keep_fields`` are *added
    to* whatever the library declares rather than replacing it, so a caller
    never silently loses a policy the library recorded.
    """

    extra_fields: tuple[str, ...] = ()
    keep_fields: tuple[str, ...] = ()
    fields: bool | None = None
    comments: bool | None = None
    metadata: bool | None = None


@dataclass
class ScrubReport:
    """What one scrub run removed (or would remove).

    ``fields`` counts entries per concrete field name — the name as it appeared
    in the file, not the glob that matched it — so a report names what actually
    left the library. ``removed_comment_indices`` is the engine's handle on the
    blanked comment slots and is not part of the human-facing summary.
    """

    fields: dict[str, int] = field(default_factory=dict)
    entries: int = 0
    metadata_keys: list[str] = field(default_factory=list)
    metadata_blocks: int = 0
    comments: int = 0
    removed_comment_indices: list[int] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def field_removals(self) -> int:
        """Total number of field values removed across all entries."""
        return sum(self.fields.values())

    @property
    def clean(self) -> bool:
        """Whether nothing matched — the library is already fit to release."""
        return not (self.fields or self.metadata_blocks or self.comments)

    def to_dict(self) -> dict[str, object]:
        """Serialize the report to a JSON-friendly dict."""
        return {
            "fields": [{"field": name, "entries": count} for name, count in self.fields.items()],
            "field_removals": self.field_removals,
            "entries": self.entries,
            "metadata_keys": list(self.metadata_keys),
            "metadata_blocks": self.metadata_blocks,
            "comments": self.comments,
            "clean": self.clean,
        }


def _split_names(values: tuple[str, ...] | list[str] | None) -> list[str]:
    """Split comma-separated and repeated name options into one clean list."""
    names: list[str] = []
    for value in values or ():
        names.extend(part.strip().lower() for part in value.split(",") if part.strip())
    return names


def _dedupe(names: list[str]) -> list[str]:
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def resolve_private_fields(lib: BibFile, options: ScrubOptions) -> list[str]:
    """Return the effective private-field patterns for ``lib``.

    The default set, plus anything the library's ``scrub-fields`` metadata
    declares, plus the caller's ``extra_fields``. Returns an empty list when
    field scrubbing is off, so a caller can report "fields: off" rather than
    "fields: none matched".
    """
    if options.fields is False:
        return []
    patterns = list(DEFAULT_PRIVATE_FIELDS)
    patterns.extend(_split_names(metadata_list_values(lib, SCRUB_FIELDS_KEY)))
    patterns.extend(_split_names(options.extra_fields))
    return _dedupe(patterns)


def resolve_keep_fields(lib: BibFile, options: ScrubOptions) -> list[str]:
    """Return the field patterns kept despite matching the private set."""
    keep = _split_names(metadata_list_values(lib, SCRUB_KEEP_FIELDS_KEY))
    keep.extend(_split_names(options.keep_fields))
    return _dedupe(keep)


def _resolve_switch(lib: BibFile, option: bool | None, key: str) -> bool:
    """Resolve a three-state switch: explicit option, then metadata, then on."""
    if option is not None:
        return option
    return metadata_bool(metadata_value(lib, key), True)


def _matches(name: str, patterns: list[str]) -> bool:
    """Whether a field name matches any pattern, case-insensitively, with globs."""
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in patterns)


def _scrub_fields(lib: BibFile, patterns: list[str], keep: list[str]) -> tuple[dict[str, int], int]:
    """Remove matching fields from every entry; return per-field counts and entries."""
    counts: dict[str, int] = {}
    entries = 0
    for entry in lib.entries.values():
        touched = False
        for name in list(entry.fields):
            if not _matches(name, patterns) or _matches(name, keep):
                continue
            if remove_entry_field(entry, name):
                counts[name] = counts.get(name, 0) + 1
                touched = True
        entries += int(touched)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))), entries


def _metadata_comment_indices(lib: BibFile) -> dict[int, list[str]]:
    """Map each comment slot holding metadata to the keys it declares."""
    slots: dict[int, list[str]] = {}
    for block in lib.metadata_blocks:
        slots.setdefault(block.comment_index, []).append(block.key)
    return slots


def scrub_library(lib: BibFile, options: ScrubOptions | None = None) -> ScrubReport:
    """Remove private content from ``lib`` in place and report what went.

    Mutates the library and returns a :class:`ScrubReport`; it does not write
    anything. Callers that need the removal reflected in a file go through
    :meth:`pynakes.engine.Bibliography.scrub`, which stages the blanked comment
    slots as surgical source deletions.
    """
    opts = options or ScrubOptions()
    report = ScrubReport()

    patterns = resolve_private_fields(lib, opts)
    report.patterns = patterns
    if patterns:
        keep = resolve_keep_fields(lib, opts)
        report.fields, report.entries = _scrub_fields(lib, patterns, keep)

    scrub_metadata = _resolve_switch(lib, opts.metadata, SCRUB_METADATA_KEY)
    scrub_comments = _resolve_switch(lib, opts.comments, SCRUB_COMMENTS_KEY)
    metadata_slots = _metadata_comment_indices(lib)

    removed: list[int] = []
    for index, comment in enumerate(lib.raw_comments):
        if not comment:
            # An already-blank slot is a placeholder from an earlier removal.
            continue
        if index in metadata_slots:
            if not scrub_metadata:
                continue
            # JabRef writes one ``groups:`` comment per node, so the same key
            # names several blocks; the count says how many, the key list says
            # which settings left.
            report.metadata_keys.extend(
                key for key in metadata_slots[index] if key not in report.metadata_keys
            )
            report.metadata_blocks += 1
        else:
            if not scrub_comments:
                continue
            report.comments += 1
        lib.raw_comments[index] = ""
        removed.append(index)

    if scrub_metadata:
        lib.jabref_metadata_blocks = [
            block for block in lib.jabref_metadata_blocks if block.comment_index not in removed
        ]
        lib.pynakes_metadata_blocks = [
            block for block in lib.pynakes_metadata_blocks if block.comment_index not in removed
        ]
    report.removed_comment_indices = removed
    return report
