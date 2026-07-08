"""Set operations over ``.bib`` libraries: merge (combine) and split (partition).

These are stateless, deterministic projections — read-only inputs in, new
libraries out — generalizing the cited-subset export in :mod:`pynakes.usage`.
They operate on whole files (no index, no persistent state), so they belong to
the single-file engine rather than the future corpus ``Library``.

``merge_libraries`` concatenates several libraries into one (optionally deduping
entries that share a citation key). ``partition_library`` routes each entry of a
working library to one or more output buckets selected by a predicate. The
predicate language is :func:`pynakes.fields.parse_query` extended with ``*``
(any), ``used`` / ``unused`` (against a cited-key set), and ``group "Name"``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from pynakes import groups as group_ops
from pynakes.fields import parse_query
from pynakes.model import BibEntry, BibFile

Predicate = Callable[[BibEntry], bool]


# --- merge -----------------------------------------------------------------


@dataclass
class MergeResult:
    """Outcome of combining several libraries.

    ``lib`` keeps the first occurrence of each conflicting key, so it is usable
    for preview, but a caller must treat ``conflicts`` as a stop condition (don't
    write) until they are resolved. ``duplicate_keys`` lists keys present more
    than once after merging (always populated; advisory).
    """

    lib: BibFile
    inputs: list[str]
    duplicate_keys: list[str] = field(default_factory=list)
    conflicts: list[dict[str, object]] = field(default_factory=list)


def _entry_identity(entry: BibEntry) -> tuple[str, tuple[tuple[str, str], ...], str | None]:
    """A content fingerprint for dedupe: semantics plus preserved raw spelling."""
    return (entry.type.lower(), tuple(sorted(entry.fields.items())), entry.raw_content)


def merge_libraries(named_libs: list[tuple[str, BibFile]], *, dedupe: bool = False) -> MergeResult:
    """Combine libraries (in order) into one.

    Without ``dedupe`` every entry is kept, in input order — duplicate citation
    keys are tolerated (pynakes' invariant) and reported in ``duplicate_keys``.
    With ``dedupe`` entries that share a key are collapsed when their content is
    identical; when they differ it is a conflict (recorded, not guessed) and the
    first occurrence is kept in ``lib``. Library-level data comes from the first
    input.
    """
    if not named_libs:
        raise ValueError("merge requires at least one input library")

    context = named_libs[0][1]
    kept: list[BibEntry] = []
    first_index: dict[str, int] = {}
    seen_count: dict[str, int] = {}
    conflicts: list[dict[str, object]] = []

    for source, lib in named_libs:
        for entry in lib.entries.values():
            seen_count[entry.key] = seen_count.get(entry.key, 0) + 1
            if not dedupe:
                kept.append(entry)
                continue
            if entry.key not in first_index:
                first_index[entry.key] = len(kept)
                kept.append(entry)
                continue
            existing = kept[first_index[entry.key]]
            if _entry_identity(existing) != _entry_identity(entry):
                conflicts.append({"key": entry.key, "source": source})

    duplicate_keys = sorted(k for k, n in seen_count.items() if n > 1)
    return MergeResult(
        lib=context.derive(kept),
        inputs=[name for name, _ in named_libs],
        duplicate_keys=duplicate_keys,
        conflicts=conflicts,
    )


def strip_metadata_blocks(lib: BibFile) -> BibFile:
    """Drop ``jabref-meta``/``pynakes-meta`` comment blocks from ``lib`` in place.

    For a bucket meant as a standalone snippet (e.g. one entry pulled out via
    ``split``), the source library's groups, save-order config, and Pinax
    fetch settings are noise: they describe the whole original library, not
    the bucket. Returns ``lib`` for chaining.
    """
    meta_indices = {
        block.comment_index for block in (*lib.jabref_metadata_blocks, *lib.pynakes_metadata_blocks)
    }
    lib.raw_comments = [
        comment for index, comment in enumerate(lib.raw_comments) if index not in meta_indices
    ]
    lib.jabref_metadata_blocks = []
    lib.pynakes_metadata_blocks = []
    return lib


# --- predicates ------------------------------------------------------------


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def compile_predicate(expr: str, cited_keys: set[str] | None = None) -> Predicate:
    """Compile one bucket predicate into a callable over entries.

    Grammar (one predicate per bucket):

    - ``*`` — matches every entry (use as a catch-all / "rest" bucket).
    - ``used`` / ``unused`` — citation key is / is not in ``cited_keys``.
    - ``group "Name"`` — entry belongs to the named JabRef group.
    - anything else — a :func:`pynakes.fields.parse_query` field expression
      (``title contains "x"``, ``type = article``, ``doi exists`` …).
    """
    text = expr.strip()
    if text == "*":
        return lambda _entry: True

    lowered = text.lower()
    if lowered in {"used", "unused"}:
        keys = cited_keys
        if keys is None:
            raise ValueError(f"predicate {expr!r} needs cited keys; pass --tex/--aux sources")
        if lowered == "used":
            return lambda entry: entry.key in keys
        return lambda entry: entry.key not in keys

    if lowered.startswith("group ") or lowered.startswith("group="):
        name = _unquote(text[len("group") :].lstrip(" ="))
        if not name:
            raise ValueError(f"predicate {expr!r} needs a group name")
        return lambda entry: name in group_ops.entry_groups(entry)

    return parse_query(text)


# --- partition -------------------------------------------------------------


@dataclass
class PartitionRule:
    """One output bucket: a destination ``label`` and its selector ``predicate``."""

    label: str
    predicate: str


@dataclass
class PartitionResult:
    """Outcome of splitting one library into labelled buckets.

    ``buckets`` maps each rule label to its output library, in rule order.
    ``counts`` is the entry count per label; ``unrouted`` is how many entries
    matched no bucket (only possible without a ``*`` rule and without ``copy``).
    """

    buckets: dict[str, BibFile]
    counts: dict[str, int]
    unrouted: int


def partition_library(
    lib: BibFile,
    rules: list[PartitionRule],
    *,
    copy: bool = False,
    cited_keys: set[str] | None = None,
) -> PartitionResult:
    """Route each entry of ``lib`` to output buckets defined by ``rules``.

    By default routing is *first match*: each entry goes to the first rule whose
    predicate matches (rule order), making the outputs a partition. With
    ``copy=True`` an entry is sent to **every** matching bucket, so outputs may
    overlap. Library-level data is copied into each bucket from ``lib``.
    """
    if not rules:
        raise ValueError("split requires at least one --to rule")

    compiled = [(rule.label, compile_predicate(rule.predicate, cited_keys)) for rule in rules]
    collected: dict[str, list[BibEntry]] = {rule.label: [] for rule in rules}
    unrouted = 0

    for entry in lib.entries.values():
        matched = False
        for label, predicate in compiled:
            if predicate(entry):
                collected[label].append(entry)
                matched = True
                if not copy:
                    break
        if not matched:
            unrouted += 1

    buckets = {label: lib.derive(entries) for label, entries in collected.items()}
    counts = {label: len(entries) for label, entries in collected.items()}
    return PartitionResult(buckets=buckets, counts=counts, unrouted=unrouted)
