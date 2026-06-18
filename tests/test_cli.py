"""CLI smoke tests."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes import doi as doi_ops
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


class TestDOICommand:
    provider_bibtex = """@article{provider-key,
  author = {Jane Smith and John Doe},
  title = {A Practical Test of DOI Import},
  journal = {Journal of Tests},
  year = {2024},
  doi = {10.5555/provider}
}
"""

    def test_import_dry_run_diff_does_not_write(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        monkeypatch.setattr(
            doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex
        )

        result = runner.invoke(
            app,
            ["doi", "import", str(bib), "10.5555/provider", "--dry-run", "--diff", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Smith2024Practical"
        assert "@article{Smith2024Practical," in data["diff"]
        assert bib.read_text() == original

    def test_import_writes_entry(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(
            doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex
        )

        result = runner.invoke(app, ["doi", "import", str(bib), "10.5555/provider"])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "@article{Smith2024Practical," in text
        assert "doi = {10.5555/provider}" in text

    def test_import_uses_jabref_key_pattern_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
        )
        monkeypatch.setattr(
            doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex
        )

        result = runner.invoke(
            app, ["doi", "import", str(bib), "10.5555/provider", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Smith24Practical"
        assert data["key_source"] == "generated"
        assert "@article{Smith24Practical," in bib.read_text()

    def test_import_can_use_provider_key(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(
            doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex
        )

        result = runner.invoke(
            app,
            ["doi", "import", str(bib), "10.5555/provider", "--key-source", "provider", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "provider-key"
        assert data["key_source"] == "provider"

    def test_import_explicit_key_wins(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(
            doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex
        )

        result = runner.invoke(
            app,
            [
                "doi",
                "import",
                str(bib),
                "10.5555/provider",
                "--key-source",
                "provider",
                "--key",
                "Manual2024",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Manual2024"
        assert data["key_source"] == "user"

    def test_import_invalid_key_source_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            ["doi", "import", str(bib), "10.5555/provider", "--key-source", "garbage", "--json"],
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidKeySource"

    def test_import_duplicate_doi_conflicts(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            [
                "doi",
                "import",
                str(bib),
                "https://doi.org/10.1234/nature.ml.2020",
                "--json",
            ],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["existing_keys"] == ["Smith2020"]


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

    def test_protect_title_dry_run_diff(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = "@article{A,\n  title = {DNA repair with eBay},\n  year = {2024}\n}\n"
        bib.write_text(original)

        result = runner.invoke(
            app,
            ["fields", "protect-title", str(bib), "--dry-run", "--diff", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified"] is True
        assert "title = {{DNA} repair with {eBay}}" in data["diff"]
        assert bib.read_text() == original

    def test_protect_title_writes_with_explicit_term(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@inproceedings{A,\n"
            "  title = {Paper},\n"
            "  booktitle = {Proceedings of JabRefConf},\n"
            "  year = {2024}\n"
            "}\n"
        )

        result = runner.invoke(
            app,
            [
                "fields",
                "protect-title",
                str(bib),
                "--field",
                "booktitle",
                "--term",
                "Proceedings",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "booktitle = {{Proceedings} of {JabRefConf}}" in bib.read_text()

    def test_invalid_query_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "clear", str(bib), "doi", "--where", "garbage <> nonsense"]
        )
        assert result.exit_code == 1


class TestNormalizeCommand:
    def test_normalize_dry_run_diff_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (
            "@article{A,\n"
            "  author = {Smith, Jane & Doe, John},\n"
            "  title = {DNA repair with eBay},\n"
            "  journal = {Nature Machine Intelligence},\n"
            "  doi = {https://doi.org/10.5555/ABC}\n"
            "}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app, ["normalize", str(bib), "--dry-run", "--diff", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified"] is True
        assert data["operations"]["title_fields"] == {"title": 1}
        assert data["operations"]["authors"] == 1
        assert data["operations"]["journals"] == 1
        assert data["operations"]["dois"] == 1
        assert "title = {{DNA} repair with {eBay}}" in data["diff"]
        assert "journal = {Nat. Mach. Intell.}" in data["diff"]
        assert bib.read_text() == original

    def test_normalize_writes_with_overrides(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n"
            "  author = {Smith, Jane & Doe, John},\n"
            "  title = {DNA repair},\n"
            "  journal = {Nature Machine Intelligence}\n"
            "}\n"
        )

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--title-protection",
                "off",
                "--journal-style",
                "none",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "author = {Smith, Jane and Doe, John}" in text
        assert "title = {DNA repair}" in text
        assert "journal = {Nature Machine Intelligence}" in text

    def test_normalize_invalid_option_errors_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["normalize", str(bib), "--journal-style", "short", "--json"]
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidNormalizeOption"

    def test_normalize_uses_journal_table(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        table = tmp_path / "journals.csv"
        bib.write_text(
            "@article{A,\n"
            "  title = {Paper},\n"
            "  journal = {Publisher Variant Title},\n"
            "  issn = {1234-567X}\n"
            "}\n"
        )
        table.write_text("title,abbreviation,issn\nCanonical Journal,Can. J.,1234-567X\n")

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--journal-table",
                str(table),
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["journals"] == 1
        assert "journal = {Can. J.}" in bib.read_text()
