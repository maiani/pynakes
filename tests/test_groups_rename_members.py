"""``groups rename-group --members`` carries a group's members along with its name."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.group_tree import add_node, list_tree
from pynakes.groups import entry_groups, rename_group_memberships
from pynakes.model import BibFile

runner = CliRunner()

NEWTON = "@book{Newton1704,\n  title = {Opticks},\n  groups = {Optics}\n}\n"
HUYGENS = (
    "@book{Huygens1690,\n  title = {Traité de la lumière},\n  groups = {Optics Lab; Mechanics}\n}\n"
)
YOUNG = (
    "@article{Young1804,\n  title = {On the Theory of Light},\n  groups = {Mechanics;Optics}\n}\n"
)
GALILEO = "@book{Galileo1638,\n  title = {Two New Sciences}\n}\n"


def _library(tmp_path: Path, *entries: str) -> Path:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Physics")
    add_node(lib, "Optics", parent="Physics")
    add_node(lib, "Lenses", parent="Optics")
    add_node(lib, "Mechanics")
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib) + "\n" + "\n".join(entries or (NEWTON, HUYGENS, YOUNG, GALILEO)))
    return bib


def _rename(bib: Path, *extra: str):
    result = runner.invoke(
        app, ["groups", "rename-group", str(bib), "Optics", "Light", *extra, "--json"]
    )
    return result, json.loads(result.output)


def test_members_moves_entries_with_the_group(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    result, envelope = _rename(bib, "--members")

    assert result.exit_code == 0, result.output
    assert envelope["status"] == "success"
    assert envelope["action"] == "groups_rename_group"
    assert envelope["members"] is True
    assert envelope["members_renamed"] == ["Newton1704", "Young1804"]
    assert envelope["modified_entries"] == 2
    text = bib.read_text()
    assert "groups = {Light}" in text
    # The separator as written is kept: only the name inside it changes.
    assert "groups = {Mechanics;Light}" in text
    tree = {node.name: node.parent for node in list_tree(Bibliography.open(bib).lib) or []}
    assert tree["Light"] == "Physics"
    assert tree["Lenses"] == "Light"
    assert "Optics" not in tree


def test_exact_name_match_and_untouched_entries_stay_byte_identical(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _rename(bib, "--members")

    text = bib.read_text()
    # "Optics Lab" is a different group; Galileo has no groups at all.
    assert HUYGENS in text
    assert GALILEO in text


def test_without_members_entries_keep_their_membership(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    result, envelope = _rename(bib)

    assert result.exit_code == 0, result.output
    assert envelope["members"] is False
    assert envelope["members_renamed"] == []
    assert envelope["modified_entries"] == 0
    text = bib.read_text()
    assert NEWTON in text and YOUNG in text


def test_dry_run_diff_shows_only_the_changed_lines(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    original = bib.read_text()

    result = runner.invoke(
        app,
        ["groups", "rename-group", str(bib), "Optics", "Light", "--members", "--dry-run"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert bib.read_text() == original

    result, envelope = _rename(bib, "--members", "--dry-run", "--diff")
    assert envelope["dry_run"] is True
    assert envelope["members_renamed"] == ["Newton1704", "Young1804"]
    changed = [
        line
        for line in envelope["diff"].splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    assert "-  groups = {Optics}" in changed
    assert "+  groups = {Light}" in changed
    assert "-  groups = {Mechanics;Optics}" in changed
    assert "+  groups = {Mechanics;Light}" in changed
    # Everything else that changed is the hierarchy naming the group.
    assert all("Optics" in line or "Light" in line for line in changed)
    assert not any("Optics Lab" in line for line in changed)
    assert bib.read_text() == original


def test_an_entry_naming_the_group_twice_names_the_new_one_once(tmp_path: Path) -> None:
    twice = (
        "@book{Kepler1604,\n  title = {Astronomiae Pars Optica},\n  groups = {Optics; Optics}\n}\n"
    )
    bib = _library(tmp_path, twice)

    result, envelope = _rename(bib, "--members")

    assert result.exit_code == 0, result.output
    assert envelope["members_renamed"] == ["Kepler1604"]
    assert "groups = {Light}" in bib.read_text()


def test_duplicated_keys_are_all_moved_and_named_once(tmp_path: Path) -> None:
    bib = _library(tmp_path, NEWTON, NEWTON.replace("Opticks", "Opticks, 2nd ed."))

    result, envelope = _rename(bib, "--members")

    assert result.exit_code == 0, result.output
    assert envelope["members_renamed"] == ["Newton1704"]
    assert bib.read_text().count("groups = {Light}") == 2


def test_expect_sha256_guards_the_write(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _, preview = _rename(bib, "--members", "--dry-run")
    original = bib.read_text()

    result, stale = _rename(bib, "--members", "--expect-sha256", "0" * 64)
    assert result.exit_code == 2
    assert stale["error"] == "ExternalModification"
    assert bib.read_text() == original

    result, written = _rename(bib, "--members", "--expect-sha256", preview["source_sha256"])
    assert result.exit_code == 0, result.output
    assert written["members_renamed"] == ["Newton1704", "Young1804"]


def test_a_taken_name_is_a_conflict_and_writes_nothing(tmp_path: Path) -> None:
    # "Optics Lab" exists only as a membership, never as a tree node.
    bib = _library(tmp_path)
    original = bib.read_text()

    for new in ("Mechanics", "Optics Lab"):
        result = runner.invoke(
            app, ["groups", "rename-group", str(bib), "Optics", new, "--members", "--json"]
        )
        assert result.exit_code == 2, result.output
        assert json.loads(result.output)["error"] == "GroupConflict"
        assert bib.read_text() == original


def test_remove_group_still_keeps_memberships(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    result = runner.invoke(app, ["groups", "remove-group", str(bib), "Optics", "--json"])

    assert result.exit_code == 0, result.output
    assert NEWTON in bib.read_text()


def test_python_api_never_duplicates_the_new_name() -> None:
    # Through the CLI a NEW that entries already name is a GroupConflict; the
    # library function still has to leave one membership, not two.
    coll = Bibliography.from_text(
        "@book{Hooke1665,\n  title = {Micrographia},\n  groups = {Light; Optics;Lenses; Optics}\n}\n"
        "@book{Boyle1664,\n  title = {Experiments Touching Colours},\n  groups = {Lenses}\n}\n"
    )

    changed = coll.rename_group_members("Optics", "Light")

    assert changed == ["Hooke1665"]
    hooke, boyle = coll.lib.entries.values()
    assert entry_groups(hooke) == ["Light", "Lenses"]
    assert "groups = {Light;Lenses}" in coll.preview()
    assert entry_groups(boyle) == ["Lenses"]
    assert coll.changed_entries_count() == 1


def test_rename_group_memberships_returns_nothing_without_members() -> None:
    lib = BibFile()
    assert rename_group_memberships(lib, "Optics", "Light") == []
