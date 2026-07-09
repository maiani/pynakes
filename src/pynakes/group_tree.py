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
from pynakes.editing import append_delimited_field, remove_entry_field, set_entry_field
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
# JabRef ``grouping`` format — multi-line modern format
# ---------------------------------------------------------------------------
# 0 AllEntriesGroup:;
# 1 StaticGroup:name\;context\;expanded\;color\;icon\;description;
# 1 KeywordGroup:name\;context\;field\;expression\;case\;separator\;icon\;desc;
# 1 SearchGroup:name\;context\;expression\;flags\;icon\;desc;
# 1 ExplicitGroup:name\;context\;expanded\;color\;key1\;key2\;...;


def _parse_jabref_params(body: str) -> list[str]:
    """Split a JabRef group body on semicolons, handling both conventions.

    JabRef uses ``;`` as the parameter delimiter, but some exporters and
    older versions write ``\\;`` instead.  We detect the convention: if the
    body contains backslash-escaped semicolons but no unescaped ``;`` apart
    from a possible trailing group terminator, we split on ``\\;`` and
    unescape each part.
    """
    unescaped_idx = _find_unescaped(body, ";")
    if "\\;" in body and (unescaped_idx == -1 or unescaped_idx == len(body) - 1):
        parts = body.split("\\;")
        return [_unescape(p) for p in parts]
    return _split_escaped(body, ";")


def parse_jabref_grouping(value: str) -> list[GroupNode]:
    """Parse a JabRef ``grouping`` metadata value into a list of nodes.

    Supports ``StaticGroup``, ``KeywordGroup``, ``SearchGroup``, and
    ``ExplicitGroup``.  Returns an empty list when *value* is empty or
    unparseable.
    """
    if not value or not value.strip():
        return []
    nodes: list[GroupNode] = []
    last_at_depth: dict[int, str] = {}
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            space_idx = line.index(" ")
            depth_str = line[:space_idx]
            depth = int(depth_str) if depth_str.isdigit() else -1
        except (ValueError, IndexError):
            continue
        if depth < 0:
            continue
        rest = line[space_idx + 1 :]
        # Find the first unescaped colon separating group type from parameters
        colon_idx = _find_unescaped(rest, ":")
        if colon_idx == -1:
            continue
        group_type = rest[:colon_idx].strip()
        body = rest[colon_idx + 1 :]
        params = _parse_jabref_params(body)
        if not params:
            continue
        raw_name = params[0]
        name = _unescape(raw_name)
        if not name or name == "AllEntriesGroup":
            last_at_depth[0] = ""
            continue
        context = (
            int(_unescape(params[1])) if len(params) > 1 and params[1].strip().isdigit() else 0
        )
        expanded = True
        color = ""
        field = ""
        expression = ""
        case_sensitive = False
        separator = ""
        search_flags = ""
        entries: tuple[str, ...] = ()

        if group_type in ("StaticGroup", "ExplicitGroup"):
            expanded = params[2] == "1" if len(params) > 2 else True
            color = _unescape(params[3]) if len(params) > 3 else ""
            if group_type == "ExplicitGroup":
                entries = tuple(
                    _unescape(params[i]) for i in range(4, len(params)) if params[i].strip()
                )

        elif group_type == "KeywordGroup":
            field = _unescape(params[2]) if len(params) > 2 else ""
            expression = _unescape(params[3]) if len(params) > 3 else ""
            case_sensitive = params[4] == "1" if len(params) > 4 else False
            separator = _unescape(params[5]) if len(params) > 5 else ""

        elif group_type == "SearchGroup":
            expression = _unescape(params[2]) if len(params) > 2 else ""
            search_flags = _unescape(params[3]) if len(params) > 3 else ""

        parent = last_at_depth.get(depth - 1, "")
        nodes.append(
            GroupNode(
                name=name,
                parent=parent or "",
                context=context,
                color=color or "",
                expanded=expanded,
                group_type=group_type,
                field=field,
                expression=expression,
                case_sensitive=case_sensitive,
                separator=separator,
                search_flags=search_flags,
                entries=entries,
            )
        )
        last_at_depth[depth] = name
        for d in list(last_at_depth):
            if d > depth:
                del last_at_depth[d]
    return nodes


def format_jabref_grouping(nodes: list[GroupNode]) -> str:
    """Serialize *nodes* to the JabRef ``grouping`` metadata block value."""
    lines: list[str] = ["0 AllEntriesGroup:;"]
    # Build depth map
    depth_map: dict[str, int] = {}
    assigned: set[str] = set()

    def _assign_depth(name: str, d: int) -> None:
        if name in assigned:
            return
        depth_map[name] = d
        assigned.add(name)
        for child in _child_groups(nodes, name):
            _assign_depth(child.name, d + 1)

    # Find root-level nodes (empty parent)
    roots = [n for n in nodes if not n.parent]
    for r in roots:
        _assign_depth(r.name, 1)

    # Assign remaining (orphans that have a parent but their parent isn't in the tree)
    for n in nodes:
        if n.name not in assigned:
            _assign_depth(n.name, 1)

    for n in nodes:
        d = depth_map.get(n.name, 1)
        escaped_name = _escape(n.name, "\\;:")
        escaped_field = _escape(n.field, "\\;:")
        escaped_expr = _escape(n.expression, "\\;:")
        escaped_sep = _escape(n.separator, "\\;:")

        if n.group_type == "KeywordGroup":
            params = [
                escaped_name,
                str(n.context),
                escaped_field,
                escaped_expr,
                "1" if n.case_sensitive else "0",
                escaped_sep,
                "",  # icon
                _escape(n.description) if n.description else "",
            ]
            line = f"{d} KeywordGroup:{';'.join(params)};"

        elif n.group_type == "SearchGroup":
            params = [
                escaped_name,
                str(n.context),
                escaped_expr,
                n.search_flags,
                "",  # icon
                _escape(n.description) if n.description else "",
            ]
            line = f"{d} SearchGroup:{';'.join(params)};"

        elif n.group_type == "ExplicitGroup":
            color_part = _escape(n.color) if n.color else ""
            entry_parts = [_escape(ek, "\\;:") for ek in n.entries]
            params = [
                escaped_name,
                str(n.context),
                "1" if n.expanded else "0",
                color_part,
                *entry_parts,
            ]
            line = f"{d} ExplicitGroup:{';'.join(params)};"

        else:  # StaticGroup (default)
            params = [
                escaped_name,
                str(n.context),
                "1" if n.expanded else "0",
                _escape(n.color) if n.color else "",
                "",  # icon (unused)
                _escape(n.description) if n.description else "",
            ]
            line = f"{d} StaticGroup:{';'.join(params)};"

        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JabRef flat ``groups:N name:context;`` format
# ---------------------------------------------------------------------------
# Each line is its own @comment{jabref-meta: groups:N name:context;;}
# The depth encodes hierarchy.


def parse_jabref_groups_lines(lines: list[str]) -> list[GroupNode]:
    """Parse flat JabRef ``groups:``-key metadata lines into nodes.

    Each line has the form ``groups:N <name>:<context>;`` where ``N`` is the
    depth (0 = root) and the name may contain escaped colons (backslash-colon).
    """
    nodes: list[GroupNode] = []
    last_at_depth: dict[int, str] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not line.startswith("groups:"):
            continue
        body = line[len("groups:") :].strip()
        # Depth is the leading digit(s) before the space
        space_idx = body.find(" ")
        if space_idx == -1:
            continue
        depth_str = body[:space_idx]
        if not depth_str.isdigit():
            continue
        depth = int(depth_str)
        rest = body[space_idx + 1 :].rstrip(";").strip()
        # Find the first unescaped colon to split name:context
        colon_idx = _find_unescaped(rest, ":")
        if colon_idx == -1:
            continue
        name_part = rest[:colon_idx].strip()
        context_str = rest[colon_idx + 1 :].strip()
        name = _unescape(name_part)
        context = int(context_str) if context_str.isdigit() else 0
        if depth == 0:
            if name.lower() == "all entries":
                continue
            last_at_depth[0] = ""
        parent = last_at_depth.get(depth - 1, "")
        nodes.append(
            GroupNode(
                name=name,
                parent=parent or "",
                context=context,
            )
        )
        last_at_depth[depth] = name
        for d in list(last_at_depth):
            if d > depth:
                del last_at_depth[d]
    return nodes


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
    grouping = _jabref_grouping_tree(lib)
    if grouping is not None:
        return grouping
    # 3. JabRef flat groups
    flat = _jabref_flat_tree(lib)
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


def _jabref_grouping_tree(lib: BibFile) -> list[GroupNode] | None:
    """Read and parse a JabRef ``grouping`` or ``groupstree`` block."""
    for block in lib.jabref_metadata_blocks:
        key = block.key.lower()
        if key in ("grouping", "groupstree"):
            nodes = parse_jabref_grouping(block.value)
            if nodes:
                return nodes
    return None


def _jabref_flat_tree(lib: BibFile) -> list[GroupNode] | None:
    """Read and parse flat JabRef ``groups:`` lines."""
    lines = [
        f"{block.key}:{block.value}"
        for block in lib.jabref_metadata_blocks
        if block.key.lower() == "groups"
    ]
    if not lines:
        return None
    nodes = parse_jabref_groups_lines(lines)
    return nodes if nodes else None


# ---------------------------------------------------------------------------
# CRUD — all operations write through the native key
# ---------------------------------------------------------------------------

_GROUPS_DELIM = ";"
_GROUPS_JOIN = "; "


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


def list_entries_in_group_tree(lib: BibFile, group: str, *, strict: bool = False) -> list[str]:
    """Return entry keys that belong to *group*, including dynamic matches.

    When *strict* is ``False`` (default), includes entries in descendant groups
    (downward propagation).  When *strict* is ``True``, only exact group matches
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
    if strict:
        return sorted(_group_entry_keys(lib, node))
    keys: set[str] = set()
    for name in _descendant_names(tree, group):
        descendant = _node_by_name(tree, name)
        if descendant:
            keys.update(_group_entry_keys(lib, descendant))
    return sorted(keys)


def add_to_group_tree(lib: BibFile, key: str, group: str) -> int:
    """Add *key* to *group*, using the tree for validation.

    If the group does not exist in the tree, a warning-level fallback is used
    (the group is still added to the entry's ``groups`` field for
    forward-compatibility).
    """
    count = 0
    for entry in lib.entries.get_all(key):
        if append_delimited_field(entry, "groups", group, _GROUPS_DELIM, _GROUPS_JOIN):
            count += 1
    return count


def remove_from_group_tree(lib: BibFile, key: str, group: str) -> int:
    """Remove *key* from *group*."""
    count = 0
    for entry in lib.entries.get_all(key):
        groups = entry_group_names(entry)
        if group not in groups:
            continue
        groups.remove(group)
        if groups:
            set_entry_field(entry, "groups", _GROUPS_JOIN.join(groups))
        else:
            remove_entry_field(entry, "groups")
        count += 1
    return count
