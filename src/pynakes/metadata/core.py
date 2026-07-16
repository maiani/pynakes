"""Namespace-neutral metadata comment engine.

pynakes recognizes two structurally identical top-level comment namespaces:
``@comment{jabref-meta: key:value;}`` (JabRef's own) and
``@comment{pynakes-meta: key:value;}`` (pynakes' superset, for settings JabRef
cannot represent). This module knows how to parse, format, and surgically edit
both — one comment per key for ``jabref-meta`` (JabRef's own convention), one
consolidated multi-line comment for ``pynakes-meta`` (with continuation-line
support: indented lines append to the previous block's value) — without knowing which
keys belong to which *owner*. That classification (JabRef-native vs
pynakes-owned, and the domain category) is injected by callers via an optional
``classify`` callback; :mod:`pynakes.metadata.schema` is the module that
actually knows the key tables and supplies it. This keeps the mechanics here
reusable independent of pynakes' specific vocabulary.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pynakes._text_utils import strip_meta_terminator
from pynakes.model import BibFile, MetadataBlock

Classifier = Callable[[str], str]


def _unclassified(_key: str) -> str:
    return "unknown"


# The two structurally identical metadata comment namespaces.
JABREF_PREFIX = "jabref-meta:"
PYNAKES_PREFIX = "pynakes-meta:"


def metadata_value(lib: BibFile, name: str) -> str | None:
    """Return the effective metadata value for ``name`` (case-insensitive), without trailing ``;``.

    Searches the library's merged metadata (pynakes-meta overrides jabref-meta).
    Returns ``None`` when the key is absent.
    """
    lowered = {key.lower(): value for key, value in lib.metadata.items()}
    value = lowered.get(name.lower())
    if value is not None:
        return strip_meta_terminator(value)
    return None


def metadata_values(lib: BibFile, name: str) -> tuple[str, ...]:
    """Return all metadata values for ``name`` across namespaces, in source order."""
    lowered = name.lower()
    return tuple(
        strip_meta_terminator(block.value)
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


@dataclass(frozen=True)
class FetchPolicy:
    """Parsed ``fetch-policy`` metadata value.

    ``bestpdf`` means fetch the published PDF if open-access is available,
    otherwise fall back to the preprint PDF.
    """

    preprint: bool = False
    published: bool = False
    source: bool = False
    supplement: bool = False
    bestpdf: bool = False


_VALID_FETCH_POLICY_VALUES = {"preprint", "published", "source", "supplement", "bestpdf"}

_DEFAULT_FETCH_POLICY = FetchPolicy(bestpdf=True)


def parse_fetch_policy(value: str | None) -> FetchPolicy:
    """Parse a ``fetch-policy`` metadata string into a :class:`FetchPolicy`.

    Comma-separated values. When ``value`` is ``None`` or empty, returns the
    default policy ``FetchPolicy(bestpdf=True)`` — fetch the best available PDF.
    """
    if not value:
        return _DEFAULT_FETCH_POLICY
    items = [v.strip().lower() for v in value.replace(";", ",").split(",") if v.strip()]
    if not items:
        return _DEFAULT_FETCH_POLICY
    return FetchPolicy(
        preprint="preprint" in items,
        published="published" in items,
        source="source" in items,
        supplement="supplement" in items,
        bestpdf="bestpdf" in items,
    )


class DuplicateMetadataError(Exception):
    """Raised when a metadata update would be ambiguous."""

    def __init__(self, key: str, count: int):
        self.key = key
        self.count = count
        super().__init__(f"Cannot safely update {key!r}: found {count} matching blocks")


@dataclass
class MetadataUpdate:
    """One safe replacement or insertion of a top-level metadata block.

    ``old_raw`` and ``new_raw`` are retained so :class:`~pynakes.engine.Bibliography`
    can splice the comment into the original file instead of rewriting it.
    """

    key: str
    value: str
    old_raw: str | None
    new_raw: str
    created: bool
    namespace: str = "jabref"
    # A secondary update produced by mirroring an aliased pynakes-native write
    # into the jabref-meta projection (see
    # :func:`pynakes.metadata.jabref.project_aliased_to_jabref`). ``None`` when
    # the write was not mirrored.
    mirrored: "MetadataUpdate | None" = None


def _make_metadata_block(
    segment: str,
    namespace: str,
    raw: str,
    comment_index: int,
    classify: Classifier,
) -> MetadataBlock | None:
    """Build one block from a ``key:value`` segment, or ``None`` if malformed."""
    key, sep, value = segment.partition(":")
    if not sep:
        return None
    key = key.strip()
    if not key:
        return None
    category = classify(key)
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
    classify: Classifier | None = None,
) -> list[MetadataBlock]:
    """Parse a top-level metadata comment into one block per setting.

    ``comment_text`` is the content inside ``@comment{...}``. ``raw`` should be
    the full raw comment when available; it is used for precise replacements.
    ``classify`` maps a key to its domain category (``"unknown"`` when absent);
    callers that care about classification (chiefly
    :mod:`pynakes.metadata.schema`) should pass their own.

    A ``jabref-meta`` comment holds exactly one ``key:value`` (its value may span
    multiple lines, e.g. ``grouping``) and yields a single block — JabRef's own
    format is preserved verbatim. A ``pynakes-meta`` comment may carry several
    settings, one ``key:value;`` per line, and yields one block per line, all
    sharing the comment's raw text and ``comment_index``; the one-setting and
    consolidated multi-line layouts parse identically. Returns ``[]`` for a
    non-metadata comment.
    """
    classify = classify or _unclassified
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
        block = _make_metadata_block(body, namespace, raw_text, comment_index, classify)
        return [block] if block is not None else []

    # pynakes-meta: one setting per line with continuation support.
    # Lines starting with whitespace continue the previous block's value
    # (appended with a newline separator).
    blocks: list[MetadataBlock] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if blocks and line[0] in (" ", "\t"):
            # Indentation unambiguously marks a continuation. Check this before
            # parsing ``key:value`` so values such as group-tree nodes whose
            # names contain colons are not split into fake metadata settings.
            prev = blocks[-1]
            prev.value = prev.value + "\n" + stripped
            continue
        block = _make_metadata_block(stripped, namespace, raw_text, comment_index, classify)
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
    Values containing ``\\n`` are split across continuation lines (indented with
    two spaces) so the comment stays readable under line-length limits.
    JabRef ignores the ``pynakes-meta`` namespace, so pynakes uses this compact
    layout (no per-key prefix, no JabRef ``;`` terminator) rather than one comment
    per key. The reader (:func:`parse_metadata_comment`) still accepts the older
    ``key:value;`` spelling, so both layouts round-trip; this is the default
    written form. Any trailing ``;`` on a value is dropped on output.
    """
    lines = [f"@comment{{{PYNAKES_PREFIX}"]
    for key, value in items:
        value = strip_meta_terminator(value)
        if "\n" in value:
            first, *rest = value.split("\n")
            lines.append(f"{key.strip()}: {first}")
            for cont in rest:
                lines.append(f"  {cont}")
        else:
            lines.append(f"{key.strip()}: {value}")
    lines.append("}")
    return line_ending.join(lines)


def consolidate_metadata(lib: BibFile, text: str, line_ending: str = "\n") -> str | None:
    """Relocate metadata comments into their canonical namespace positions.

    pynakes keeps its native ``pynakes-meta`` block at the top of the file,
    where tool-facing settings are visible before the entries. JabRef writes its
    ``@Comment{jabref-meta: ...}`` blocks contiguously at the bottom of the file,
    sorted by key; pynakes preserves that convention for the compatibility
    projection. A library that has been hand-edited can end up with metadata
    stranded in the middle. This gathers all metadata and rewrites it as a
    top consolidated ``pynakes-meta`` block, the bibliography body, then bottom
    ``jabref-meta`` comments.

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

    top_parts: list[str] = []
    if pynakes_blocks:
        merged: dict[str, str] = {}
        for block in pynakes_blocks:
            merged[block.key] = block.value
        items = sorted(merged.items(), key=lambda kv: kv[0].lower())
        top_parts.append(format_pynakes_meta_block(items, line_ending))

    bottom_parts = [
        block.raw for block in sorted(jabref_blocks, key=lambda b: (b.key.lower(), b.comment_index))
    ]

    sections: list[str] = []
    sections.extend(top_parts)
    body = stripped.strip("\r\n")
    if body:
        sections.append(body)
    sections.extend(bottom_parts)

    result = (line_ending + line_ending).join(sections) + line_ending

    return result if result != text else None


def _comment_raw(lib: BibFile, block: MetadataBlock) -> str:
    """Return the live raw comment text for *block* (its stored raw as fallback)."""
    if 0 <= block.comment_index < len(lib.raw_comments):
        return lib.raw_comments[block.comment_index]
    return block.raw


def set_in_namespace(
    lib: BibFile,
    key: str,
    value: str,
    namespace: str,
    *,
    classify: Classifier | None = None,
) -> MetadataUpdate:
    """Set one metadata key within ``namespace``, applying that namespace's block mechanics.

    ``namespace`` must be ``"jabref"`` or ``"pynakes"``. Pure mechanics: this
    does not check whether ``key`` belongs to ``namespace`` — callers (see
    :func:`pynakes.metadata.schema.set_metadata`) own that policy.
    """
    if namespace == "jabref":
        return _set_jabref_metadata(lib, key, value, classify or _unclassified)
    if namespace == "pynakes":
        return _set_pynakes_metadata(lib, key, value, classify or _unclassified)
    raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")


def _set_jabref_metadata(
    lib: BibFile, key: str, value: str, classify: Classifier
) -> MetadataUpdate:
    """Set one ``jabref-meta`` key — one comment per key (JabRef's own format)."""
    blocks = lib.jabref_metadata_blocks

    matches = [b for b in blocks if b.key.lower() == key.lower()]
    if len(matches) > 1:
        raise DuplicateMetadataError(key, len(matches))

    new_raw = format_metadata_comment(key, value, "jabref")
    new_blocks = parse_metadata_comment(
        new_raw[new_raw.find("{") + 1 : -1], raw=new_raw, classify=classify
    )
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


def _set_pynakes_metadata(
    lib: BibFile, key: str, value: str, classify: Classifier
) -> MetadataUpdate:
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

    # In-memory BibFile may carry synthetic blocks with comment_index=-1
    # that have no raw_comments backing; treat them as "no existing comment".
    if target_index is not None and target_index < 0:
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
        new_raw[new_raw.find("{") + 1 : -1],
        raw=new_raw,
        comment_index=comment_index,
        classify=classify,
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


def remove_in_namespace(
    lib: BibFile,
    key: str,
    namespace: str,
    *,
    classify: Classifier | None = None,
) -> MetadataUpdate | None:
    """Remove one metadata key from ``namespace``, applying that namespace's block mechanics.

    Returns ``None`` when the key is absent from ``namespace``.
    """
    if namespace == "jabref":
        return _remove_jabref_metadata(lib, key)
    if namespace == "pynakes":
        return _remove_pynakes_metadata(lib, key, classify or _unclassified)
    raise ValueError(f"Unknown metadata namespace {namespace!r}; expected jabref or pynakes")


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


def _remove_pynakes_metadata(lib: BibFile, key: str, classify: Classifier) -> MetadataUpdate | None:
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
        new_raw[new_raw.find("{") + 1 : -1],
        raw=new_raw,
        comment_index=comment_index,
        classify=classify,
    )
    if 0 <= comment_index < len(lib.raw_comments):
        lib.raw_comments[comment_index] = new_raw
    lib.pynakes_metadata_blocks = others + new_blocks
    return MetadataUpdate(key, "", old_raw, new_raw, False, "pynakes")
