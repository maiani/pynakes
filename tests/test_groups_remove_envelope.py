"""``groups remove-group`` names every node it removes in its JSON envelope."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.group_tree import add_node
from pynakes.model import BibFile


def _hierarchy(tmp_path: Path) -> Path:
    lib = BibFile()
    lib.pynakes_metadata_blocks = []
    add_node(lib, "Physics")
    add_node(lib, "Optics", parent="Physics")
    add_node(lib, "Lenses", parent="Optics")
    add_node(lib, "Mechanics")
    bib = tmp_path / "refs.bib"
    bib.write_text(write_bib(lib))
    return bib


def test_remove_group_names_the_group_and_its_descendants(tmp_path: Path) -> None:
    # A caller confirming a removal must be able to say which subgroups go with
    # the group without walking the tree itself.
    bib = _hierarchy(tmp_path)
    original = bib.read_text()

    result = CliRunner().invoke(
        app, ["groups", "remove-group", str(bib), "Optics", "--dry-run", "--json"]
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["removed_count"] == 2
    assert envelope["removed_groups"] == ["Optics", "Lenses"]
    assert bib.read_text() == original


def test_remove_group_without_descendants_names_only_itself(tmp_path: Path) -> None:
    bib = _hierarchy(tmp_path)

    result = CliRunner().invoke(app, ["groups", "remove-group", str(bib), "Mechanics", "--json"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["removed_groups"] == ["Mechanics"]
    assert "Mechanics" not in bib.read_text()
