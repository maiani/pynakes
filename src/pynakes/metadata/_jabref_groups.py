"""JabRef's group-tree grammar: the ``grouping`` and legacy ``groups`` values.

Parsing and serializing JabRef's own group syntax, kept beside the rest of the
JabRef adapter. Public through :mod:`pynakes.metadata.jabref` and
:mod:`pynakes.metadata`, which re-export it.
"""

from pynakes._text_utils import _split_escaped
from pynakes.group_tree import (
    GroupNode,
    _child_groups,
    _escape,
    _find_unescaped,
    _unescape,
)
from pynakes.model import BibFile

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
        if unescaped_idx == len(body) - 1:
            # The bare ``;`` ends the group; it is not one more parameter.
            body = body[:-1]
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

        lines.append(_quote_group_line(line))
    return "\n".join(lines)


def _quote_group_line(line: str) -> str:
    """Quote one serialized group the way JabRef writes it inside ``grouping``.

    JabRef quotes every group a second time at the metadata level, so on disk
    its field separators appear as ``\\;`` and only the terminating ``;`` is
    bare: ``1 StaticGroup:Physics\\;0\\;1\\;0x8a8a8aff\\;\\;\\;;``. JabRef's
    reader splits the block on bare ``;``, so a group written unquoted falls
    apart into fragments it cannot parse, and the groups are lost.
    """
    # The serialized group already ends with JabRef's own trailing separator;
    # it is quoted like the rest, and the bare terminator follows it.
    return line.replace("\\", "\\\\").replace(";", "\\;") + ";"


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


def jabref_grouping_tree(lib: "BibFile") -> list[GroupNode] | None:
    """Read and parse a JabRef ``grouping`` or ``groupstree`` block."""
    for block in lib.jabref_metadata_blocks:
        key = block.key.lower()
        if key in ("grouping", "groupstree"):
            nodes = parse_jabref_grouping(block.value)
            if nodes:
                return nodes
    return None


def jabref_flat_tree(lib: "BibFile") -> list[GroupNode] | None:
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
