"""Tests for the group tree data model, native format, and CRUD operations."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.group_tree import (
    GroupNode,
    _ancestor_names,
    _descendant_names,
    _escape,
    _group_entry_keys,
    _matches_keyword_group,
    _matches_search_group,
    _node_by_name,
    _split_escaped,
    _unescape,
    add_node,
    entry_computed_groups,
    entry_group_names,
    format_jabref_grouping,
    library_group_tree,
    list_entries_in_group_tree,
    list_tree,
    move_node,
    parse_jabref_grouping,
    parse_jabref_groups_lines,
    parse_native,
    remove_node,
    rename_node,
    resolve_effective_groups,
    serialize_native,
    update_node,
)
from pynakes.model import BibEntry, BibFile

# ---------------------------------------------------------------------------
# Data model helpers
# ---------------------------------------------------------------------------


def test_descendant_names() -> None:
    nodes = [
        GroupNode(name="A"),
        GroupNode(name="B", parent="A"),
        GroupNode(name="C", parent="B"),
        GroupNode(name="D", parent="A"),
    ]
    assert _descendant_names(nodes, "A") == ["A", "B", "C", "D"]
    assert _descendant_names(nodes, "B") == ["B", "C"]
    assert _descendant_names(nodes, "C") == ["C"]


def test_ancestor_names() -> None:
    nodes = [
        GroupNode(name="A"),
        GroupNode(name="B", parent="A"),
        GroupNode(name="C", parent="B"),
    ]
    assert _ancestor_names(nodes, "C") == ["C", "B", "A"]
    assert _ancestor_names(nodes, "B") == ["B", "A"]
    assert _ancestor_names(nodes, "A") == ["A"]


def test_node_by_name() -> None:
    nodes = [GroupNode(name="Papers"), GroupNode(name="ML", parent="Papers")]
    assert _node_by_name(nodes, "Papers") is nodes[0]
    assert _node_by_name(nodes, "ml") is nodes[1]
    assert _node_by_name(nodes, "Nope") is None


# ---------------------------------------------------------------------------
# Escape / unescape
# ---------------------------------------------------------------------------


def test_escape_unescape_pipe() -> None:
    raw = "a|b;c\\d"
    escaped = _escape(raw)
    assert "|" not in escaped or "\\|" in escaped
    assert _unescape(escaped) == raw


def test_split_escaped() -> None:
    assert _split_escaped("a;b;c", ";") == ["a", "b", "c"]
    assert _split_escaped(r"a\;b;c", ";") == [r"a\;b", "c"]
    assert _split_escaped(r"a\\;b", ";") == [r"a\\", "b"]


# ---------------------------------------------------------------------------
# Native format
# ---------------------------------------------------------------------------


def test_native_round_trip() -> None:
    nodes = [
        GroupNode(name="Papers", color="8a8a8aff"),
        GroupNode(name="ML", parent="Papers"),
        GroupNode(name="Deep Learning", parent="ML", color="ff0000ff"),
    ]
    serialized = serialize_native(nodes)
    parsed = parse_native(serialized)
    assert len(parsed) == 3
    assert parsed[0].name == "Papers"
    assert parsed[0].color == "8a8a8aff"
    assert parsed[1].name == "ML"
    assert parsed[1].parent == "Papers"
    assert parsed[2].name == "Deep Learning"
    assert parsed[2].parent == "ML"
    assert parsed[2].color == "ff0000ff"


def test_native_round_trip_with_special_chars() -> None:
    nodes = [
        GroupNode(name="Papers: AI", color="8a8a8aff"),
        GroupNode(name="ML | stuff", parent="Papers; AI"),
    ]
    serialized = serialize_native(nodes)
    parsed = parse_native(serialized)
    assert len(parsed) == 2
    assert parsed[0].name == "Papers: AI"
    assert parsed[1].name == "ML | stuff"
    assert parsed[1].parent == "Papers; AI"


def test_native_empty_value() -> None:
    assert parse_native("") == []
    assert parse_native("   ") == []


def test_native_multiline_parsing() -> None:
    """parse_native accepts newline-separated multiline format."""
    value = "Papers||2|8a8a8aff|1|\nML|Papers|2||1|\nDeep Learning|ML|2|ff0000ff|1|"
    parsed = parse_native(value)
    assert len(parsed) == 3
    assert parsed[0].name == "Papers"
    assert parsed[1].name == "ML"
    assert parsed[1].parent == "Papers"
    assert parsed[2].name == "Deep Learning"
    assert parsed[2].parent == "ML"


def test_native_multiline_and_semicolon_mixed() -> None:
    """parse_native handles a line with semicolons AND multiline."""
    value = "Papers||2|8a8a8aff|1|\nML|Papers|2||1|; Deep Learning|ML|2|ff0000ff|1|"
    parsed = parse_native(value)
    assert len(parsed) == 3


def test_native_multiline_empty_lines_are_skipped() -> None:
    value = "A||2||1|\n\nB|A|2||1|"
    parsed = parse_native(value)
    assert len(parsed) == 2


# ---------------------------------------------------------------------------
# Metadata pipeline — continuation lines in pynakes-meta
# ---------------------------------------------------------------------------


def test_parse_metadata_comment_with_continuation_lines() -> None:
    """Continuation lines (indented) append to the previous block's value."""
    from pynakes.metadata import parse_metadata_comment

    comment = """pynakes-meta: group-tree: A||2||1|
  B|A|2||1|
  C|A|2||1|"""
    blocks = parse_metadata_comment(comment)
    assert len(blocks) == 1
    assert blocks[0].key == "group-tree"
    assert blocks[0].value == "A||2||1|\nB|A|2||1|\nC|A|2||1|"


def test_parse_metadata_comment_non_continuation_lines() -> None:
    """A line without colon and without leading whitespace is not a continuation."""
    from pynakes.metadata import parse_metadata_comment

    comment = """pynakes-meta: group-tree: A||2||1|
B|A|2||1|"""
    blocks = parse_metadata_comment(comment)
    # Second line has no leading whitespace and no colon: skipped
    assert len(blocks) == 1
    assert blocks[0].value == "A||2||1|"


def test_format_pynakes_meta_block_with_multiline_value() -> None:
    """A value containing \\n is split across continuation lines."""
    from pynakes.metadata.core import format_pynakes_meta_block

    result = format_pynakes_meta_block([("group-tree", "A||2||1|\nB|A|2||1|")])
    assert "group-tree: A||2||1|" in result
    assert "  B|A|2||1|" in result


def test_format_pynakes_meta_block_with_singleline_value() -> None:
    """A value without \\n remains a single line."""
    from pynakes.metadata.core import format_pynakes_meta_block

    result = format_pynakes_meta_block([("group-tree", "A||2||1|")])
    assert "group-tree: A||2||1|" in result
    assert "  " not in result  # no indented continuation lines


def test_multiline_write_tree() -> None:
    """A multi-node tree is written as multiline (>1 node → continuation lines)."""
    from pynakes.group_tree import add_node, list_tree
    from pynakes.model import BibFile

    lib = BibFile()
    lib.pynakes_metadata_blocks = []

    add_node(lib, "Papers", color="8a8a8aff")
    # Single node: still single-line
    for block in lib.pynakes_metadata_blocks:
        if block.key.lower() == "group-tree":
            assert "\n" not in block.value
            break

    add_node(lib, "ML", parent="Papers")
    # Two nodes: now multiline
    for block in lib.pynakes_metadata_blocks:
        if block.key.lower() == "group-tree":
            assert "\n" in block.value
            break

    tree = list_tree(lib)
    assert tree is not None and len(tree) == 2


# ---------------------------------------------------------------------------
# JabRef grouping format
# ---------------------------------------------------------------------------


def test_parse_jabref_grouping() -> None:
    value = """0 AllEntriesGroup:;
1 StaticGroup:Papers;0;1;8a8a8aff;;;
2 StaticGroup:ML;1;1;;;;
3 StaticGroup:Deep Learning;2;1;ff0000ff;;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 3
    assert nodes[0].name == "Papers"
    assert nodes[0].parent == ""
    assert nodes[0].color == "8a8a8aff"
    assert nodes[1].name == "ML"
    assert nodes[1].parent == "Papers"
    assert nodes[1].context == 1
    assert nodes[2].name == "Deep Learning"
    assert nodes[2].parent == "ML"
    assert nodes[2].context == 2
    assert nodes[2].color == "ff0000ff"


def test_parse_jabref_grouping_escaped_colon() -> None:
    """Group names with escaped colons in the flat JabRef format."""
    value = """0 AllEntriesGroup:;
1 StaticGroup:Machine Learning\\:AI;0;1;;;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    assert nodes[0].name == "Machine Learning:AI"


def test_format_jabref_grouping() -> None:
    nodes = [
        GroupNode(name="Papers", color="8a8a8aff"),
        GroupNode(name="ML", parent="Papers"),
    ]
    result = format_jabref_grouping(nodes)
    assert "0 AllEntriesGroup:;" in result
    assert "StaticGroup:Papers;" in result
    assert "StaticGroup:ML;" in result


def test_jabref_grouping_round_trip() -> None:
    value = """0 AllEntriesGroup:;
1 StaticGroup:Papers;0;1;8a8a8aff;;;
2 StaticGroup:ML;1;1;;;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 2
    result = format_jabref_grouping(nodes)
    assert "StaticGroup:Papers;0;1;8a8a8aff;;;" in result
    assert "StaticGroup:ML;1;1;;;;" in result


def test_parse_keyword_group() -> None:
    """KeywordGroup: name;context;field;expression;case;separator;;"""
    value = """0 AllEntriesGroup:;
1 KeywordGroup:ML;0;keywords;machine learning;0;\\;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.name == "ML"
    assert n.group_type == "KeywordGroup"
    assert n.field == "keywords"
    assert n.expression == "machine learning"
    assert n.case_sensitive is False
    assert n.separator == ";"


def test_parse_keyword_group_case_sensitive() -> None:
    value = """0 AllEntriesGroup:;
1 KeywordGroup:AI;0;title;Artificial Intelligence;1;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.field == "title"
    assert n.expression == "Artificial Intelligence"
    assert n.case_sensitive is True
    assert n.separator == ""


def test_parse_search_group() -> None:
    """SearchGroup: name;context;expression;flags;;"""
    value = """0 AllEntriesGroup:;
1 SearchGroup:Deep Learning;1;\\"deep learning\\";0;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.name == "Deep Learning"
    assert n.group_type == "SearchGroup"
    assert '"deep learning"' in n.expression
    assert n.search_flags == "0"


def test_parse_explicit_group() -> None:
    """ExplicitGroup: name;context;expanded;color;key1;key2;..."""
    value = """0 AllEntriesGroup:;
1 ExplicitGroup:My Papers;0;1;;Smith2020;Jones2021;Doe2022;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.name == "My Papers"
    assert n.group_type == "ExplicitGroup"
    assert n.expanded is True
    assert n.entries == ("Smith2020", "Jones2021", "Doe2022")


def test_parse_explicit_group_collapsed_with_color() -> None:
    value = """0 AllEntriesGroup:;
1 ExplicitGroup:Selected;0;0;8a8a8aff;KeyA;KeyB;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.expanded is False
    assert n.color == "8a8a8aff"
    assert n.entries == ("KeyA", "KeyB")


def test_format_keyword_group() -> None:
    nodes = [
        GroupNode(
            name="ML",
            context=0,
            group_type="KeywordGroup",
            field="keywords",
            expression="machine learning",
            case_sensitive=False,
            separator=",",
        ),
    ]
    result = format_jabref_grouping(nodes)
    assert "KeywordGroup:ML;0;keywords;machine learning;0;,;;;" in result


def test_format_search_group() -> None:
    nodes = [
        GroupNode(
            name="Deep Learning",
            context=0,
            group_type="SearchGroup",
            expression='"deep learning"',
            search_flags="0",
        ),
    ]
    result = format_jabref_grouping(nodes)
    assert 'SearchGroup:Deep Learning;0;"deep learning";0;;;' in result


def test_format_explicit_group() -> None:
    nodes = [
        GroupNode(
            name="Selected Papers",
            context=0,
            group_type="ExplicitGroup",
            expanded=True,
            color="8a8a8aff",
            entries=("Smith2020", "Jones2021"),
        ),
    ]
    result = format_jabref_grouping(nodes)
    assert "ExplicitGroup:Selected Papers;0;1;8a8a8aff;Smith2020;Jones2021;" in result


def test_all_group_types_round_trip() -> None:
    """Parse a JabRef grouping with all types, format, and verify they match."""
    grouping = """0 AllEntriesGroup:;
1 StaticGroup:Papers;0;1;8a8a8aff;;;
2 KeywordGroup:ML;0;keywords;machine learning;0;,;;
2 SearchGroup:Deep Learning;1;"deep learning";0;;
3 ExplicitGroup:Subset;1;1;;KeyA;KeyB;
"""
    nodes = parse_jabref_grouping(grouping)
    assert len(nodes) == 4

    result = format_jabref_grouping(nodes)
    # Round-trip: re-parse the formatted output
    nodes2 = parse_jabref_grouping(result)
    assert len(nodes2) == 4

    for n, n2 in zip(nodes, nodes2):
        assert n.name == n2.name
        assert n.group_type == n2.group_type
        assert n.context == n2.context
        assert n.color == n2.color
        assert n.expanded == n2.expanded
        assert n.field == n2.field
        assert n.expression == n2.expression
        assert n.case_sensitive == n2.case_sensitive
        assert n.separator == n2.separator
        assert n.search_flags == n2.search_flags
        assert n.entries == n2.entries


# ---------------------------------------------------------------------------
# Flat JabRef groups format
# ---------------------------------------------------------------------------


def test_parse_jabref_groups_lines() -> None:
    lines = [
        "groups:0 All Papers:;",
        r"groups:1 Machine Learning\:AI Papers:;",
        "groups:1 Blockchain:;",
    ]
    nodes = parse_jabref_groups_lines(lines)
    assert len(nodes) == 3
    assert nodes[0].name == "All Papers"
    assert nodes[1].name == "Machine Learning:AI Papers"
    assert nodes[1].parent == "All Papers"
    assert nodes[2].name == "Blockchain"
    assert nodes[2].parent == "All Papers"


# ---------------------------------------------------------------------------
# Library-level reads
# ---------------------------------------------------------------------------


def test_library_group_tree_from_native() -> None:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Papers", color="8a8a8aff")
    add_node(lib, "ML", parent="Papers")
    tree = library_group_tree(lib)
    assert tree is not None
    assert len(tree) == 2


def test_library_group_tree_from_jabref_grouping() -> None:
    text = """@comment{jabref-meta: grouping:
0 AllEntriesGroup:;
1 StaticGroup:Papers;0;1;;;;
}
@article{A, author = {X}, title = {Y}, journal = {Z}, year = {2020}}"""
    lib = parse_bib(text)
    tree = library_group_tree(lib)
    assert tree is not None
    assert len(tree) == 1
    assert tree[0].name == "Papers"


def test_library_group_tree_from_flat_groups() -> None:
    text = r"""@comment{jabref-meta: groupsversion:3;}
@comment{jabref-meta: groups:0 All Papers:;}
@comment{jabref-meta: groups:1 ML\::;}
@article{A, author = {X}, title = {Y}, journal = {Z}, year = {2020}}"""
    lib = parse_bib(text)
    tree = library_group_tree(lib)
    assert tree is not None
    assert any(n.name == "ML:" for n in tree)


def test_library_group_tree_none() -> None:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    assert library_group_tree(lib) is None


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def _fresh_lib() -> BibFile:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    return lib


def test_add_node() -> None:
    lib = _fresh_lib()
    assert add_node(lib, "Papers", color="8a8a8aff")
    assert add_node(lib, "ML", parent="Papers")
    assert not add_node(lib, "ML", parent="Papers")  # duplicate
    tree = list_tree(lib)
    assert tree is not None
    assert len(tree) == 2


def test_remove_node() -> None:
    lib = _fresh_lib()
    add_node(lib, "A")
    add_node(lib, "B", parent="A")
    add_node(lib, "C", parent="B")
    count = remove_node(lib, "A")
    assert count == 3  # A + B + C
    assert list_tree(lib) is None


def test_remove_node_not_found() -> None:
    lib = _fresh_lib()
    assert remove_node(lib, "Nope") == 0


def test_rename_node() -> None:
    lib = _fresh_lib()
    add_node(lib, "NLP")
    add_node(lib, "DL", parent="NLP")
    assert rename_node(lib, "NLP", "Natural Language Processing")
    tree = list_tree(lib)
    assert tree is not None
    assert tree[0].name == "Natural Language Processing"
    assert tree[1].parent == "Natural Language Processing"


def test_rename_node_not_found() -> None:
    lib = _fresh_lib()
    assert not rename_node(lib, "Nope", "Something")


def test_move_node() -> None:
    lib = _fresh_lib()
    add_node(lib, "A")
    add_node(lib, "B")
    add_node(lib, "C", parent="A")
    assert move_node(lib, "C", "B")
    tree = list_tree(lib)
    assert tree is not None
    c = [n for n in tree if n.name == "C"][0]
    assert c.parent == "B"


def test_move_node_circular() -> None:
    lib = _fresh_lib()
    add_node(lib, "A")
    add_node(lib, "B", parent="A")
    # Moving A under B would create a cycle
    assert not move_node(lib, "A", "B")


def test_move_node_to_root() -> None:
    lib = _fresh_lib()
    add_node(lib, "A")
    add_node(lib, "B", parent="A")
    assert move_node(lib, "B", "")
    tree = list_tree(lib)
    assert tree is not None
    b = [n for n in tree if n.name == "B"][0]
    assert b.parent == ""


def test_update_node() -> None:
    lib = _fresh_lib()
    add_node(lib, "Papers", color="8a8a8aff")
    assert update_node(lib, "Papers", color="ff0000ff", context=1)
    tree = list_tree(lib)
    assert tree is not None
    assert tree[0].color == "ff0000ff"
    assert tree[0].context == 1


def test_update_node_not_found() -> None:
    lib = _fresh_lib()
    assert not update_node(lib, "Nope", color="red")


# ---------------------------------------------------------------------------
# Tree-aware entry queries
# ---------------------------------------------------------------------------


def test_entry_group_names() -> None:
    entry = BibEntry(key="A", type="article", fields={"groups": "ML; Deep Learning"})
    assert entry_group_names(entry) == ["ML", "Deep Learning"]


def test_entry_group_names_empty() -> None:
    entry = BibEntry(key="A", type="article", fields={})
    assert entry_group_names(entry) == []


def test_list_entries_in_group_tree_with_tree() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    add_node(lib, "NLP", parent="ML")
    lib.entries.add(BibEntry(key="A", type="article", fields={}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "Deep Learning"}))
    lib.entries.add(BibEntry(key="C", type="article", fields={"groups": "NLP"}))
    lib.entries.add(BibEntry(key="D", type="article", fields={"groups": "ML"}))
    # Non-strict: ML includes its descendants
    result = list_entries_in_group_tree(lib, "ML")
    assert "B" in result
    assert "C" in result
    assert "D" in result
    assert "A" not in result


def test_list_entries_in_group_tree_strict() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "Deep Learning"}))
    lib.entries.add(BibEntry(key="D", type="article", fields={"groups": "ML"}))
    result = list_entries_in_group_tree(lib, "ML", strict=True)
    assert result == ["D"]


def test_list_entries_in_group_tree_no_tree() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "ML"}))
    # Without a tree, falls back to exact match
    result = list_entries_in_group_tree(lib, "ML")
    assert result == ["A"]


def test_resolve_effective_groups() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    entry = BibEntry(key="A", type="article", fields={"groups": "Deep Learning"})
    effective = resolve_effective_groups(lib, entry)
    assert "Deep Learning" in effective
    assert "ML" in effective


def test_resolve_effective_groups_no_tree() -> None:
    lib = _fresh_lib()
    entry = BibEntry(key="A", type="article", fields={"groups": "Deep Learning"})
    assert resolve_effective_groups(lib, entry) == ["Deep Learning"]


# ---------------------------------------------------------------------------
# Dynamic group evaluation — KeywordGroup
# ---------------------------------------------------------------------------


def test_matches_keyword_group_exact() -> None:
    ml_kw = GroupNode(
        name="ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    entry_match = BibEntry(
        key="A", type="article", fields={"keywords": "deep learning; machine learning; ai"}
    )
    entry_no_match = BibEntry(key="B", type="article", fields={"keywords": "machine-learning; ai"})
    assert _matches_keyword_group(entry_match, ml_kw) is True
    assert _matches_keyword_group(entry_no_match, ml_kw) is False


def test_matches_keyword_group_case_sensitive() -> None:
    cs = GroupNode(
        name="ML", group_type="KeywordGroup", field="keywords", expression="ML", case_sensitive=True
    )
    ci = GroupNode(
        name="ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="ML",
        case_sensitive=False,
    )
    entry = BibEntry(key="A", type="article", fields={"keywords": "ml"})
    assert _matches_keyword_group(entry, cs) is False
    assert _matches_keyword_group(entry, ci) is True


def test_matches_keyword_group_substring() -> None:
    kw = GroupNode(name="TF", group_type="KeywordGroup", field="title", expression="transformer")
    entry_match = BibEntry(
        key="A", type="article", fields={"title": "A Transformer-Based Approach"}
    )
    entry_no_match = BibEntry(
        key="B", type="article", fields={"title": "Attention Is All You Need"}
    )
    assert _matches_keyword_group(entry_match, kw) is True
    assert _matches_keyword_group(entry_no_match, kw) is False


def test_matches_keyword_group_empty_field() -> None:
    empty_expr = GroupNode(name="G", group_type="KeywordGroup", field="keywords", expression="")
    empty_field = GroupNode(name="G", group_type="KeywordGroup", field="", expression="test")
    entry = BibEntry(key="A", type="article", fields={"keywords": "test"})
    assert _matches_keyword_group(entry, empty_expr) is False
    assert _matches_keyword_group(entry, empty_field) is False


# ---------------------------------------------------------------------------
# Dynamic group evaluation — SearchGroup
# ---------------------------------------------------------------------------


def test_matches_search_group() -> None:
    sg = GroupNode(name="TF", group_type="SearchGroup", expression="transformer")
    entry_match = BibEntry(
        key="A", type="article", fields={"title": "A Transformer Model", "author": "Smith"}
    )
    entry_no_match = BibEntry(
        key="B", type="article", fields={"title": "Attention Mechanism", "author": "Jones"}
    )
    assert _matches_search_group(entry_match, sg) is True
    assert _matches_search_group(entry_no_match, sg) is False


def test_matches_search_group_case_sensitive() -> None:
    cs = GroupNode(name="TF", group_type="SearchGroup", expression="Transformer", search_flags="1")
    entry = BibEntry(key="A", type="article", fields={"title": "a transformer model"})
    assert _matches_search_group(entry, cs) is False


def test_matches_search_group_empty() -> None:
    sg = GroupNode(name="G", group_type="SearchGroup", expression="")
    entry = BibEntry(key="A", type="article", fields={"title": "anything"})
    assert _matches_search_group(entry, sg) is False


# ---------------------------------------------------------------------------
# _group_entry_keys
# ---------------------------------------------------------------------------


def test_group_entry_keys_keyword() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(BibEntry(key="A", type="article", fields={"keywords": "machine learning"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"keywords": "deep learning"}))
    node = _node_by_name(library_group_tree(lib) or [], "ML")
    assert node is not None
    keys = _group_entry_keys(lib, node)
    assert "A" in keys
    assert "B" not in keys


def test_group_entry_keys_combined_explicit_and_dynamic() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(
        BibEntry(key="A", type="article", fields={"keywords": "machine learning", "groups": "ML"})
    )
    lib.entries.add(BibEntry(key="B", type="article", fields={"keywords": "machine learning"}))
    lib.entries.add(
        BibEntry(key="C", type="article", fields={"keywords": "deep learning", "groups": "ML"})
    )
    node = _node_by_name(library_group_tree(lib) or [], "ML")
    assert node is not None
    keys = _group_entry_keys(lib, node)
    assert "A" in keys
    assert "B" in keys
    assert "C" in keys


# ---------------------------------------------------------------------------
# entry_computed_groups
# ---------------------------------------------------------------------------


def test_entry_computed_groups() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(BibEntry(key="A", type="article", fields={"keywords": "machine learning"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"keywords": "deep learning"}))
    assert entry_computed_groups(lib, "A") == ["ML"]
    assert entry_computed_groups(lib, "B") == []


def test_entry_computed_groups_search() -> None:
    lib = _fresh_lib()
    add_node(lib, "Deep Learning")
    update_node(lib, "Deep Learning", group_type="SearchGroup", expression="deep learning")
    lib.entries.add(BibEntry(key="A", type="article", fields={"title": "On Deep Learning Methods"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"title": "Shallow Networks"}))
    assert "Deep Learning" in entry_computed_groups(lib, "A")
    assert entry_computed_groups(lib, "B") == []


def test_entry_computed_groups_no_tree() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"keywords": "machine learning"}))
    assert entry_computed_groups(lib, "A") == []


# ---------------------------------------------------------------------------
# Integration tests — list_entries_in_group_tree with dynamic groups
# ---------------------------------------------------------------------------


def test_list_entries_in_group_tree_dynamic() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    add_node(lib, "Deep Learning")
    update_node(lib, "Deep Learning", group_type="SearchGroup", expression="deep learning")
    lib.entries.add(BibEntry(key="A", type="article", fields={"keywords": "machine learning"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"title": "Deep Learning Advances"}))
    lib.entries.add(BibEntry(key="C", type="article", fields={"title": "Other Stuff"}))
    ml_entries = list_entries_in_group_tree(lib, "ML")
    dl_entries = list_entries_in_group_tree(lib, "Deep Learning")
    assert "A" in ml_entries
    assert "C" not in ml_entries
    assert "B" in dl_entries
    assert "C" not in dl_entries


def test_list_entries_in_group_tree_combined() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(
        BibEntry(key="A", type="article", fields={"keywords": "machine learning", "groups": "ML"})
    )
    result = list_entries_in_group_tree(lib, "ML")
    assert result == ["A"]


def test_list_entries_in_group_tree_strict_dynamic() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(BibEntry(key="A", type="article", fields={"keywords": "machine learning"}))
    result = list_entries_in_group_tree(lib, "ML", strict=True)
    assert "A" in result


# ---------------------------------------------------------------------------
# Integration tests — resolve_effective_groups with dynamic groups
# ---------------------------------------------------------------------------


def test_resolve_effective_groups_with_dynamic() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    update_node(
        lib, "Deep Learning", group_type="KeywordGroup", field="title", expression="deep learning"
    )
    entry = BibEntry(key="A", type="article", fields={"title": "Deep Learning Advances"})
    lib.entries.add(entry)
    effective = resolve_effective_groups(lib, entry)
    assert "Deep Learning" in effective
    assert "ML" in effective


# ---------------------------------------------------------------------------
# Round-trip / regression
# ---------------------------------------------------------------------------


def test_keyword_group_still_round_trips() -> None:
    grouping = """0 AllEntriesGroup:;
1 KeywordGroup:ML;0;keywords;machine learning;0;,;;
"""
    nodes = parse_jabref_grouping(grouping)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.group_type == "KeywordGroup"
    assert n.field == "keywords"
    assert n.expression == "machine learning"
    assert n.case_sensitive is False
    assert n.separator == ","
    result = format_jabref_grouping(nodes)
    nodes2 = parse_jabref_grouping(result)
    assert nodes[0].name == nodes2[0].name
    assert nodes[0].group_type == nodes2[0].group_type
    assert nodes[0].field == nodes2[0].field
    assert nodes[0].expression == nodes2[0].expression
    assert nodes[0].case_sensitive == nodes2[0].case_sensitive
    assert nodes[0].separator == nodes2[0].separator


# ---------------------------------------------------------------------------
# Regression: ExplicitGroup inline entries in _group_entry_keys
# ---------------------------------------------------------------------------


def test_group_entry_keys_explicit_group_inline() -> None:
    lib = _fresh_lib()
    add_node(lib, "Selected")
    update_node(lib, "Selected", group_type="ExplicitGroup", entries=("KeyA", "KeyB"))
    lib.entries.add(BibEntry(key="KeyA", type="article", fields={}))
    lib.entries.add(BibEntry(key="KeyB", type="article", fields={}))
    lib.entries.add(BibEntry(key="C", type="article", fields={}))
    node = _node_by_name(library_group_tree(lib) or [], "Selected")
    assert node is not None
    keys = _group_entry_keys(lib, node)
    assert "KeyA" in keys
    assert "KeyB" in keys
    assert "C" not in keys


def test_list_entries_in_group_tree_explicit_inline() -> None:
    lib = _fresh_lib()
    add_node(lib, "Selected")
    update_node(lib, "Selected", group_type="ExplicitGroup", entries=("KeyA", "KeyB"))
    lib.entries.add(BibEntry(key="KeyA", type="article", fields={}))
    lib.entries.add(BibEntry(key="KeyB", type="article", fields={}))
    lib.entries.add(BibEntry(key="C", type="article", fields={}))
    keys = list_entries_in_group_tree(lib, "Selected")
    assert "KeyA" in keys
    assert "KeyB" in keys
    assert "C" not in keys


# ---------------------------------------------------------------------------
# CLI: groups list-entries
# ---------------------------------------------------------------------------


def test_groups_list_entries_cli_includes_descendants(tmp_path: Path) -> None:
    lib = _fresh_lib()
    add_node(lib, "CS")
    add_node(lib, "ML", parent="CS")
    update_node(lib, "ML", group_type="ExplicitGroup", entries=("PaperA",))
    lib.entries.add(BibEntry(key="PaperA", type="article", fields={}))
    lib.entries.add(BibEntry(key="PaperB", type="article", fields={"groups": "CS"}))
    text = write_bib(lib)
    bib = tmp_path / "refs.bib"
    bib.write_text(text)

    result = CliRunner().invoke(app, ["groups", "list-entries", str(bib), "CS", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "groups_list_entries"
    assert data["group"] == "CS"
    assert data["strict"] is False
    # Descendant propagation: PaperA (in child ML) and PaperB (in CS itself).
    assert "PaperA" in data["entries"]
    assert "PaperB" in data["entries"]


def test_groups_list_entries_cli_strict_omits_descendants(tmp_path: Path) -> None:
    lib = _fresh_lib()
    add_node(lib, "CS")
    add_node(lib, "ML", parent="CS")
    update_node(lib, "ML", group_type="ExplicitGroup", entries=("PaperA",))
    lib.entries.add(BibEntry(key="PaperA", type="article", fields={}))
    lib.entries.add(BibEntry(key="PaperB", type="article", fields={"groups": "CS"}))
    text = write_bib(lib)
    bib = tmp_path / "refs.bib"
    bib.write_text(text)

    result = CliRunner().invoke(
        app, ["groups", "list-entries", str(bib), "CS", "--strict", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["strict"] is True
    # Strict mode: only PaperB (directly in CS), not PaperA (in ML).
    assert "PaperA" not in data["entries"]
    assert "PaperB" in data["entries"]


# ---------------------------------------------------------------------------
# Regression: CLI groups list uses tree-aware API
# ---------------------------------------------------------------------------


def test_group_entry_members_without_tree_still_works() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "ML"}))
    assert list_entries_in_group_tree(lib, "ML") == ["A"]


def test_group_entry_members_explicit_and_dynamic_deduplicated() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    update_node(
        lib,
        "ML",
        group_type="KeywordGroup",
        field="keywords",
        expression="machine learning",
        separator=";",
    )
    lib.entries.add(
        BibEntry(key="A", type="article", fields={"keywords": "machine learning", "groups": "ML"})
    )
    node = _node_by_name(library_group_tree(lib) or [], "ML")
    assert node is not None
    keys = _group_entry_keys(lib, node)
    assert len([k for k in keys if k == "A"]) == 1
