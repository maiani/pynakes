"""CLI smoke tests."""

import json
import tarfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import __version__
from pynakes import importer as importer_ops
from pynakes.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


class TestVersion:
    @pytest.mark.parametrize("flag", ["--version", "-V"])
    def test_prints_installed_package_version(self, flag: str) -> None:
        result = runner.invoke(app, [flag])

        assert result.exit_code == 0, result.output
        assert result.output == f"{__version__}\n"


class TestChangePlanEnvelope:
    def test_modifying_command_json_includes_structured_plan(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {t},\n  doi = {10.1/x}\n}\n")
        result = runner.invoke(
            app, ["fields", "append", str(bib), "keywords", "ml", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        plan = json.loads(result.output)["plan"]
        assert plan["summary"]["modified"] == 1
        assert plan["entries"][0]["key"] == "A"
        assert plan["entries"][0]["fields"]["keywords"] == {"old": None, "new": "ml"}


class TestUsedCommand:
    def test_discovers_lone_bib_file_with_source_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{Smith2020,\n  title = {T}\n}\n")
        sources = tmp_path / "sources"
        sources.mkdir()
        (sources / "paper.tex").write_text(r"\cite{Smith2020}" "\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["used", "sources", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["report"]["used"] == ["Smith2020"]

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
    def test_inspect_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["inspect", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == "refs.bib"

    def test_nested_command_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            ["fields", "append", "keywords", "ml", "--dry-run", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["modified_entries"] == 1

    def test_multiple_bib_files_are_not_auto_selected(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "first.bib").write_text("@article{A, title = {A}}\n")
        (tmp_path / "second.bib").write_text("@article{B, title = {B}}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["inspect"])

        assert result.exit_code == 1

    def test_inspect_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["inspect", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["entry_count"] == 5
        assert {e["key"] for e in data["entries"]} >= {"Smith2020", "Jones2021"}
        assert "issues" not in data

    def test_inspect_json_includes_declarations_and_resolved_fields(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@string{j = {Jrnl}}\n\n"
            "@proceedings{p, title = {Proc}, year = {2020}}\n\n"
            "@inproceedings{c, crossref = {p}, title = {Paper}, author = {A, B}}\n"
        )
        result = runner.invoke(app, ["inspect", str(bib), "--resolved", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["strings"] == {"j": "Jrnl"}
        assert "preamble" in data and "comments" in data
        child = next(e for e in data["entries"] if e["key"] == "c")
        # raw fields lack booktitle; resolved view inherits it from the parent.
        assert "booktitle" not in child["fields"]
        assert child["resolved_fields"]["booktitle"] == "Proc"

    def test_inspect_json_annotates_pinax_materials(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "A_preprint.pdf").write_bytes(b"pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n"
            "  title = {T},\n"
            "  eprinttype = {arxiv},\n"
            "  eprint = {2101.00001}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "files-dir:\n"
            "}\n"
        )

        result = runner.invoke(app, ["inspect", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        entry = data["entries"][0]
        assert entry["preprint_pdf"] == str(files / "A_preprint.pdf")
        assert entry["canonical_pdf"] == str(files / "A_preprint.pdf")
        assert entry["refetchable"] is True

    def test_inspect_human_does_not_run_lint(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(app, ["inspect", str(bib)])

        assert result.exit_code == 0, result.output
        assert "@article{A}" in result.output
        assert "Issues:" not in result.output

    def test_lint_json_reports_duplicates(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        result = runner.invoke(app, ["lint", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["errors"] >= 1
        assert any(i["type"] == "duplicate_key" for i in data["issues"])

    def test_lint_json_reports_undefined_string_references(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n"
            "  author = {Jane Doe},\n"
            "  title = {A Study},\n"
            "  journal = {Journal},\n"
            "  year = {2024},\n"
            "  month = june,\n"
            "  doi = {10.1234/abc}\n"
            "}\n"
        )

        result = runner.invoke(app, ["lint", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["errors"] == 1
        assert data["issues"][-1] == {
            "type": "undefined_string_reference",
            "severity": "error",
            "message": "Entry 'A' field 'month' references undefined BibTeX string name 'june'",
            "key": "A",
            "field": "month",
        }

    def test_lint_strict_fails_metadata_profile_deviations(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][year];}\n\n"
            "@article{WrongKey,\n"
            "  author = {Jane Smith},\n"
            "  title = {A Study},\n"
            "  journal = {Nature},\n"
            "  year = {2024},\n"
            "  doi = {10.1234/example}\n"
            "}\n"
        )

        advisory = runner.invoke(app, ["lint", str(bib), "--json"])
        assert advisory.exit_code == 0, advisory.output
        assert any(
            issue["type"] == "citation_key_pattern_mismatch"
            for issue in json.loads(advisory.output)["issues"]
        )

        strict = runner.invoke(app, ["lint", str(bib), "--strict", "--json"])
        assert strict.exit_code == 1, strict.output


class TestSearchCommand:
    def test_search_json_reports_matches(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  author = {Avery Example},\n"
            "  title = {Neural Widgets for Small Libraries},\n"
            "  year = {2024}\n"
            "}\n\n"
            "@book{Beta2023,\n"
            "  author = {Blair Example},\n"
            "  title = {Manual Widgets},\n"
            "  year = {2023}\n"
            "}\n"
        )

        result = runner.invoke(app, ["search", "neural widgets", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["action"] == "search"
        assert data["count"] == 1
        assert data["matches"][0]["key"] == "Alpha2024"
        assert data["matches"][0]["matched_fields"] == ["title"]

    def test_search_supports_field_terms_and_where_filter(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Graph Widgets},\n"
            "  year = {2024}\n"
            "}\n\n"
            "@book{Beta2024,\n"
            "  title = {Graph Widgets},\n"
            "  year = {2024}\n"
            "}\n"
        )

        result = runner.invoke(
            app,
            ["search", "title:graph", str(bib), "--where", "type = article", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [match["key"] for match in data["matches"]] == ["Alpha2024"]

    def test_search_human_output_is_clean(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", "widget", str(bib)])

        assert result.exit_code == 0, result.output
        assert "1 matching entry" in result.output
        assert "@misc{Alpha}" in result.output

    def test_search_invalid_query_is_structured(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", '"unterminated', str(bib), "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["error"] == "InvalidInput"


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

    def test_check_json_reports_pinax_orphans_and_drift(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "Ghost.pdf").write_bytes(b"pdf")
        (files / ".pinax").mkdir()
        (files / ".pinax" / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": {
                        "A": {
                            "preprint_pdf": {
                                "source": "manual",
                                "added_date": "2026-06-27",
                                "sha256": "0" * 64,
                                "refetchable": False,
                            }
                        }
                    },
                }
            )
        )
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\nfiles-dir:\n}\n")

        result = runner.invoke(app, ["files", "check", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        pinax = json.loads(result.output)["pinax"]
        assert pinax["orphans"][0]["key"] == "Ghost"
        assert pinax["drift"][0] == {
            "key": "A",
            "kind": "preprint_pdf",
            "reason": "manifest without file",
        }

    def test_check_fix_reconciles_pinax_manifest_drift(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "A_preprint.pdf").write_bytes(b"pdf")
        (files / ".pinax").mkdir()
        (files / ".pinax" / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": {
                        "A": {
                            "published_pdf": {
                                "source": "manual",
                                "added_date": "2026-06-27",
                                "sha256": "0" * 64,
                                "refetchable": False,
                            }
                        },
                        "Ghost": {},
                    },
                }
            )
        )
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\nfiles-dir:\n}\n")

        result = runner.invoke(app, ["files", "check", str(bib), "--fix", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert {item["action"] for item in data["fixed"]} == {
            "removed_missing_file",
            "removed_orphan_row",
            "added_manual_record",
        }
        assert data["pinax"]["drift"] == []
        manifest = json.loads((files / ".pinax" / "manifest.json").read_text())
        assert "Ghost" not in manifest["files"]
        assert manifest["files"]["A"]["preprint_pdf"]["source"] == "manual"


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <published>2023-01-02T00:00:00Z</published>
    <title>A Deep Test of arXiv Import</title>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
</feed>
"""


class TestAddCommand:
    provider_bibtex = """@article{provider-key,
  author = {Jane Smith and John Doe},
  title = {A Practical Test of DOI Import},
  journal = {Journal of Tests},
  year = {2024},
  doi = {10.5555/provider}
}
"""

    def test_add_dry_run_diff_does_not_write(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app,
            ["add", "10.5555/provider", str(bib), "--dry-run", "--diff", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Smith2024Practical"
        assert data["identifier_type"] == "doi"
        assert "@article{Smith2024Practical," in data["diff"]
        assert bib.read_text() == original

    def test_add_writes_entry(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["add", "10.5555/provider", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "@article{Smith2024Practical," in text
        assert "doi = {10.5555/provider}" in text

    def test_add_places_entry_before_trailing_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Existing,\n"
            "  title = {Existing}\n"
            "}\n"
            "\n"
            "@comment{jabref-meta: databaseType:bibtex;}\n"
        )
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["add", "10.5555/provider", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("@article{Existing,") < text.index("@article{Smith2024Practical,")
        assert text.index("@article{Smith2024Practical,") < text.index("@comment{jabref-meta:")

    def test_add_arxiv_writes_misc_entry(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)

        result = runner.invoke(app, ["add", "arXiv:2301.00001", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["identifier_type"] == "arxiv"
        assert data["entry_type"] == "misc"
        assert data["identifier"] == "2301.00001"
        text = bib.read_text()
        assert "@misc{" in text
        assert "eprint = {2301.00001}" in text
        assert "archivePrefix = {arXiv}" in text
        assert "year = {2023}" in text

    def test_add_arxiv_url_in_biblatex_writes_online_entry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{jabref-meta: databaseType:biblatex;}\n")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)

        result = runner.invoke(
            app, ["add", "https://arxiv.org/abs/2301.00001v1", str(bib), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["entry_type"] == "online"
        text = bib.read_text()
        assert "@online{" in text
        assert "eprinttype = {arxiv}" in text
        assert "date = {2023-01-02}" in text
        assert text.index("@online{") < text.index("@comment{jabref-meta:")

    def test_add_fetch_downloads_arxiv_materials(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{jabref-meta: databaseType:biblatex;}\n")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)
        monkeypatch.setattr("pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id: b"%PDF fixture")
        monkeypatch.setattr(
            "pynakes.fetch.fetch_arxiv_source",
            lambda arxiv_id: _tar_bytes({"paper.tex": b"\\title{A Deep Test}\n"}),
        )

        result = runner.invoke(app, ["add", "arXiv:2301.00001", str(bib), "--fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        assert data["fetch"]["fetched"][0]["key"] == key
        assert data["fetch"]["fetch_preprint"] is True
        assert data["fetch"]["fetch_source"] is True
        assert (tmp_path / "refs.files" / f"{key}_preprint.pdf").read_bytes() == b"%PDF fixture"
        assert (tmp_path / "refs.files" / f"{key}_preprint" / "paper.tex").read_text() == (
            "\\title{A Deep Test}\n"
        )
        assert "files-dir: refs.files" in bib.read_text()

    def test_add_fetch_honors_fetch_source_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{pynakes-meta:\nfetch-source: false\n}\n")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)
        monkeypatch.setattr("pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id: b"%PDF fixture")

        def fail_source(arxiv_id: str) -> bytes:
            raise AssertionError("source fetcher should not run")

        monkeypatch.setattr("pynakes.fetch.fetch_arxiv_source", fail_source)

        result = runner.invoke(app, ["add", "arXiv:2301.00001", str(bib), "--fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        fetched = data["fetch"]["fetched"][0]
        assert data["fetch"]["fetch_source"] is False
        assert fetched["pdf_path"] == str(tmp_path / "refs.files" / f"{key}_preprint.pdf")
        assert fetched["source_path"] is None
        assert not (tmp_path / "refs.files" / f"{key}_preprint").exists()

    def test_add_uses_jabref_key_pattern_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
        )
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["add", "10.5555/provider", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "Smith24Practical"
        assert data["key_source"] == "generated"
        assert "@article{Smith24Practical," in bib.read_text()

    def test_add_can_use_provider_key(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app,
            ["add", "10.5555/provider", str(bib), "--key-source", "provider", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "provider-key"
        assert data["key_source"] == "provider"

    def test_add_explicit_key_wins(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app,
            [
                "add",
                "10.5555/provider",
                str(bib),
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

    def test_add_invalid_key_source_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            ["add", "10.5555/provider", str(bib), "--key-source", "garbage", "--json"],
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidKeySource"

    def test_add_duplicate_doi_conflicts(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            ["add", "https://doi.org/10.1234/nature.ml.2020", str(bib), "--json"],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "DuplicateReference"
        assert data["existing_keys"] == ["Smith2020"]

    def test_add_citation_key_conflict(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app,
            ["add", "10.5555/provider", str(bib), "--key", "Smith2020", "--json"],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "CitationKeyConflict"
        assert data["key"] == "Smith2020"

    def test_add_citation_key_conflict_human(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["add", "10.5555/provider", str(bib), "--key", "Smith2020"])
        assert result.exit_code == 2, result.output
        assert "CitationKeyConflict" in result.output

    def test_add_unrecognized_identifier_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["add", "not-an-identifier", str(bib), "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UnsupportedIdentifier"

    def test_add_provider_failure_errors(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")

        def _boom(doi: str) -> str:
            raise importer_ops.DOIImportError("resolver offline")

        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", _boom)
        result = runner.invoke(app, ["add", "10.5555/provider", str(bib), "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "ReferenceImportError"

    def test_add_duplicate_doi_human_output(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["add", "https://doi.org/10.1234/nature.ml.2020", str(bib)])
        assert result.exit_code == 2, result.output
        assert "DuplicateReference" in result.output
        assert "--allow-duplicate" in result.output


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return buffer.getvalue()


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
    def test_generate_single_key_uses_preferred_pattern(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{Old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{Keep,\n  author = {Jane Doe},\n  year = {2023},\n  title = {Other}\n}\n"
        )

        result = runner.invoke(app, ["keys", "generate", str(bib), "--key", "Old", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["renames"] == [{"old": "Old", "new": "Smith24"}]
        text = bib.read_text()
        assert "@article{Smith24," in text
        assert "@article{Keep," in text

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

    def test_rename_moves_pinax_materials_on_commit(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "Smith2020_preprint.pdf").write_bytes(b"pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Smith2020,\n  title = {T}\n}\n@comment{pynakes-meta:\nfiles-dir:\n}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", str(tex)]
        )

        assert result.exit_code == 0, result.output
        assert not (files / "Smith2020_preprint.pdf").exists()
        assert (files / "Smith2020ML_preprint.pdf").read_bytes() == b"pdf"

    def test_generate_pinax_material_move_respects_dry_run(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "Old_preprint.pdf").write_bytes(b"pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Old,\n  author = {Jane Smith},\n  title = {A Test},\n  year = {2020}\n}\n"
            "@comment{pynakes-meta:\nfiles-dir:\n}\n"
        )

        result = runner.invoke(
            app, ["keys", "generate", str(bib), "--key", "Old", "--dry-run", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert (files / "Old_preprint.pdf").read_bytes() == b"pdf"
        assert not (files / "Smith2020Test_preprint.pdf").exists()

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

    def test_normalize_repairs_bare_month_name(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A, month = june}\n")

        result = runner.invoke(app, ["normalize", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["operations"]["months"] == 1
        assert bib.read_text() == "@article{A, month = jun}\n"

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

    def test_convert_requires_explicit_target(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "bibtex_classic.bib")

        result = runner.invoke(app, ["convert", str(bib), "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "MissingConvertTarget"
        assert bib.read_text() == (FIXTURES / "bibtex_classic.bib").read_text()

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

        result = runner.invoke(app, ["convert", str(bib), "--to", "bogus-format", "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "UnknownConvertTarget"

    def test_convert_export_to_csl_json_stdout(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A, author = {Doe, J}, title = {T}, journal = {J}, year = {2020}}\n"
        )

        result = runner.invoke(app, ["convert", str(bib), "--to", "csl-json"])

        assert result.exit_code == 0, result.output
        items = json.loads(result.output)
        assert items[0]["id"] == "A"
        assert items[0]["type"] == "article-journal"
        assert bib.read_text().startswith("@article{A,")  # source untouched

    def test_convert_export_to_ris_file(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A, author = {Doe, J}, title = {T}, journal = {J}, year = {2020}}\n"
        )
        out = tmp_path / "refs.ris"

        result = runner.invoke(
            app, ["convert", str(bib), "--to", "ris", "--out", str(out), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert (data["to"], data["written"], data["entry_count"]) == ("ris", True, 1)
        assert "TY  - JOUR" in out.read_text()

    def test_convert_export_to_mods_file(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A, author = {Doe, J}, title = {T}, journal = {J}, year = {2020}}\n"
        )
        out = tmp_path / "refs.xml"

        result = runner.invoke(
            app, ["convert", str(bib), "--to", "mods", "--out", str(out), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert (data["to"], data["written"], data["entry_count"]) == ("mods", True, 1)
        assert "<modsCollection" in out.read_text()

    def test_convert_import_from_ris(self, tmp_path: Path) -> None:
        ris = tmp_path / "in.ris"
        ris.write_text("TY  - JOUR\nAU  - Doe, Jane\nTI  - A Study\nPY  - 2021\nER  - \n")

        result = runner.invoke(app, ["convert", str(ris), "--from", "ris"])

        assert result.exit_code == 0, result.output
        assert "@article{" in result.output
        assert "author = {Doe, Jane}" in result.output
        assert "title = {A Study}" in result.output

    def test_convert_import_from_endnote(self, tmp_path: Path) -> None:
        tagged = tmp_path / "in.enw"
        tagged.write_text("%0 Journal Article\n%A Doe, Jane\n%T A Study\n%D 2021\n")

        result = runner.invoke(app, ["convert", str(tagged), "--from", "endnote"])

        assert result.exit_code == 0, result.output
        assert "@article{" in result.output
        assert "author = {Doe, Jane}" in result.output
        assert "title = {A Study}" in result.output

    def test_convert_import_foreign_to_foreign_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "in.ris"
        src.write_text("TY  - JOUR\nER  - \n")

        result = runner.invoke(
            app, ["convert", str(src), "--from", "ris", "--to", "csl-json", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UnsupportedConversion"


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
