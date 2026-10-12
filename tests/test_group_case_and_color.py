"""Group names that differ only in case, and group colors JabRef can read."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.group_tree import add_node, check_group_color, list_tree, rename_node
from pynakes.model import BibFile

runner = CliRunner()

NEWTON = "@book{Newton1704,\n  title = {Opticks},\n  groups = {Optics}\n}\n"
YOUNG = "@article{Young1804,\n  title = {On the Theory of Light},\n  groups = {optics}\n}\n"


def _library(tmp_path: Path, *entries: str) -> Path:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Physics")
    add_node(lib, "Optics", parent="Physics")
    add_node(lib, "Lenses", parent="Optics")
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib) + "\n" + "\n".join(entries or (NEWTON,)))
    return bib


def _invoke(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.output)


# --- case-only rename ---------------------------------------------------------


def test_case_only_rename_renames_the_node_and_its_children(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, envelope = _invoke("groups", "rename-group", str(bib), "Optics", "OPTICS")

    assert code == 0, envelope
    assert envelope["status"] == "success"
    tree = {node["name"]: node["parent"] for node in _invoke("groups", "tree", str(bib))[1]["tree"]}
    assert tree == {"Physics": "", "OPTICS": "Physics", "Lenses": "OPTICS"}


def test_case_only_rename_with_members_moves_the_entries(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, envelope = _invoke("groups", "rename-group", str(bib), "Optics", "OPTICS", "--members")

    assert code == 0, envelope
    assert envelope["members_renamed"] == ["Newton1704"]
    assert "groups = {OPTICS}" in bib.read_text()


def test_rename_onto_another_node_differing_in_case_is_a_conflict(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, envelope = _invoke("groups", "rename-group", str(bib), "Lenses", "optics")

    assert code == 2
    assert envelope["status"] == "conflict"
    assert envelope["error"] == "GroupConflict"


def test_add_group_differing_from_a_node_only_in_case_is_a_conflict(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, envelope = _invoke("groups", "add-group", str(bib), "OPTICS")

    assert code == 2
    assert envelope["error"] == "GroupConflict"


def test_rename_node_prefers_the_exact_spelling(tmp_path: Path) -> None:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Optics")
    tree = list_tree(lib)
    assert tree is not None
    # A second node differing only in case can arrive from a hand-edited file.
    tree.append(type(tree[0])(name="optics"))
    from pynakes.group_tree import _write_tree

    _write_tree(lib, tree)

    assert not rename_node(lib, "optics", "Optics")
    assert rename_node(lib, "optics", "Lowercase")
    assert [node.name for node in list_tree(lib) or []] == ["Optics", "Lowercase"]


# --- membership spelled differently from the node ------------------------------


def test_membership_differing_in_case_is_its_own_group(tmp_path: Path) -> None:
    bib = _library(tmp_path, NEWTON, YOUNG)

    _, listed = _invoke("groups", "list", str(bib))
    _, entries = _invoke("groups", "list-entries", str(bib), "optics")

    assert listed["groups"]["Optics"] == ["Newton1704"]
    assert listed["groups"]["optics"] == ["Young1804"]
    assert entries["entries"] == ["Young1804"]


def test_membership_differing_in_case_can_be_removed(tmp_path: Path) -> None:
    bib = _library(tmp_path, NEWTON, YOUNG)

    code, envelope = _invoke("groups", "remove-entry", str(bib), "Young1804", "optics")

    assert code == 0, envelope
    assert envelope["modified_entries"] == 1
    assert "groups = {optics}" not in bib.read_text()


def test_list_entries_by_another_case_includes_descendants(tmp_path: Path) -> None:
    lenses = "@book{Kepler1611,\n  title = {Dioptrice},\n  groups = {Lenses}\n}\n"
    bib = _library(tmp_path, NEWTON, lenses)

    _, envelope = _invoke("groups", "list-entries", str(bib), "OPTICS")

    assert envelope["entries"] == ["Kepler1611", "Newton1704"]


def test_list_entries_of_a_flat_group_beside_a_tree(tmp_path: Path) -> None:
    flat = "@book{Hooke1665,\n  title = {Micrographia},\n  groups = {Microscopy}\n}\n"
    bib = _library(tmp_path, NEWTON, flat)

    _, envelope = _invoke("groups", "list-entries", str(bib), "Microscopy")

    assert envelope["entries"] == ["Hooke1665"]


# --- colors -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "color", ["", "8a8a8aff", "0x8a8a8aff", "0X8A8A8A", "#8a8a8a", "#fff", "#ffff", "abc"]
)
def test_hex_colors_are_accepted(color: str) -> None:
    check_group_color(color)


@pytest.mark.parametrize("color", ["zz", "red", "#12345", "0x", "8a8a8a|ff", "#8a8a8aff00", " fff"])
def test_other_colors_are_refused(color: str) -> None:
    with pytest.raises(ValueError, match="not a hex color"):
        check_group_color(color)


@pytest.mark.parametrize("command", ["add-group", "update-group"])
def test_cli_refuses_an_invalid_color_without_writing(tmp_path: Path, command: str) -> None:
    bib = _library(tmp_path)
    before = bib.read_text()
    name = "Mechanics" if command == "add-group" else "Optics"

    code, envelope = _invoke("groups", command, str(bib), name, "--color", "zz")

    assert code == 1
    assert envelope["status"] == "error"
    assert envelope["error"] == "InvalidInput"
    assert bib.read_text() == before


def test_cli_accepts_jabref_color_spelling(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, envelope = _invoke("groups", "update-group", str(bib), "Optics", "--color", "0x8a8a8aff")

    assert code == 0, envelope
    tree = _invoke("groups", "tree", str(bib))[1]["tree"]
    assert next(node for node in tree if node["name"] == "Optics")["color"] == "0x8a8a8aff"
