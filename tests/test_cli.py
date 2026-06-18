"""CLI smoke tests."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


class TestUsedCommand:
    def test_report_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())

        result = runner.invoke(
            app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data["report"]["used"]) == {"Smith2020", "Brown2022"}
        assert "Missing2099" in data["report"]["missing"]

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (FIXTURES / "simple.bib").read_text()
        bib.write_text(original)

        result = runner.invoke(
            app,
            ["used", str(bib), str(FIXTURES / "paper.aux"), "--group", "Used", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert bib.read_text() == original  # unchanged
        assert "Would tag" in result.output

    def test_group_tag_writes(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())

        result = runner.invoke(
            app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--group", "Cited"]
        )
        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "groups = {Cited}" in text
        # Only used entries are tagged.
        assert text.count("groups = {Cited}") == 2

    def test_inplace_tag_preserves_untouched_entries(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (FIXTURES / "simple.bib").read_text()
        bib.write_text(original)

        runner.invoke(
            app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--group", "Cited"]
        )
        new = bib.read_text()
        # Exactly the two used entries gained a group line; no entry dropped.
        assert new.count("groups = {Cited}") == 2
        for key in ["Smith2020", "Jones2021", "Brown2022", "Green2023", "White2024"]:
            assert key in new
        # An uncited entry is byte-for-byte unchanged.
        assert "@phdthesis{Green2023,\n  author = {Michael Green}," in new
        # The blank line between entries is preserved (no whitespace churn).
        assert "}\n\n@book{Jones2021," in new

    def test_export_subset(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())
        out = tmp_path / "cited.bib"

        result = runner.invoke(
            app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--out", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        exported = out.read_text()
        assert "Smith2020" in exported
        assert "Brown2022" in exported
        assert "Green2023" not in exported  # not cited


def _copy(tmp_path: Path, name: str) -> Path:
    dst = tmp_path / "refs.bib"
    dst.write_text((FIXTURES / name).read_text())
    return dst


class TestInspectAndLint:
    def test_inspect_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["inspect", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["entry_count"] == 5
        assert {e["key"] for e in data["entries"]} >= {"Smith2020", "Jones2021"}

    def test_lint_json_reports_duplicates(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        result = runner.invoke(app, ["lint", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["errors"] >= 1
        assert any(i["type"] == "duplicate_key" for i in data["issues"])


class TestGroupsCommand:
    def test_list_groups(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "jabref_groups.bib")
        result = runner.invoke(app, ["groups", "list", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        groups = json.loads(result.output)["groups"]
        assert "Machine Learning" in groups

    def test_add_entry_dry_run_does_not_write(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        result = runner.invoke(
            app, ["groups", "add-entry", str(bib), "Smith2020", "Fav", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert bib.read_text() == original

    def test_add_entry_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["groups", "add-entry", str(bib), "Smith2020", "Fav"])
        assert result.exit_code == 0, result.output
        assert "groups = {Fav}" in bib.read_text()

    def test_add_entry_unknown_key_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["groups", "add-entry", str(bib), "Nope", "Fav"])
        assert result.exit_code == 1


class TestKeysCommand:
    def test_check_reports_duplicates(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        result = runner.invoke(app, ["keys", "check", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["has_duplicates"] is True

    def test_repair_dry_run_diff(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        original = bib.read_text()
        result = runner.invoke(
            app, ["keys", "repair", str(bib), "--dry-run", "--diff", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["renames"]
        assert "diff" in data
        assert bib.read_text() == original  # dry-run wrote nothing

    def test_repair_writes_unique_keys(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        result = runner.invoke(app, ["keys", "repair", str(bib)])
        assert result.exit_code == 0, result.output
        from pynakes.bibtex_parser import parse_bib

        assert parse_bib(bib.read_text()).entries.duplicate_keys() == {}


class TestFieldsCommand:
    def test_rename_with_diff(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "rename", str(bib), "journal", "journaltitle", "--diff", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified"] is True
        assert "journaltitle = {Nature Machine Intelligence}" in bib.read_text()

    def test_append_with_where_filter(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            ["fields", "append", str(bib), "keywords", "vision",
             "--where", 'title contains "Computer Vision"'],
        )
        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "keywords = {vision}" in text
        assert text.count("keywords = {vision}") == 1

    def test_clear_field(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["fields", "clear", str(bib), "doi"])
        assert result.exit_code == 0, result.output
        assert "doi =" not in bib.read_text()

    def test_invalid_query_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "clear", str(bib), "doi", "--where", "garbage <> nonsense"]
        )
        assert result.exit_code == 1
