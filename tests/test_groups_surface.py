"""The 0.9 ``groups`` surface: one list, verbs without suffixes, deprecated forms."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

LIBRARY = """@book{Newton1704, title = {Opticks}, groups = {Optics}}
@book{Huygens1690, title = {Traite de la lumiere}, groups = {Optics, Waves}}

@comment{jabref-meta: grouping:
0 AllEntriesGroup:;
1 StaticGroup:Optics\\;0\\;1\\;\\;\\;\\;;
}
"""


def _library(tmp_path: Path) -> str:
    path = tmp_path / "refs.bib"
    path.write_text(LIBRARY, encoding="utf-8")
    return str(path)


def _json(args: list[str]) -> dict:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_list_reports_declared_tree_memberships_and_undeclared_groups(tmp_path: Path) -> None:
    data = _json(["groups", "list", _library(tmp_path)])
    assert data["action"] == "groups_list"
    assert [node["name"] for node in data["tree"]] == ["Optics"]
    assert data["groups"] == {"Optics": ["Huygens1690", "Newton1704"], "Waves": ["Huygens1690"]}
    assert data["undeclared"] == ["Waves"]

    human = runner.invoke(app, ["groups", "list", _library(tmp_path)]).output
    assert "Optics (2): Huygens1690, Newton1704" in human
    assert "Not declared in the hierarchy:\n  Waves (1): Huygens1690" in human


@pytest.mark.parametrize(
    ("old", "args", "action", "new"),
    [
        ("tree", [], "groups_tree", "groups list"),
        ("list-entries", ["Optics"], "groups_list_entries", "groups show"),
        ("add-entry", ["Newton1704", "Waves"], "groups_add_entry", "groups assign"),
        ("remove-entry", ["Huygens1690", "Waves"], "groups_remove_entry", "groups unassign"),
        ("add-group", ["Mechanics"], "groups_add_group", "groups add"),
        ("remove-group", ["Optics"], "groups_remove_group", "groups remove"),
        ("rename-group", ["Optics", "Light"], "groups_rename_group", "groups rename"),
        ("move-group", ["Optics", "--parent", ""], "groups_move_group", "groups update --parent"),
        ("update-group", ["Optics", "--color", "8a8a8aff"], "groups_update_group", "groups update"),
    ],
)
def test_old_forms_run_hidden_with_their_old_action(
    tmp_path: Path, old: str, args: list[str], action: str, new: str
) -> None:
    library = _library(tmp_path)
    write = [] if old in {"tree", "list-entries"} else ["--dry-run"]
    data = _json(["groups", old, library, *args, *write])
    assert data["action"] == action
    assert {"type": "deprecated", "old": f"groups {old}", "new": new} == {
        key: data["warnings"][-1][key] for key in ("type", "old", "new")
    }
    assert f"groups {old}" not in runner.invoke(app, ["groups", "--help"]).output


def test_deprecated_batch_operation_names_still_apply_and_warn(tmp_path: Path) -> None:
    library = _library(tmp_path)
    ops = json.dumps([{"op": "groups.add_entry", "key": "Newton1704", "group": "Waves"}])
    data = _json(["batch", library, "--ops", ops, "--dry-run"])
    assert data["operations"][0]["op"] == "groups.add_entry"
    assert data["warnings"] == [
        {
            "type": "deprecated",
            "old": "groups.add_entry",
            "new": "groups.assign",
            "removal": "0.10.0",
            "message": "batch operation groups.add_entry is deprecated and will be removed "
            "in 0.10.0; use groups.assign",
        }
    ]
    assert data["modified_entries"] == 1


def test_update_refuses_a_parent_that_would_make_a_cycle(tmp_path: Path) -> None:
    library = _library(tmp_path)
    assert (
        runner.invoke(app, ["groups", "add", library, "Lenses", "--parent", "Optics"]).exit_code
        == 0
    )
    before = Path(library).read_text(encoding="utf-8")
    result = runner.invoke(
        app, ["groups", "update", library, "Optics", "--parent", "Lenses", "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "InvalidInput"
    assert "circular reference" in json.loads(result.output)["message"]
    assert Path(library).read_text(encoding="utf-8") == before
