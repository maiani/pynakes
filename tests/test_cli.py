"""CLI smoke tests."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import doi as doi_ops
from pynakes.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


class TestUsedCommand:
    def test_report_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())

        result = runner.invoke(app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--json"])
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

    def test_used_falls_back_to_tex_sources_metadata(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{Smith2020,\n  title = {T}\n}\n"
            "@article{Unused2019,\n  title = {U}\n}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")

        # No sources argument: scan the files listed in tex-sources metadata.
        result = runner.invoke(app, ["used", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["report"]["used"] == ["Smith2020"]

    def test_used_without_sources_or_metadata_errors(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(app, ["used", str(bib), "--json"])

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "NoSources"

    def test_inplace_tag_preserves_untouched_entries(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (FIXTURES / "simple.bib").read_text()
        bib.write_text(original)

        runner.invoke(app, ["used", str(bib), str(FIXTURES / "paper.aux"), "--group", "Cited"])
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


class TestFilesCommand:
    def test_check_json_reports_linked_files(self, tmp_path: Path) -> None:
        (tmp_path / "A.pdf").write_text("pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n  title = {T},\n  file = {A:A.pdf:PDF; Missing:missing.pdf:PDF}\n}\n"
        )

        result = runner.invoke(app, ["files", "check", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["checked"] == 2
        assert data["ok"] == 1
        assert data["missing"] == 1
        assert data["issues"][0]["entry_key"] == "A"

    def test_check_uses_root(self, tmp_path: Path) -> None:
        root = tmp_path / "papers"
        root.mkdir()
        (root / "A.pdf").write_text("pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T},\n  file = {A.pdf}\n}\n")

        result = runner.invoke(app, ["files", "check", str(bib), "--root", str(root), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] == 1
        assert data["files"][0]["resolved_path"] == str(root / "A.pdf")

    def test_check_human_lists_issues(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T},\n  file = {missing.pdf}\n}\n")

        result = runner.invoke(app, ["files", "check", str(bib)])

        assert result.exit_code == 0, result.output
        assert "checked 1 linked file" in result.output
        assert "[missing] A[0]: missing.pdf" in result.output


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
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

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
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

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
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["doi", "import", str(bib), "10.5555/provider", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Smith24Practical"
        assert data["key_source"] == "generated"
        assert "@article{Smith24Practical," in bib.read_text()

    def test_import_can_use_provider_key(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

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
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

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

    def test_import_citation_key_conflict(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app,
            ["doi", "import", str(bib), "10.5555/provider", "--key", "Smith2020", "--json"],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "CitationKeyConflict"
        assert data["key"] == "Smith2020"

    def test_import_citation_key_conflict_human(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app, ["doi", "import", str(bib), "10.5555/provider", "--key", "Smith2020"]
        )
        assert result.exit_code == 2, result.output
        assert "CitationKeyConflict" in result.output

    def test_import_malformed_doi_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["doi", "import", str(bib), "not-a-doi", "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "InvalidDOI"

    def test_import_provider_failure_errors(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")

        def _boom(doi: str) -> str:
            raise doi_ops.DOIImportError("resolver offline")

        monkeypatch.setattr(doi_ops, "fetch_bibtex_for_doi", _boom)
        result = runner.invoke(app, ["doi", "import", str(bib), "10.5555/provider", "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "DOIImportError"

    def test_import_duplicate_doi_human_output(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["doi", "import", str(bib), "https://doi.org/10.1234/nature.ml.2020"]
        )
        assert result.exit_code == 2, result.output
        assert "DuplicateDOI" in result.output
        assert "--allow-duplicate" in result.output


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
        result = runner.invoke(app, ["keys", "repair", str(bib), "--dry-run", "--diff", "--json"])
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

    def test_rename_updates_bib_and_tex_dry_run(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\citep[see]{Smith2020, Jones2021}" "\n")
        original_bib = bib.read_text()
        original_tex = tex.read_text()

        result = runner.invoke(
            app,
            [
                "keys",
                "rename",
                str(bib),
                "Smith2020",
                "Smith2020ML",
                str(tex),
                "--dry-run",
                "--diff",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "keys_rename"
        assert data["modified"] is True
        assert data["modified_entries"] == 1
        assert data["source_occurrences"] == 1
        assert "@article{Smith2020ML," in data["diff"]
        assert r"\citep[see]{Smith2020ML, Jones2021}" in data["diff"]
        assert bib.read_text() == original_bib
        assert tex.read_text() == original_tex

    def test_rename_writes_bib_and_tex(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n" r"% \cite{Smith2020}" "\n")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", str(tex)]
        )

        assert result.exit_code == 0, result.output
        assert "@article{Smith2020ML," in bib.read_text()
        assert r"\cite{Smith2020ML}" in tex.read_text()
        assert r"% \cite{Smith2020}" in tex.read_text()

    def test_rename_falls_back_to_tex_sources_metadata(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{Smith2020,\n  title = {T}\n}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n")

        # No sources argument: the library's tex-sources metadata is used.
        result = runner.invoke(app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML"])

        assert result.exit_code == 0, result.output
        assert "@article{Smith2020ML," in bib.read_text()
        assert r"\cite{Smith2020ML}" in tex.read_text()

    def test_rename_without_sources_or_metadata_errors(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{Smith2020,\n  title = {T}\n}\n")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "NoTeXSources"

    def test_repair_warns_about_ambiguous_tex_citations(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{Smith2020,\n  title = {A}\n}\n"
            "@article{Smith2020,\n  title = {B}\n}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["keys", "repair", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["renames"]
        ambiguous = [w for w in data["warnings"] if w["type"] == "ambiguous_citation"]
        assert ambiguous and ambiguous[0]["key"] == "Smith2020"
        # repair does not rewrite the .tex (the citation is ambiguous).
        assert r"\cite{Smith2020}" in (tmp_path / "paper.tex").read_text()

    def test_rename_conflicts_when_target_key_exists(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Jones2021", str(tex), "--json"]
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "CitationKeyConflict"


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
            [
                "fields",
                "append",
                str(bib),
                "keywords",
                "vision",
                "--where",
                'title contains "Computer Vision"',
            ],
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
            app,
            [
                "normalize",
                str(bib),
                "--journal-style",
                "abbreviated",
                "--dry-run",
                "--diff",
                "--json",
            ],
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

    def test_normalize_leaves_journals_untouched_by_default(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n  title = {Paper},\n  journal = {Nature Machine Intelligence}\n}\n"
        )

        result = runner.invoke(app, ["normalize", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["journals"] == 0
        assert "journal = {Nature Machine Intelligence}" in bib.read_text()

    def test_normalize_identifier_case_can_be_disabled(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = "@Article{A,\n  TITLE = {Paper}\n}\n"
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--title-protection",
                "off",
                "--author-style",
                "none",
                "--doi-normalization",
                "off",
                "--identifier-case",
                "off",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["entry_types"] == 0
        assert data["operations"]["field_names"] == 0
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

        result = runner.invoke(app, ["normalize", str(bib), "--journal-style", "short", "--json"])

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
                "--journal-style",
                "abbreviated",
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

    def test_normalize_does_not_write_backup_by_default(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  author = {Smith, Jane & Doe, John},\n  title = {Paper}\n}\n")

        result = runner.invoke(app, ["normalize", str(bib)])

        assert result.exit_code == 0, result.output
        assert not (tmp_path / "refs.bib.bak").exists()

    def test_normalize_backup_flag_writes_bak(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = "@article{A,\n  author = {Smith, Jane & Doe, John},\n  title = {Paper}\n}\n"
        bib.write_text(original)

        result = runner.invoke(app, ["normalize", str(bib), "--backup"])

        assert result.exit_code == 0, result.output
        backup = tmp_path / "refs.bib.bak"
        assert backup.exists()
        assert backup.read_text() == original

    def test_normalize_consolidates_metadata_to_end_by_default(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@Comment{jabref-meta: databaseType:bibtex;}\n"
            "\n"
            "@article{A,\n  author = {Smith, John},\n  title = {T}\n}\n"
        )

        result = runner.invoke(app, ["normalize", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        # Metadata now follows the entry instead of preceding it.
        assert text.index("@article{A,") < text.index("@Comment{jabref-meta")

    def test_normalize_metadata_formatting_off_leaves_position(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (
            "@Comment{jabref-meta: databaseType:bibtex;}\n"
            "\n"
            "@article{A,\n  author = {Smith, John},\n  title = {T}\n}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--metadata-formatting",
                "off",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--journal-style",
                "none",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        assert bib.read_text() == original


class TestConvertCommand:
    def test_convert_dry_run_diff_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "bibtex_classic.bib")
        original = bib.read_text()

        result = runner.invoke(
            app, ["convert", str(bib), "--to", "biblatex", "--dry-run", "--diff", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "convert"
        assert data["modified"] is True
        assert data["operations"]["types_changed"] == 2
        assert "journaltitle = {Nature Machine Intelligence}" in data["diff"]
        assert "@thesis{Green2023," in data["diff"]
        assert bib.read_text() == original  # dry-run writes nothing

    def test_convert_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "bibtex_classic.bib")

        result = runner.invoke(app, ["convert", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "@thesis{Green2023," in text
        assert "institution = {Stanford University}" in text
        assert "date = {2020-03}" in text

    def test_convert_to_bibtex_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "biblatex_sample.bib")

        result = runner.invoke(app, ["convert", str(bib), "--to", "bibtex", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["entries"] >= 1
        text = bib.read_text()
        assert "@phdthesis{FormattedThesis2023," in text
        assert "journal = {Journal of Artificial Intelligence}" in text

    def test_convert_unknown_target_errors_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "bibtex_classic.bib")

        result = runner.invoke(app, ["convert", str(bib), "--to", "endnote", "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidInput"


class TestErrorHandling:
    """The agent contract: expected failures are structured, not tracebacks."""

    def test_missing_file_json_is_structured(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["inspect", str(tmp_path / "nope.bib"), "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)  # must be parseable JSON, not a traceback
        assert data["status"] == "error"
        assert data["error"] == "FileNotFound"

    def test_missing_file_human_is_clean(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["lint", str(tmp_path / "nope.bib")])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "FileNotFound" in result.output

    def test_malformed_file_reports_parse_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.bib"
        bad.write_text("@article{Bad,\n  title = {Unclosed\n")
        result = runner.invoke(app, ["inspect", str(bad), "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["error"] == "ParseError"

    def test_invalid_query_is_structured(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "clear", str(bib), "doi", "--where", "garbage <> nonsense", "--json"]
        )
        assert result.exit_code == 1
        assert json.loads(result.output)["status"] == "error"

    def test_unknown_key_human_mode_not_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["groups", "add-entry", str(bib), "Nope", "Fav"])
        assert result.exit_code == 1
        # Human mode must not dump JSON.
        assert not result.output.strip().startswith("{")
        assert "KeyNotFound" in result.output


class TestCapabilities:
    def test_capabilities_json(self) -> None:
        result = runner.invoke(app, ["capabilities", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["tool"] == "pynakes"
        assert data["exit_codes"]["2"].startswith("conflict")
        # Every advertised command is actually registered on the app.
        registered = {
            c.name or (c.callback.__name__ if c.callback else "") for c in app.registered_commands
        }
        groups = {g.name for g in app.registered_groups}
        for name in data["commands"]:
            assert name in registered or name in groups, name


class TestEnvelopeConsistency:
    """Every modifying command emits the same JSON envelope keys."""

    ENVELOPE = {"status", "action", "file", "dry_run", "modified", "modified_entries", "warnings"}

    def _invoke(self, tmp_path, args, fixture="simple.bib"):
        bib = _copy(tmp_path, fixture)
        return runner.invoke(app, [args[0], str(bib), *args[1:], "--dry-run", "--json"])

    def test_groups_add_entry_envelope(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        r = runner.invoke(
            app, ["groups", "add-entry", str(bib), "Smith2020", "X", "--dry-run", "--json"]
        )
        assert self.ENVELOPE <= set(json.loads(r.output))

    def test_keys_repair_envelope(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        r = runner.invoke(app, ["keys", "repair", str(bib), "--dry-run", "--json"])
        assert self.ENVELOPE <= set(json.loads(r.output))

    def test_fields_rename_envelope(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        r = runner.invoke(
            app, ["fields", "rename", str(bib), "journal", "journaltitle", "--dry-run", "--json"]
        )
        assert self.ENVELOPE <= set(json.loads(r.output))

    def test_normalize_envelope(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        r = runner.invoke(app, ["normalize", str(bib), "--dry-run", "--json"])
        assert self.ENVELOPE <= set(json.loads(r.output))

    def test_used_envelope_uses_file_key(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        r = runner.invoke(
            app,
            ["used", str(bib), str(FIXTURES / "paper.aux"), "--group", "X", "--dry-run", "--json"],
        )
        data = json.loads(r.output)
        assert self.ENVELOPE <= set(data)
        assert "input_path" not in data  # standardized to "file"


class TestJournalsCommand:
    def test_abbreviate_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["journals", "abbreviate", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "journals_abbreviate"
        assert data["modified_entries"] == 1
        assert "journal = {Nat. Mach. Intell.}" in bib.read_text()

    def test_expand_reverses_exact_mapping(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {X},\n  journal = {Phys. Rev. Lett.}\n}\n")
        result = runner.invoke(app, ["journals", "expand", str(bib)])
        assert result.exit_code == 0, result.output
        assert "journal = {Physical Review Letters}" in bib.read_text()

    def test_abbreviate_then_expand_round_trips(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        runner.invoke(app, ["journals", "abbreviate", str(bib)])
        runner.invoke(app, ["journals", "expand", str(bib)])
        assert "journal = {Nature Machine Intelligence}" in bib.read_text()

    def test_check_reports_status(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n  title = {X},\n  journal = {Nature Machine Intelligence}\n}\n"
            "@article{B,\n  title = {Y},\n  journal = {Some Obscure Local Gazette}\n}\n"
        )
        result = runner.invoke(app, ["journals", "check", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        statuses = {j["journal"]: j["status"] for j in data["journals"]}
        assert statuses["Nature Machine Intelligence"] == "builtin_exact"
        assert statuses["Some Obscure Local Gazette"] == "unknown"
        assert data["unknown"] == ["Some Obscure Local Gazette"]

    def test_check_does_not_modify(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        runner.invoke(app, ["journals", "check", str(bib)])
        assert bib.read_text() == original

    def test_abbreviate_warns_unknown(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {X},\n  journal = {Zzz Qqq Www}\n}\n")
        result = runner.invoke(app, ["journals", "abbreviate", str(bib), "--json"])
        data = json.loads(result.output)
        assert data["unknown"] == ["Zzz Qqq Www"]
        assert any(w["type"] == "unknown_journal" for w in data["warnings"])


# Each case: (command prefix, positional suffix after <file>, fixture). The
# runner inserts the bib path right after the prefix. Every case is chosen to
# actually modify its fixture, so --diff must produce a diff.
_MODIFYING_CASES = [
    (["groups", "add-entry"], ["Smith2020", "Fav"], "simple.bib"),
    (["keys", "repair"], [], "duplicate_entries.bib"),
    (["keys", "generate"], [], "simple.bib"),
    (["fields", "rename"], ["journal", "journaltitle"], "simple.bib"),
    (["fields", "move"], ["journal", "journaltitle"], "simple.bib"),
    (["fields", "append"], ["keywords", "test"], "simple.bib"),
    (["fields", "clear"], ["doi"], "simple.bib"),
    (["normalize"], [], "simple.bib"),
    (["convert"], ["--to", "biblatex"], "bibtex_classic.bib"),
    (["convert"], ["--to", "bibtex"], "biblatex_sample.bib"),
    (["journals", "abbreviate"], [], "simple.bib"),
]


@pytest.mark.parametrize("prefix,suffix,fixture", _MODIFYING_CASES)
class TestDryRunDiffJsonIntegration:
    """Every modifying command honors --dry-run, --diff, and --json together."""

    ENVELOPE = {"status", "action", "file", "dry_run", "modified", "modified_entries", "warnings"}

    def _run(self, tmp_path, prefix, suffix, fixture, flags):
        bib = _copy(tmp_path, fixture)
        before = bib.read_text()
        args = [*prefix, str(bib), *suffix, *flags]
        return runner.invoke(app, args), bib, before

    def test_dry_run_diff_json(self, tmp_path, prefix, suffix, fixture) -> None:
        result, bib, before = self._run(
            tmp_path, prefix, suffix, fixture, ["--dry-run", "--diff", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert self.ENVELOPE <= set(data)
        assert data["dry_run"] is True
        assert data["modified"] is True
        assert data["diff"]  # --diff includes a non-empty unified diff
        assert bib.read_text() == before  # dry-run never writes

    def test_actual_run_matches_dry_run_diff(self, tmp_path, prefix, suffix, fixture) -> None:
        # The diff previewed by --dry-run must equal what a real run produces.
        preview, bib, before = self._run(
            tmp_path, prefix, suffix, fixture, ["--dry-run", "--diff", "--json"]
        )
        preview_diff = json.loads(preview.output)["diff"]

        result, bib2, _ = self._run(tmp_path, prefix, suffix, fixture, ["--diff", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["diff"] == preview_diff
        assert bib2.read_text() != before  # real run wrote the change
