"""Group tree model, native metadata format, and JabRef projection.

JabRef stores a group hierarchy in two formats:

* Modern ``grouping`` — a single ``@comment{jabref-meta: grouping:...}`` block
  whose value is a newline-separated tree with backslash-escaped parameters.
* Legacy ``groupstree`` — same structure but with inline entry keys.
* Flat ``groups:N name:context;`` — one ``@comment{jabref-meta: groups:...}``
  per group node, encoding depth as ``N``.

pynakes introduces a native ``pynakes-meta`` key ``group-tree`` with a
pipe-delimited format.  Trees with a single node use a one-line value; larger
trees are split across continuation lines (one node per line) within the
``pynakes-meta`` block to stay readable under line-length limits.  When the
file is JabRef-tracked the tree is also projected into the ``grouping`` block.

All four JabRef group types are fully supported and the dynamic types
(``KeywordGroup`` / ``SearchGroup``) are evaluated at query time:

* ``StaticGroup`` — a fixed group defined by name alone.
* ``KeywordGroup`` — dynamic group matching a field against a search expression.
* ``SearchGroup`` — dynamic group with a free-form search expression.
* ``ExplicitGroup`` — static group with inline entry keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pynakes._text_utils import _split_escaped
from pynakes.model import BibFile

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_GroupContext = Literal[0, 1, 2]


@dataclass
class GroupNode:
    """One node in the group hierarchy.

    ``parent`` is the name of the parent node, or empty for root-level nodes.
    ``context`` controls how membership is aggregated: 0 = independent,
    1 = refining (intersection with parent), 2 = including (union with subgroups).

    ``group_type`` is one of ``StaticGroup``, ``KeywordGroup``, ``SearchGroup``,
    or ``ExplicitGroup``.  Type-specific fields are:

    * ``KeywordGroup`` — *field*, *expression*, *case_sensitive*, *separator*
    * ``SearchGroup`` — *expression*, *search_flags*
    * ``ExplicitGroup`` — *entries* (tuple of inline citation keys)
    """

    name: str
    parent: str = ""
    context: int = 2
    color: str = ""
    expanded: bool = True
    description: str = ""
    group_type: str = "StaticGroup"
    # KeywordGroup
    field: str = ""
    expression: str = ""
    case_sensitive: bool = False
    separator: str = ""
    # SearchGroup
    search_flags: str = ""
    # ExplicitGroup
    entries: tuple[str, ...] = ()

    def __hash__(self) -> int:
        return hash(self.name.lower())

    def to_dict(self) -> dict[str, object]:
        """Serialize this node to a JSON-friendly dict (explicit, not ``__dict__``).

        Field order matches the dataclass declaration so JSON output is stable
        and identical to the previous ``__dict__``-based serialization.
        """
        return {
            "name": self.name,
            "parent": self.parent,
            "context": self.context,
            "color": self.color,
            "expanded": self.expanded,
            "description": self.description,
            "group_type": self.group_type,
            "field": self.field,
            "expression": self.expression,
            "case_sensitive": self.case_sensitive,
            "separator": self.separator,
            "search_flags": self.search_flags,
            "entries": self.entries,
        }


def _child_groups(nodes: list[GroupNode], parent: str) -> list[GroupNode]:
    """Return the direct children of *parent* in insertion order."""
    return [n for n in nodes if n.parent == parent]


def _descendant_names(nodes: list[GroupNode], name: str) -> list[str]:
    """Return *name* and all recursive descendant group names."""
    result: list[str] = [name]
    for child in _child_groups(nodes, name):
        result.extend(_descendant_names(nodes, child.name))
    return result


def _ancestor_names(nodes: list[GroupNode], name: str) -> list[str]:
    """Return *name* and all ancestor group names (start to root)."""
    result: list[str] = [name]
    parent = _parent_of(nodes, name)
    while parent:
        result.append(parent.name)
        parent = _parent_of(nodes, parent.name)
    return result


def _parent_of(nodes: list[GroupNode], name: str) -> GroupNode | None:
    """Return the parent node of *name*, or ``None`` if root-level."""
    for n in nodes:
        if n.name == name and n.parent:
            for p in nodes:
                if p.name == n.parent:
                    return p
    return None


def _node_by_name(nodes: list[GroupNode], name: str) -> GroupNode | None:
    """Return the first node matching *name* (case-insensitive)."""
    for n in nodes:
        if n.name.lower() == name.lower():
            return n
    return None


# ---------------------------------------------------------------------------
# Native format — pipe-delimited, multiline-capable
# ---------------------------------------------------------------------------
# Single-node:   group-tree: f0|f1|f2|f3|f4|f5|f6|f7|f8|f9|f10|f11|f12
# Multi-node:    group-tree: n1_fields...
#                             n2_fields...
#
# Fields per node (pipe-separated):
#   0   name          — group display name
#   1   parent        — parent name (empty for root-level)
#   2   context       — 0/1/2 (default 2)
#   3   color         — hex RGBA like "8a8a8aff" or empty
#   4   expanded      — 1 or 0 (default 1)
#   5   description   — description (default empty)
#   6   group_type    — StaticGroup / KeywordGroup / SearchGroup / ExplicitGroup
#   7   field         — KeywordGroup: BibTeX field to match
#   8   expression    — KeywordGroup/SearchGroup: search expression
#   9   case_sensitive— KeywordGroup: 0 or 1
#  10   separator     — KeywordGroup: field separator
#  11   search_flags  — SearchGroup: flags
#  12   entries       — ExplicitGroup: comma-joined citation keys
#
# Nodes are separated by ``\n`` for multiline or ``; `` for single-line.
# Backslash escapes: ``\\``, ``\|``, ``\;``.

_NODE_SEP = "; "
_FIELD_SEP = "|"


def _escape(text: str, special: str = _FIELD_SEP + _NODE_SEP.strip()) -> str:
    """Backslash-escape *special* characters in *text*."""
    result = text.replace("\\", "\\\\")
    for ch in special:
        result = result.replace(ch, f"\\{ch}")
    return result


def _unescape(text: str) -> str:
    """Resolve backslash escapes in *text*."""
    result = ""
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            result += text[i + 1]
            i += 2
        else:
            result += text[i]
            i += 1
    return result


def _serialize_node(n: GroupNode) -> str:
    """Serialize one node to the pipe-delimited native format."""
    fields = [
        _escape(n.name),
        _escape(n.parent),
        str(n.context),
        n.color or "",
        "1" if n.expanded else "0",
        _escape(n.description),
        n.group_type,
        _escape(n.field),
        _escape(n.expression),
        "1" if n.case_sensitive else "0",
        _escape(n.separator),
        n.search_flags,
        ",".join(n.entries),
    ]
    return _FIELD_SEP.join(fields)


def serialize_native(nodes: list[GroupNode]) -> str:
    """Serialize a list of *nodes* to the native single-line format."""
    return _NODE_SEP.join(_serialize_node(n) for n in nodes)


def _find_unescaped(text: str, char: str) -> int:
    """Return the index of the first unescaped occurrence of *char* in *text*.

    A backslash before *char* escapes it.  Returns -1 when not found.
    """
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == char:
            return i
        i += 1
    return -1


def parse_native(value: str) -> list[GroupNode]:
    """Parse a native ``group-tree`` value into a list of nodes.

    Accepts both the single-line ``; ``-delimited format and the multiline
    ``\\n``-separated format.  Returns an empty list when *value* is empty
    or ``None``.
    """
    if not value or not value.strip():
        return []
    nodes: list[GroupNode] = []
    # Split on newlines first, then on "; " within each line.
    for line in value.split("\n"):
        line = line.strip()
        if not line:
            continue
        for node_text in _split_escaped(line, _NODE_SEP.strip()):
            node_text = node_text.strip()
            if not node_text:
                continue
            fields = _split_escaped(node_text, _FIELD_SEP)
            name = _unescape(fields[0]) if fields else ""
            if not name:
                continue
            parent = _unescape(fields[1]) if len(fields) > 1 else ""
            context = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else 2
            color = fields[3] if len(fields) > 3 else ""
            expanded = fields[4] == "1" if len(fields) > 4 else True
            description = _unescape(fields[5]) if len(fields) > 5 else ""
            group_type = fields[6] if len(fields) > 6 and fields[6] else "StaticGroup"
            kw_field = _unescape(fields[7]) if len(fields) > 7 else ""
            expression = _unescape(fields[8]) if len(fields) > 8 else ""
            case_sensitive = fields[9] == "1" if len(fields) > 9 else False
            separator = _unescape(fields[10]) if len(fields) > 10 else ""
            search_flags = fields[11] if len(fields) > 11 else ""
            raw_entries = fields[12] if len(fields) > 12 else ""
            entries = tuple(e for e in raw_entries.split(",") if e) if raw_entries else ()
            nodes.append(
                GroupNode(
                    name=name,
                    parent=parent,
                    context=context,
                    color=color,
                    expanded=expanded,
                    description=description,
                    group_type=group_type,
                    field=kw_field,
                    expression=expression,
                    case_sensitive=case_sensitive,
                    separator=separator,
                    search_flags=search_flags,
                    entries=entries,
                )
            )
    return nodes


# ---------------------------------------------------------------------------
# Backward-compatible re-exports — canonical home is metadata.jabref
# ---------------------------------------------------------------------------


def parse_jabref_grouping(value: str) -> list[GroupNode]:
    """Parse a JabRef ``grouping`` metadata value into a list of nodes.

    Canonical implementation: :func:`pynakes.metadata.jabref.parse_jabref_grouping`.
    """
    from pynakes.metadata.jabref import parse_jabref_grouping as _impl

    return _impl(value)


def format_jabref_grouping(nodes: list[GroupNode]) -> str:
    """Serialize *nodes* to the JabRef ``grouping`` metadata block value.

    Canonical implementation: :func:`pynakes.metadata.jabref.format_jabref_grouping`.
    """
    from pynakes.metadata.jabref import format_jabref_grouping as _impl

    return _impl(nodes)


def parse_jabref_groups_lines(lines: list[str]) -> list[GroupNode]:
    """Parse flat JabRef ``groups:``-key metadata lines into nodes.

    Canonical implementation: :func:`pynakes.metadata.jabref.parse_jabref_groups_lines`.
    """
    from pynakes.metadata.jabref import parse_jabref_groups_lines as _impl

    return _impl(lines)


# ---------------------------------------------------------------------------
# Library-level read helpers
# ---------------------------------------------------------------------------

NATIVE_KEY = "group-tree"


def library_group_tree(lib: BibFile) -> list[GroupNode] | None:
    """Return the parsed group tree for *lib*, or ``None`` when none is defined.

    Reads the native ``group-tree`` key first (pynakes-meta), then falls back
    to JabRef's ``grouping``, ``groupstree``, or ``groups`` metadata blocks.
    """
    # 1. Native key
    native = _native_tree(lib)
    if native is not None:
        return native
    # 2. JabRef grouping
    from pynakes.metadata.jabref import jabref_grouping_tree

    grouping = jabref_grouping_tree(lib)
    if grouping is not None:
        return grouping
    # 3. JabRef flat groups
    from pynakes.metadata.jabref import jabref_flat_tree

    flat = jabref_flat_tree(lib)
    if flat is not None:
        return flat
    return None


def _native_tree(lib: BibFile) -> list[GroupNode] | None:
    """Read the native ``group-tree`` key from pynakes-meta."""
    for block in lib.pynakes_metadata_blocks:
        if block.key.lower() == NATIVE_KEY:
            nodes = parse_native(block.value)
            return nodes if nodes else None
    return None


# ---------------------------------------------------------------------------
# CRUD — all operations write through the native key
# ---------------------------------------------------------------------------

_GROUPS_DELIM = ";"


def _write_tree(lib: BibFile, nodes: list[GroupNode]) -> None:
    """Serialize *nodes* to the native ``group-tree`` key and write to *lib*.

    On JabRef-tracked files the tree is also projected into ``grouping`` and
    ``groupsversion`` metadata.

    When the tree has more than one node the value is split across continuation
    lines (one node per line) so the metadata comment stays readable under
    line-length limits.
    """
    from pynakes.metadata import set_in_namespace
    from pynakes.metadata.jabref import library_is_jabref_tracked

    if len(nodes) > 1:
        # One node per continuation line to keep lines short.
        value = "\n".join(_serialize_node(n) for n in nodes)
    else:
        value = serialize_native(nodes)
    set_in_namespace(lib, NATIVE_KEY, value, "pynakes")
    if library_is_jabref_tracked(lib):
        grouping_value = format_jabref_grouping(nodes)
        set_in_namespace(lib, "grouping", grouping_value, "jabref")
        set_in_namespace(lib, "groupsversion", "3", "jabref")


def add_node(
    lib: BibFile,
    name: str,
    *,
    parent: str = "",
    context: int = 2,
    color: str = "",
    expanded: bool = True,
) -> bool:
    """Add a group node to the tree.

    Returns ``True`` if a new node was added, ``False`` if a node with the same
    name already exists.
    """
    tree = library_group_tree(lib) or []
    if _node_by_name(tree, name):
        return False
    tree.append(
        GroupNode(name=name, parent=parent, context=context, color=color, expanded=expanded)
    )
    _write_tree(lib, tree)
    return True


def remove_node(lib: BibFile, name: str) -> int:
    """Remove a group node and all its descendants from the tree.

    Returns the number of nodes removed (1 + descendants).
    """
    tree = library_group_tree(lib) or []
    to_remove = _descendant_names(tree, name)
    before = len(tree)
    tree = [n for n in tree if n.name not in to_remove]
    if len(tree) == before:
        return 0
    _write_tree(lib, tree)
    return before - len(tree)


def rename_node(lib: BibFile, old_name: str, new_name: str) -> bool:
    """Rename a group node, updating parent references in children.

    Returns ``True`` if a node was renamed, ``False`` if *old_name* was not
    found or *new_name* already exists.
    """
    tree = library_group_tree(lib) or []
    node = _node_by_name(tree, old_name)
    if node is None or _node_by_name(tree, new_name):
        return False
    node.name = new_name
    # Update parent refs in children
    for n in tree:
        if n.parent.lower() == old_name.lower():
            n.parent = new_name
    _write_tree(lib, tree)
    return True


def move_node(lib: BibFile, name: str, new_parent: str) -> bool:
    """Move a group node to a new parent.

    Pass ``new_parent=""`` to make it a root-level node.  Returns ``False`` if
    *name* is not found or the move would create a circular reference.
    """
    tree = library_group_tree(lib) or []
    node = _node_by_name(tree, name)
    if node is None:
        return False
    # Prevent circular reference (descendant_names returns strings)
    if new_parent and new_parent.lower() in {n.lower() for n in _descendant_names(tree, name)}:
        return False
    node.parent = new_parent
    _write_tree(lib, tree)
    return True


def update_node(lib: BibFile, name: str, **kwargs) -> bool:
    """Update properties of a group node.

    Acceptable keyword arguments: ``parent``, ``context``, ``color``,
    ``expanded``, ``description``, ``group_type``, ``field``, ``expression``,
    ``case_sensitive``, ``separator``, ``search_flags``, ``entries``.
    Returns ``False`` when *name* is not found.
    """
    tree = library_group_tree(lib) or []
    node = _node_by_name(tree, name)
    if node is None:
        return False
    for key, value in kwargs.items():
        if hasattr(node, key):
            setattr(node, key, value)
    _write_tree(lib, tree)
    return True


def list_tree(lib: BibFile) -> list[GroupNode] | None:
    """Return the group tree, or ``None`` if no tree is defined."""
    return library_group_tree(lib)


# ---------------------------------------------------------------------------
# Dynamic group evaluation (KeywordGroup / SearchGroup)
# ---------------------------------------------------------------------------


def _matches_keyword_group(entry, node) -> bool:
    if not node.field or not node.expression:
        return False
    field_value = entry.fields.get(node.field, "")
    if node.separator:
        tokens = field_value.split(node.separator)
        if node.case_sensitive:
            return any(t.strip() == node.expression for t in tokens)
        return any(t.strip().lower() == node.expression.lower() for t in tokens)
    if node.case_sensitive:
        return node.expression in field_value
    return node.expression.lower() in field_value.lower()


def _matches_search_group(entry, node) -> bool:
    if not node.expression:
        return False
    case_sensitive = node.search_flags == "1"
    if case_sensitive:
        return any(node.expression in val for val in entry.fields.values())
    expr_lower = node.expression.lower()
    return any(expr_lower in val.lower() for val in entry.fields.values())


def _group_entry_keys(lib, node) -> set[str]:
    keys: set[str] = set()
    for entry in lib.entries.values():
        if node.name in entry_group_names(entry):
            keys.add(entry.key)
    if node.group_type == "KeywordGroup":
        for entry in lib.entries.values():
            if _matches_keyword_group(entry, node):
                keys.add(entry.key)
    elif node.group_type == "SearchGroup":
        for entry in lib.entries.values():
            if _matches_search_group(entry, node):
                keys.add(entry.key)
    elif node.group_type == "ExplicitGroup":
        keys.update(node.entries)
    return keys


def entry_computed_groups(lib, entry_key) -> list[str]:
    entry = lib.entries.get(entry_key)
    if entry is None:
        return []
    tree = library_group_tree(lib)
    if tree is None:
        return []
    result: list[str] = []
    for node in tree:
        if node.group_type == "KeywordGroup" and _matches_keyword_group(entry, node):
            result.append(node.name)
        elif node.group_type == "SearchGroup" and _matches_search_group(entry, node):
            result.append(node.name)
    return result


# ---------------------------------------------------------------------------
# Tree-aware group queries (extend groups.py semantics)
# ---------------------------------------------------------------------------


def entry_group_names(entry) -> list[str]:
    """Return the raw group names assigned to *entry* (from its ``groups`` field)."""
    raw = entry.fields.get("groups") or ""
    return [g.strip() for g in raw.split(_GROUPS_DELIM) if g.strip()]


def resolve_effective_groups(lib: BibFile, entry) -> list[str]:
    """Return all effective groups for *entry*, including inherited ancestors
    and computed dynamic groups.

    If a group tree is defined, this walks upward from each assigned group and
    each computed dynamic group, including all ancestors.  Without a tree,
    returns the raw group names only.
    """
    raw = entry_group_names(entry)
    tree = library_group_tree(lib)
    if tree is None:
        return raw
    effective: set[str] = set()
    for g in raw:
        effective.update(_ancestor_names(tree, g))
    for g in entry_computed_groups(lib, entry.key):
        effective.update(_ancestor_names(tree, g))
    return [g for g in raw if g in effective] + [g for g in effective if g not in raw]


def list_entries_in_group_tree(lib: BibFile, group: str, *, exact: bool = False) -> list[str]:
    """Return entry keys that belong to *group*, including dynamic matches.

    When *exact* is ``False`` (default), includes entries in descendant groups
    (downward propagation).  When *exact* is ``True``, only exact group matches
    are returned (JabRef-compatible behavior).  Both modes evaluate
    ``KeywordGroup`` and ``SearchGroup`` expressions.
    """
    tree = library_group_tree(lib)
    if tree is None:
        return sorted(
            [entry.key for entry in lib.entries.values() if group in entry_group_names(entry)]
        )
    node = _node_by_name(tree, group)
    if node is None:
        return []
    if exact:
        return sorted(_group_entry_keys(lib, node))
    keys: set[str] = set()
    for name in _descendant_names(tree, group):
        descendant = _node_by_name(tree, name)
        if descendant:
            keys.update(_group_entry_keys(lib, descendant))
    return sorted(keys)


def known_group_names(lib: BibFile) -> list[str]:
    """Return every group name known to *lib*: tree nodes union flat tags.

    Tree node names come first, in tree order; flat-only group tags — names
    that appear only in some entry's ``groups`` field, with no corresponding
    tree node (or when no tree is defined at all) — follow, in first-seen
    order. This is the deterministic union that ``groups list`` and
    ``groups list-entries`` (for unknown-name detection) share, so a flat-only
    group is never dropped just because an unrelated tree exists.
    """
    from pynakes.groups import list_groups as _flat_group_names

    tree = library_group_tree(lib)
    tree_names = [n.name for n in tree] if tree else []
    seen = {n.lower() for n in tree_names}
    result = list(tree_names)
    for name in _flat_group_names(lib):
        if name.lower() not in seen:
            seen.add(name.lower())
            result.append(name)
    return result


def list_direct_members(lib: BibFile, name: str) -> list[str]:
    """Return the direct members of *name*, without descendant expansion.

    Resolves *name* against a tree node when one exists (evaluating its
    explicit/dynamic membership), otherwise falls back to entries whose flat
    ``groups`` field tags *name* directly. This covers flat-only group tags
    even when an unrelated tree is present elsewhere in the library.
    """
    tree = library_group_tree(lib)
    node = _node_by_name(tree, name) if tree else None
    if node is not None:
        return sorted(_group_entry_keys(lib, node))
    return sorted(entry.key for entry in lib.entries.values() if name in entry_group_names(entry))
