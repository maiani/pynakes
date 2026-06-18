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
