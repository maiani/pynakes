"""GraphML and Markdown renderings of a co-author network document.

Both read the documented JSON document (:meth:`pynakes.coauthors.CoauthorNetwork.to_dict`)
rather than internal state, so any consumer holding that document can render
it the same way. Output is deterministic: lists keep the document's order.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

_GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"

#: GraphML attribute keys: (id, domain, attr.name, attr.type).
_NODE_KEYS = (
    ("label", "node", "label", "string"),
    ("entries", "node", "entries", "int"),
    ("collaborators", "node", "collaborators", "int"),
    ("component", "node", "component", "int"),
    ("first_year", "node", "first_year", "string"),
    ("last_year", "node", "last_year", "string"),
    ("orcids", "node", "orcids", "string"),
)
_FOCUS_KEYS = (
    ("focus", "node", "focus", "boolean"),
    ("with_focus", "node", "with_focus", "int"),
)
_EDGE_KEYS = (
    ("weight", "edge", "weight", "int"),
    ("edge_first_year", "edge", "first_year", "string"),
    ("edge_last_year", "edge", "last_year", "string"),
    ("keys", "edge", "keys", "string"),
)


def render_graphml(document: dict) -> str:
    """Return ``document`` as an undirected GraphML graph.

    Nodes are ``n0``, ``n1``, … in the document's author order, labelled with
    the author name; an edge's ``weight`` is the number of shared entries and
    ``keys`` their citation keys, separated by ``; ``. A focus view adds the
    ``focus`` and ``with_focus`` node attributes.
    """
    focus = document.get("focus") is not None
    root = ET.Element("graphml", xmlns=_GRAPHML_NS)
    for key_id, domain, name, kind in (*_NODE_KEYS, *(_FOCUS_KEYS if focus else ()), *_EDGE_KEYS):
        ET.SubElement(
            root, "key", {"id": key_id, "for": domain, "attr.name": name, "attr.type": kind}
        )
    graph = ET.SubElement(root, "graph", id="coauthors", edgedefault="undirected")
    node_ids: dict[str, str] = {}
    for number, author in enumerate(document["authors"]):
        node_id = f"n{number}"
        node_ids[author["name"]] = node_id
        node = ET.SubElement(graph, "node", id=node_id)
        values = {
            "label": author["name"],
            "entries": author["entries"],
            "collaborators": author["collaborators"],
            "component": author["component"],
            "first_year": author["first_year"],
            "last_year": author["last_year"],
            "orcids": "; ".join(author["orcids"]) or None,
        }
        if focus:
            values["focus"] = "true" if author["focus"] else "false"
            values["with_focus"] = author["with_focus"]
        _data(node, values)
    for number, pair in enumerate(document["pairs"]):
        source, target = (node_ids[name] for name in pair["authors"])
        edge = ET.SubElement(graph, "edge", id=f"e{number}", source=source, target=target)
        _data(
            edge,
            {
                "weight": pair["entries"],
                "edge_first_year": pair["first_year"],
                "edge_last_year": pair["last_year"],
                "keys": "; ".join(pair["keys"]),
            },
        )
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _data(parent: ET.Element, values: dict[str, object]) -> None:
    for key, value in values.items():
        if value is not None:
            ET.SubElement(parent, "data", key=key).text = str(value)


def render_markdown(document: dict, title: str) -> str:
    """Return ``document`` as a Markdown report: summary, then one table per list."""
    summary = document["summary"]
    entries = document["entries"]
    lines = [f"# {title}", ""]
    source = document.get("source")
    if source:
        selection = source.get("where") or ""
        if source.get("keys"):
            selection += (" and " if selection else "") + f"key in [{', '.join(source['keys'])}]"
        lines += [
            f"Source: `{source['file']}`" + (f", entries where `{selection}`" if selection else ""),
            "",
        ]
    lines += [
        _table(
            ["Count", "Value"],
            [
                ["Entries", entries["total"]],
                ["Entries with authors", entries["with_authors"]],
                ["Co-authored entries", entries["coauthored"]],
                ["Entries with a truncated author list (others)", entries["with_others"]],
                ["Authors", summary["authors"]],
                ["Pairs", summary["pairs"]],
                ["Components", summary["components"]],
                ["Largest component", summary["largest_component"]],
                ["Isolated authors", summary["isolated_authors"]],
                ["Name-variant candidates", summary["variant_candidates"]],
            ],
        ),
        "",
    ]
    focus = document.get("focus")
    if focus is not None:
        names = ", ".join(item["name"] for item in focus)
        collaborators = [a for a in document["authors"] if not a["focus"]]
        collaborators.sort(key=lambda a: (-a["with_focus"], a["name"].casefold()))
        lines += [
            "## Focus",
            "",
            f"Ego view of {names}: their co-authors and the pairs among them. "
            "Components leave the focus names out.",
            "",
            _table(
                ["Co-author", "Shared entries", "Component", "Keys"],
                [
                    [a["name"], a["with_focus"], a["component"], "; ".join(a["with_focus_keys"])]
                    for a in collaborators
                ],
            ),
            "",
        ]
    lines += [
        "## Authors",
        "",
        _table(
            ["Author", "Entries", "Collaborators", "Years", "Component"],
            [
                [a["name"], a["entries"], a["collaborators"], _years(a), _blank(a["component"])]
                for a in document["authors"]
            ],
        ),
        "",
        "## Pairs",
        "",
        _table(
            ["Author", "Author", "Shared entries", "Years", "Keys"],
            [
                [*p["authors"], p["entries"], _years(p), "; ".join(p["keys"])]
                for p in document["pairs"]
            ],
        ),
        "",
        "## Components",
        "",
        _table(
            ["Component", "Size", "Entries", "Authors"],
            [
                [c["id"], c["size"], c["entries"], "; ".join(c["authors"])]
                for c in document["components"]
            ],
        ),
        "",
        "## Name-variant candidates",
        "",
        "Distinct names that may be one person. They are counted apart; decide and "
        "correct the records rather than the report.",
        "",
        _table(
            ["Names", "Reasons", "Evidence against", "Entries"],
            [
                [
                    " / ".join(v["names"]),
                    ", ".join(v["reasons"]),
                    ", ".join(v["evidence_against"]),
                    " / ".join(str(item["entries"]) for item in v["entries"]),
                ]
                for v in document["variants"]
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def _years(item: dict) -> str:
    first, last = item["first_year"], item["last_year"]
    if first is None:
        return "undated"
    span = first if first == last else f"{first}–{last}"
    return span + (f" (+{item['undated']} undated)" if item["undated"] else "")


def _blank(value: object) -> object:
    return "" if value is None else value


def _table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "None."
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    for row in rows:
        cells = (str(cell).replace("|", "\\|").replace("\n", " ") for cell in row)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
