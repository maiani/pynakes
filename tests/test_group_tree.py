"""Tests for the group tree data model, native format, and CRUD operations."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.group_tree import (
    GroupNode,
    _descendant_names,
    _escape,
    _group_entry_keys,
    _matches_keyword_group,
    _matches_search_group,
    _node_by_name,
    _split_escaped,
    _unescape,
    add_node,
    format_jabref_grouping,
    known_group_names,
    library_group_tree,
    list_direct_members,
    list_entries_in_group_tree,
    list_tree,
    move_node,
    parse_jabref_grouping,
    parse_jabref_groups_lines,
    parse_native,
    remove_node,
    rename_node,
    serialize_native,
    update_node,
)
from pynakes.groups import entry_groups
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


def test_parse_metadata_comment_treats_indented_colon_as_continuation() -> None:
    """A colon in an indented group name does not start a metadata key."""
    from pynakes.metadata import parse_metadata_comment

    comment = """pynakes-meta: group-tree: Papers
  Machine Learning: AI|Papers"""
    blocks = parse_metadata_comment(comment)

    assert len(blocks) == 1
    assert blocks[0].key == "group-tree"
    assert blocks[0].value == "Papers\nMachine Learning: AI|Papers"


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
    assert "StaticGroup:Papers\\;" in result
    assert "StaticGroup:ML\\;" in result


def test_jabref_grouping_round_trip() -> None:
    value = """0 AllEntriesGroup:;
1 StaticGroup:Papers;0;1;8a8a8aff;;;
2 StaticGroup:ML;1;1;;;;
"""
    nodes = parse_jabref_grouping(value)
    assert len(nodes) == 2
    result = format_jabref_grouping(nodes)
    assert "StaticGroup:Papers\\;0\\;1\\;8a8a8aff\\;\\;\\;;" in result
    assert "StaticGroup:ML\\;1\\;1\\;\\;\\;\\;;" in result


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
    assert "KeywordGroup:ML\\;0\\;keywords\\;machine learning\\;0\\;,\\;\\;\\;;" in result


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
    assert 'SearchGroup:Deep Learning\\;0\\;"deep learning"\\;0\\;\\;\\;;' in result


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
    assert "ExplicitGroup:Selected Papers\\;0\\;1\\;8a8a8aff\\;Smith2020\\;Jones2021\\;;" in result


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


def test_entry_groups() -> None:
    entry = BibEntry(key="A", type="article", fields={"groups": "ML; Deep Learning"})
    assert entry_groups(entry) == ["ML", "Deep Learning"]


def test_entry_groups_empty() -> None:
    entry = BibEntry(key="A", type="article", fields={})
    assert entry_groups(entry) == []


def test_list_entries_in_group_tree_with_tree() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    add_node(lib, "NLP", parent="ML")
    lib.entries.add(BibEntry(key="A", type="article", fields={}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "Deep Learning"}))
    lib.entries.add(BibEntry(key="C", type="article", fields={"groups": "NLP"}))
    lib.entries.add(BibEntry(key="D", type="article", fields={"groups": "ML"}))
    # Not exact: ML includes its descendants
    result = list_entries_in_group_tree(lib, "ML")
    assert "B" in result
    assert "C" in result
    assert "D" in result
    assert "A" not in result


def test_list_entries_in_group_tree_exact() -> None:
    lib = _fresh_lib()
    add_node(lib, "ML")
    add_node(lib, "Deep Learning", parent="ML")
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "Deep Learning"}))
    lib.entries.add(BibEntry(key="D", type="article", fields={"groups": "ML"}))
    result = list_entries_in_group_tree(lib, "ML", exact=True)
    assert result == ["D"]


def test_list_entries_in_group_tree_no_tree() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "ML"}))
    # Without a tree, falls back to exact match
    result = list_entries_in_group_tree(lib, "ML")
    assert result == ["A"]


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


def test_list_entries_in_group_tree_exact_dynamic() -> None:
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
    result = list_entries_in_group_tree(lib, "ML", exact=True)
    assert "A" in result


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
    assert data["exact"] is False
    # Descendant propagation: PaperA (in child ML) and PaperB (in CS itself).
    assert "PaperA" in data["entries"]
    assert "PaperB" in data["entries"]


def test_groups_list_entries_cli_exact_omits_descendants(tmp_path: Path) -> None:
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
        app, ["groups", "list-entries", str(bib), "CS", "--exact", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["exact"] is True
    # Exact mode: only PaperB (directly in CS), not PaperA (in ML).
    assert "PaperA" not in data["entries"]
    assert "PaperB" in data["entries"]


# ---------------------------------------------------------------------------
# Regression: metadata-only group-tree CRUD must persist through the CLI
# ---------------------------------------------------------------------------


def test_groups_add_group_cli_persists_on_fresh_library(tmp_path: Path) -> None:
    # Regression: `groups add-group` on a library with no group-tree reported
    # success while writing nothing — the commit gate saw modified=False because
    # the metadata-only change was never staged for the surgical renderer.
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Bardeen1948,\n  title = {The Transistor}\n}\n")

    r1 = CliRunner().invoke(app, ["groups", "add-group", str(bib), "Devices", "--json"])
    assert r1.exit_code == 0, r1.output
    assert json.loads(r1.output)["modified"] is True
    assert "group-tree" in bib.read_text()

    # A second node bootstraps a real hierarchy through the CLI alone.
    r2 = CliRunner().invoke(
        app, ["groups", "add-group", str(bib), "Transistors", "--parent", "Devices", "--json"]
    )
    assert r2.exit_code == 0, r2.output

    tree = list_tree(parse_bib(bib.read_text()))
    assert tree is not None
    assert {n.name for n in tree} == {"Devices", "Transistors"}


def test_groups_remove_group_cli_persists(tmp_path: Path) -> None:
    # The same commit-gate bug affected remove/rename/move; verify remove persists.
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Keep")
    add_node(lib, "Drop")
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib))

    result = CliRunner().invoke(app, ["groups", "remove-group", str(bib), "Drop", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["modified"] is True
    tree = list_tree(parse_bib(bib.read_text()))
    assert tree is not None
    assert {n.name for n in tree} == {"Keep"}


def test_groups_cli_human_views_and_tree_lifecycle(tmp_path: Path) -> None:
    """Exercise the human-facing group views and all tree mutation commands."""
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Noether1918,\n  title = {Invariant Variational Problems}\n}\n")
    runner = CliRunner()

    empty = runner.invoke(app, ["groups", "tree", str(bib)])
    assert empty.exit_code == 0, empty.output
    assert "no group tree defined" in empty.output

    add_root = runner.invoke(
        app,
        ["groups", "add-group", str(bib), "Physics", "--color", "8a8a8aff"],
    )
    assert add_root.exit_code == 0, add_root.output
    add_child = runner.invoke(
        app,
        ["groups", "add-group", str(bib), "Symmetry", "--parent", "Physics"],
    )
    assert add_child.exit_code == 0, add_child.output

    shown = runner.invoke(app, ["groups", "tree", str(bib)])
    assert shown.exit_code == 0, shown.output
    assert "+ Physics [8a8a8aff]" in shown.output
    assert "  + Symmetry" in shown.output

    listed = runner.invoke(app, ["groups", "list", str(bib)])
    assert listed.exit_code == 0, listed.output
    assert "Physics (0)" in listed.output

    updated = runner.invoke(
        app,
        [
            "groups",
            "update-group",
            str(bib),
            "Symmetry",
            "--description",
            "Symmetry papers",
            "--color",
            "ff0000ff",
            "--context",
            "refining",
            "--collapsed",
        ],
    )
    assert updated.exit_code == 0, updated.output
    renamed = runner.invoke(app, ["groups", "rename-group", str(bib), "Symmetry", "Field Theory"])
    assert renamed.exit_code == 0, renamed.output
    moved = runner.invoke(app, ["groups", "move-group", str(bib), "Field Theory", "--parent", ""])
    assert moved.exit_code == 0, moved.output

    add_entry = runner.invoke(app, ["groups", "add-entry", str(bib), "Noether1918", "Field Theory"])
    assert add_entry.exit_code == 0, add_entry.output
    entries = runner.invoke(app, ["groups", "list-entries", str(bib), "Field Theory"])
    assert entries.exit_code == 0, entries.output
    assert "Noether1918" in entries.output
    remove_entry = runner.invoke(
        app, ["groups", "remove-entry", str(bib), "Noether1918", "Field Theory"]
    )
    assert remove_entry.exit_code == 0, remove_entry.output

    removed = runner.invoke(app, ["groups", "remove-group", str(bib), "Field Theory"])
    assert removed.exit_code == 0, removed.output


def test_groups_cli_structured_errors(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Noether1918,\n  title = {Invariant Variational Problems}\n}\n")
    runner = CliRunner()

    # A missing group is KeyNotFound everywhere; an existing one is a conflict.
    for args, error, exit_code in (
        (["add-entry", str(bib), "Missing", "Physics"], "KeyNotFound", 1),
        (["add-entry", str(bib), "Noether1918", "Physics"], "KeyNotFound", 1),
        (["add-group", str(bib), "Physics"], None, 0),
        (["add-group", str(bib), "Physics"], "GroupConflict", 2),
        (["add-group", str(bib), "Waves", "--parent", "Missing"], "KeyNotFound", 1),
        (["remove-entry", str(bib), "Noether1918", "Missing"], "KeyNotFound", 1),
        (["remove-group", str(bib), "Missing"], "KeyNotFound", 1),
        (["rename-group", str(bib), "Missing", "Other"], "KeyNotFound", 1),
        (["add-group", str(bib), "Optics"], None, 0),
        (["rename-group", str(bib), "Optics", "Physics"], "GroupConflict", 2),
        (["move-group", str(bib), "Missing"], "KeyNotFound", 1),
        (["move-group", str(bib), "Optics", "--parent", "Missing"], "KeyNotFound", 1),
        (["update-group", str(bib), "Missing"], "KeyNotFound", 1),
        (["update-group", str(bib), "Optics", "--parent", "Missing"], "KeyNotFound", 1),
    ):
        result = runner.invoke(app, ["groups", *args, "--json"])
        assert result.exit_code == exit_code, (args, result.output)
        if error is not None:
            assert json.loads(result.output)["error"] == error


def test_add_entry_create_makes_a_new_group(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Noether1918,\n  title = {Invariant Variational Problems}\n}\n")

    result = CliRunner().invoke(
        app, ["groups", "add-entry", str(bib), "Noether1918", "Physics", "--create", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert "groups = {Physics}" in bib.read_text()


# ---------------------------------------------------------------------------
# Regression: `groups add-entry` keeps the group-tree in sync
# ---------------------------------------------------------------------------


def test_add_entry_registers_group_in_existing_tree(tmp_path: Path) -> None:
    # Regression: adding an entry to a group absent from an existing tree left an
    # orphan membership invisible to `groups tree`/`groups list` and JabRef. The
    # group is now registered as a node so the membership is addressable.
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Papers")
    lib.entries.add(BibEntry(key="Shockley1949", type="article", fields={"title": "PN"}))
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib))

    result = CliRunner().invoke(
        app,
        ["groups", "add-entry", str(bib), "Shockley1949", "Semiconductors", "--create", "--json"],
    )

    assert result.exit_code == 0, result.output
    reparsed = parse_bib(bib.read_text())
    tree = list_tree(reparsed)
    assert tree is not None
    assert {n.name for n in tree} == {"Papers", "Semiconductors"}
    assert list_entries_in_group_tree(reparsed, "Semiconductors") == ["Shockley1949"]


def test_add_entry_on_treeless_library_creates_no_tree(tmp_path: Path) -> None:
    # A flat, tree-less library keeps entry-field-only groups: add-entry must not
    # synthesize a group-tree behind the user's back (`groups list` still shows it).
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Bardeen1948,\n  title = {Transistor}\n}\n")

    result = CliRunner().invoke(
        app, ["groups", "add-entry", str(bib), "Bardeen1948", "Devices", "--create", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert list_tree(parse_bib(bib.read_text())) is None
    assert "groups = {Devices}" in bib.read_text()


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


# ---------------------------------------------------------------------------
# Fix 1: `groups list` must union flat tags and tree nodes, direct members only
# ---------------------------------------------------------------------------


def test_known_group_names_union_flat_and_tree() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "FlatGroup"}))
    add_node(lib, "TreeGroup")
    # An unrelated tree node must not hide the flat-only tag.
    assert known_group_names(lib) == ["TreeGroup", "FlatGroup"]


def test_known_group_names_no_tree_is_flat_only() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "FlatGroup"}))
    assert known_group_names(lib) == ["FlatGroup"]


def test_list_direct_members_flat_only_with_unrelated_tree() -> None:
    lib = _fresh_lib()
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "FlatGroup"}))
    add_node(lib, "TreeGroup")
    # `list_entries_in_group_tree` alone would return [] here (FlatGroup has no
    # node), but the flat tag is still a real, direct membership.
    assert list_direct_members(lib, "FlatGroup") == ["A"]
    assert list_direct_members(lib, "TreeGroup") == []


def test_list_direct_members_excludes_descendants() -> None:
    lib = _fresh_lib()
    add_node(lib, "CS")
    add_node(lib, "ML", parent="CS")
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "CS"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "ML"}))
    assert list_direct_members(lib, "CS") == ["A"]
    assert list_direct_members(lib, "ML") == ["B"]


def test_groups_list_cli_flat_and_tree_union(tmp_path: Path) -> None:
    """Exact regression from the bug report: a flat-only group must survive the
    creation of an unrelated tree node, member list intact."""
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Euclid300BCE,\n"
        "  title = {On the Ratios of Straight Lines},\n"
        "  author = {Euclid}\n"
        "}\n"
    )
    runner = CliRunner()

    add_entry = runner.invoke(
        app, ["groups", "add-entry", str(bib), "Euclid300BCE", "FlatGroup", "--create", "--json"]
    )
    assert add_entry.exit_code == 0, add_entry.output

    before = runner.invoke(app, ["groups", "list", str(bib), "--json"])
    assert before.exit_code == 0, before.output
    before_data = json.loads(before.output)
    assert before_data["groups"] == {"FlatGroup": ["Euclid300BCE"]}

    add_group = runner.invoke(app, ["groups", "add-group", str(bib), "TreeGroup", "--json"])
    assert add_group.exit_code == 0, add_group.output

    after = runner.invoke(app, ["groups", "list", str(bib), "--json"])
    assert after.exit_code == 0, after.output
    after_data = json.loads(after.output)
    # FlatGroup and its member must not vanish once an unrelated tree exists.
    assert after_data["groups"]["FlatGroup"] == ["Euclid300BCE"]
    assert after_data["groups"]["TreeGroup"] == []
    assert after_data["status"] == "success"


# ---------------------------------------------------------------------------
# Fix 2: `update-group --expanded` can re-expand a collapsed node
# ---------------------------------------------------------------------------


def test_groups_update_group_cli_collapse_then_expand_roundtrip(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()

    assert runner.invoke(app, ["groups", "add-group", str(bib), "Geometry"]).exit_code == 0

    collapsed = runner.invoke(
        app, ["groups", "update-group", str(bib), "Geometry", "--collapsed", "--json"]
    )
    assert collapsed.exit_code == 0, collapsed.output
    tree_after_collapse = json.loads(
        runner.invoke(app, ["groups", "tree", str(bib), "--json"]).output
    )["tree"]
    assert tree_after_collapse[0]["expanded"] is False

    expanded = runner.invoke(
        app, ["groups", "update-group", str(bib), "Geometry", "--expanded", "--json"]
    )
    assert expanded.exit_code == 0, expanded.output
    tree_after_expand = json.loads(
        runner.invoke(app, ["groups", "tree", str(bib), "--json"]).output
    )["tree"]
    assert tree_after_expand[0]["expanded"] is True


# ---------------------------------------------------------------------------
# Fix 3: `update-group` empty-string clearing, and zero-flag no-op
# ---------------------------------------------------------------------------


def test_groups_update_group_cli_clears_parent_color_description(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()

    assert runner.invoke(app, ["groups", "add-group", str(bib), "Geometry"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "groups",
                "add-group",
                str(bib),
                "Postulates",
                "--parent",
                "Geometry",
            ],
        ).exit_code
        == 0
    )
    seeded = runner.invoke(
        app,
        [
            "groups",
            "update-group",
            str(bib),
            "Postulates",
            "--color",
            "8a8a8aff",
            "--description",
            "Five postulates",
            "--json",
        ],
    )
    assert seeded.exit_code == 0, seeded.output

    cleared = runner.invoke(
        app,
        [
            "groups",
            "update-group",
            str(bib),
            "Postulates",
            "--parent",
            "",
            "--color",
            "",
            "--description",
            "",
            "--json",
        ],
    )
    assert cleared.exit_code == 0, cleared.output

    tree = json.loads(runner.invoke(app, ["groups", "tree", str(bib), "--json"]).output)["tree"]
    node = next(n for n in tree if n["name"] == "Postulates")
    assert node["parent"] == ""
    assert node["color"] == ""
    assert node["description"] == ""


def test_groups_update_group_cli_zero_flags_reports_no_change(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()
    assert runner.invoke(app, ["groups", "add-group", str(bib), "Geometry"]).exit_code == 0

    before_text = bib.read_text()
    result = runner.invoke(app, ["groups", "update-group", str(bib), "Geometry", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["modified"] is False
    assert data["modified_entries"] == 0
    # A true no-op must not touch the file at all.
    assert bib.read_text() == before_text


def test_groups_update_group_cli_zero_flags_missing_group_still_errors(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    result = CliRunner().invoke(app, ["groups", "update-group", str(bib), "Missing", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "KeyNotFound"


# ---------------------------------------------------------------------------
# Fix 4: unknown group name errors on `list-entries`; a real-but-empty group
# still succeeds
# ---------------------------------------------------------------------------


def test_groups_list_entries_cli_unknown_name_errors(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()
    assert (
        runner.invoke(
            app, ["groups", "add-entry", str(bib), "Euclid300BCE", "FlatGroup", "--create"]
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["groups", "list-entries", str(bib), "TypoedName", "--json"])

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "KeyNotFound"


def test_groups_list_entries_cli_known_empty_group_succeeds(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()
    assert runner.invoke(app, ["groups", "add-group", str(bib), "Geometry"]).exit_code == 0

    result = runner.invoke(app, ["groups", "list-entries", str(bib), "Geometry", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["entries"] == []


# ---------------------------------------------------------------------------
# Fix 5: `groups tree --json` uses an explicit `to_dict()`, not `__dict__`
# ---------------------------------------------------------------------------


def test_group_node_to_dict_matches_dunder_dict() -> None:
    node = GroupNode(
        name="ML",
        parent="Physics",
        context=1,
        color="ff0000ff",
        expanded=False,
        description="desc",
        group_type="KeywordGroup",
        field="keywords",
        expression="deep learning",
        case_sensitive=True,
        separator=";",
        search_flags="1",
        entries=("A", "B"),
    )
    assert list(node.to_dict().keys()) == list(node.__dict__.keys())
    assert node.to_dict() == node.__dict__


def test_groups_tree_cli_json_keys_unchanged(tmp_path: Path) -> None:
    """`groups tree --json` must emit the exact same per-node keys as the old
    ``n.__dict__`` serialization (only the mechanism changed, not the contract)."""
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    runner = CliRunner()
    assert runner.invoke(app, ["groups", "add-group", str(bib), "Geometry"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "groups",
                "update-group",
                str(bib),
                "Geometry",
                "--color",
                "8a8a8aff",
                "--description",
                "Euclidean geometry",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["groups", "tree", str(bib), "--json"])
    assert result.exit_code == 0, result.output
    tree = json.loads(result.output)["tree"]
    assert len(tree) == 1

    expected_keys = [
        "name",
        "parent",
        "context",
        "color",
        "expanded",
        "description",
        "group_type",
        "field",
        "expression",
        "case_sensitive",
        "separator",
        "search_flags",
        "entries",
    ]
    assert list(tree[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Fix 6: `groups list-entries --exact` renames `--strict` (breaking change)
# ---------------------------------------------------------------------------


def test_groups_list_entries_cli_strict_flag_no_longer_exists(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Euclid300BCE,\n  title = {On the Ratios of Straight Lines}\n}\n")
    result = CliRunner().invoke(
        app, ["groups", "list-entries", str(bib), "Anything", "--strict", "--json"]
    )
    assert result.exit_code != 0
    assert "--strict" in result.output or "No such option" in result.output


def test_groups_list_entries_cli_exact_matches_old_strict_semantics(tmp_path: Path) -> None:
    lib = _fresh_lib()
    add_node(lib, "Geometry")
    add_node(lib, "Postulates", parent="Geometry")
    lib.entries.add(BibEntry(key="A", type="article", fields={"groups": "Geometry"}))
    lib.entries.add(BibEntry(key="B", type="article", fields={"groups": "Postulates"}))
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib))

    default = CliRunner().invoke(app, ["groups", "list-entries", str(bib), "Geometry", "--json"])
    exact = CliRunner().invoke(
        app, ["groups", "list-entries", str(bib), "Geometry", "--exact", "--json"]
    )

    assert default.exit_code == 0 and exact.exit_code == 0
    default_data = json.loads(default.output)
    exact_data = json.loads(exact.output)
    assert default_data["exact"] is False
    assert exact_data["exact"] is True
    # Default includes the descendant's member; --exact does not.
    assert "B" in default_data["entries"]
    assert "B" not in exact_data["entries"]
    assert "A" in exact_data["entries"]


# --- regressions: JabRef's on-disk grouping syntax ---------------------------

# As JabRef 5 writes it: every group quoted a second time at the metadata
# level, so field separators are ``\;`` and only the terminator is bare.
JABREF_ON_DISK = (
    "0 AllEntriesGroup:;\n"
    r"1 StaticGroup:Physics\;0\;1\;0x8a8a8aff\;\;\;;"
    "\n"
    r"2 ExplicitGroup:Optics\;0\;1\;\;Euler1748\;Newton1704\;;"
)


def test_jabref_on_disk_grouping_round_trips_byte_for_byte() -> None:
    nodes = parse_jabref_grouping(JABREF_ON_DISK)

    assert format_jabref_grouping(nodes) == JABREF_ON_DISK


def test_jabref_explicit_group_entries_exclude_the_terminator() -> None:
    nodes = parse_jabref_grouping(JABREF_ON_DISK)

    optics = next(node for node in nodes if node.name == "Optics")
    assert optics.entries == ("Euler1748", "Newton1704")
