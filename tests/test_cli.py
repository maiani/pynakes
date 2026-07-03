"""CLI smoke tests."""

import json
import re
import tarfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import __version__
from pynakes import importer as importer_ops
from pynakes.cli import app
from pynakes.cli_common import _metadata_cache_dir

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain_cli_output(value: str) -> str:
    """Strip Rich ANSI styling and collapse help-table wrapping."""
    return " ".join(_ANSI_RE.sub("", value).replace("│", " ").split())


class TestVersion:
    @pytest.mark.parametrize("flag", ["--version", "-V"])
    def test_prints_installed_package_version(self, flag: str) -> None:
        result = runner.invoke(app, [flag])

        assert result.exit_code == 0, result.output
        assert result.output == f"{__version__}\n"


class TestTopLevelHelp:
    def test_lists_subcommands_for_each_group(self) -> None:
        # Grouping commands under sub-apps must not hide the operations: the
        # top-level --help enumerates each group's subcommands inline.
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, result.output
        out = _plain_cli_output(result.output)
        # The group name sits in its own table column; the description column
        # ends with "→ <subcommands>".
        assert "→ add, import, remove" in out
        assert "→ fetch, check" in out
        assert "→ combine, split, batch" in out
        assert "→ list, add, remove, clear, scan" in out

    def test_leaf_commands_have_no_arrow(self) -> None:
        result = runner.invoke(app, ["--help"])
        out = _plain_cli_output(result.output)
        # A flat command like `normalize` is not a group; it gets no subcommand list.
        assert "normalize →" not in out


def test_default_metadata_cache_dir_anchors_symlinked_bib_at_link_path(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    link_dir = tmp_path / "linked"
    real_dir.mkdir()
    link_dir.mkdir()
    real_bib = real_dir / "refs.bib"
    real_bib.write_text("@article{A, title = {T}}\n")
    link_bib = link_dir / "refs.bib"
    link_bib.symlink_to(real_bib)

    assert _metadata_cache_dir(str(link_bib), None, True) == str(link_dir / ".pynakes-cache")


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

        result = runner.invoke(app, ["tex", "scan", "sources", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["report"]["used"] == ["Smith2020"]

    def test_report_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())

        result = runner.invoke(
            app, ["tex", "scan", str(bib), str(FIXTURES / "paper.aux"), "--json"]
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
            ["tex", "scan", str(bib), str(FIXTURES / "paper.aux"), "--group", "Used", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert bib.read_text() == original  # unchanged
        assert "Would tag" in result.output

    def test_group_tag_writes(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text((FIXTURES / "simple.bib").read_text())

        result = runner.invoke(
            app, ["tex", "scan", str(bib), str(FIXTURES / "paper.aux"), "--group", "Cited"]
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
        result = runner.invoke(app, ["tex", "scan", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["report"]["used"] == ["Smith2020"]

    def test_used_without_sources_or_metadata_errors(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(app, ["tex", "scan", str(bib), "--json"])

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "NoSources"

    def test_inplace_tag_preserves_untouched_entries(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (FIXTURES / "simple.bib").read_text()
        bib.write_text(original)

        runner.invoke(
            app, ["tex", "scan", str(bib), str(FIXTURES / "paper.aux"), "--group", "Cited"]
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
            app, ["tex", "scan", str(bib), str(FIXTURES / "paper.aux"), "--out", str(out)]
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

    def test_lint_discovers_lone_bib_file_without_options(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@book{Knuth1984,\n"
            "  author = {Donald E. Knuth},\n"
            "  title = {The TeXbook},\n"
            "  publisher = {Addison-Wesley},\n"
            "  year = {1984}\n"
            "}\n"
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["lint"])

        assert result.exit_code == 0, result.output
        assert "refs.bib: no issues found." in result.output

    def test_auto_discovery_ignores_revtex_notes_bib(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        (tmp_path / "refsNotes.bib").write_text("@article{N,\n  title = {Generated Notes}\n}\n")
        (tmp_path / "refs_diffNotes.bib").write_text(
            "@article{D,\n  title = {Generated Diff Notes}\n}\n"
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["inspect", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == "refs.bib"

    def test_explicit_revtex_notes_bib_is_still_allowed(self, tmp_path: Path) -> None:
        notes = tmp_path / "refsNotes.bib"
        notes.write_text("@article{N,\n  title = {Generated Notes}\n}\n")

        result = runner.invoke(app, ["inspect", str(notes), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == str(notes)

    def test_variadic_nested_check_discovers_lone_bib_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["keys", "check", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"

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
        (files / "A.preprint.pdf").write_bytes(b"pdf")
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
        assert entry["preprint_pdf"] == str(files / "A.preprint.pdf")
        assert entry["canonical_pdf"] == str(files / "A.preprint.pdf")
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

    def test_search_auto_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["search", "widget", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["matches"][0]["key"] == "Alpha"

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

        result = runner.invoke(app, ["asset", "check", str(bib), "--json"])

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

        result = runner.invoke(app, ["asset", "check", str(bib), "--root", str(root), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] == 1
        assert data["files"][0]["resolved_path"] == str(root / "A.pdf")

    def test_check_human_lists_issues(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T},\n  file = {missing.pdf}\n}\n")

        result = runner.invoke(app, ["asset", "check", str(bib)])

        assert result.exit_code == 0, result.output
        assert "checked 1 linked file" in result.output
        assert "[missing] A[0]: missing.pdf" in result.output

    def test_check_json_reports_pinax_orphans_and_drift(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "Ghost.published.pdf").write_bytes(b"pdf")
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

        result = runner.invoke(app, ["asset", "check", str(bib), "--json"])

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
        (files / "A.preprint.pdf").write_bytes(b"pdf")
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

        result = runner.invoke(app, ["asset", "check", str(bib), "--fix", "--json"])

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

    def test_check_fix_backup_writes_manifest_bak(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "A.preprint.pdf").write_bytes(b"pdf")
        (files / ".pinax").mkdir()
        manifest = files / ".pinax" / "manifest.json"
        manifest.write_text(
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
                        }
                    },
                }
            )
        )
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\nfiles-dir:\n}\n")

        result = runner.invoke(app, ["asset", "check", str(bib), "--fix", "--backup", "--json"])

        assert result.exit_code == 0, result.output
        backup = files / ".pinax" / "manifest.json.bak"
        assert backup.exists()
        assert "published_pdf" in backup.read_text()
        assert "published_pdf" not in manifest.read_text()


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <published>2023-01-02T00:00:00Z</published>
    <updated>2023-01-15T12:00:00Z</updated>
    <title>A Deep Test of arXiv Import</title>
    <summary>We present a deep test of the arXiv import functionality.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
</feed>
"""


class TestImportCommand:
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
            ["ref", "import", "10.5555/provider", str(bib), "--dry-run", "--diff", "--json"],
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

        result = runner.invoke(app, ["ref", "import", "10.5555/provider", str(bib)])

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

        result = runner.invoke(app, ["ref", "import", "10.5555/provider", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("@article{Existing,") < text.index("@article{Smith2024Practical,")
        assert text.index("@article{Smith2024Practical,") < text.index("@comment{jabref-meta:")

    def test_add_arxiv_writes_misc_entry(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)

        result = runner.invoke(app, ["ref", "import", "arXiv:2301.00001", str(bib), "--json"])

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
        assert "month = {jan}" in text
        assert "abstract = {We present a deep test of the arXiv import functionality.}" in text
        assert "updated = {2023-01-15}" in text

    def test_add_arxiv_url_in_biblatex_writes_online_entry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{jabref-meta: databaseType:biblatex;}\n")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)

        result = runner.invoke(
            app, ["ref", "import", "https://arxiv.org/abs/2301.00001v1", str(bib), "--json"]
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
        monkeypatch.setattr(
            "pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id, **kwargs: b"%PDF fixture"
        )
        monkeypatch.setattr(
            "pynakes.fetch.fetch_arxiv_source",
            lambda arxiv_id, **kwargs: _tar_bytes({"paper.tex": b"\\title{A Deep Test}\n"}),
        )

        result = runner.invoke(
            app, ["ref", "import", "arXiv:2301.00001", str(bib), "--fetch", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        assert data["fetch"]["fetched"][0]["key"] == key
        assert data["fetch"]["fetch_preprint"] is True
        assert data["fetch"]["fetch_source"] is True
        assert (tmp_path / "refs.files" / f"{key}.preprint.pdf").read_bytes() == b"%PDF fixture"
        assert (tmp_path / "refs.files" / f"{key}.source" / "paper.tex").read_text() == (
            "\\title{A Deep Test}\n"
        )
        assert "files-dir: refs.files" in bib.read_text()

    def test_add_fetch_honors_fetch_source_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{pynakes-meta:\nfetch-source: false\n}\n")
        monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: ARXIV_ATOM)
        monkeypatch.setattr(
            "pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id, **kwargs: b"%PDF fixture"
        )

        def fail_source(arxiv_id: str) -> bytes:
            raise AssertionError("source fetcher should not run")

        monkeypatch.setattr("pynakes.fetch.fetch_arxiv_source", fail_source)

        result = runner.invoke(
            app, ["ref", "import", "arXiv:2301.00001", str(bib), "--fetch", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        fetched = data["fetch"]["fetched"][0]
        assert data["fetch"]["fetch_source"] is False
        assert fetched["pdf_path"] == str(tmp_path / "refs.files" / f"{key}.preprint.pdf")
        assert fetched["source_path"] is None
        assert not (tmp_path / "refs.files" / f"{key}.source").exists()

    def test_import_fetch_reuses_published_fetch_path(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        cache = tmp_path / "provider-cache"
        bib.write_text("@comment{pynakes-meta:\nfetch-published: true\n}\n")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        def fake_urlopen(request: object, timeout: float = 30.0) -> BytesIO:
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "openalex.org" in str(url):
                body = json.dumps(
                    {"best_oa_location": {"host_type": "publisher", "pdf_url": "https://example.com/provider.pdf"}}
                ).encode("utf-8")
                return BytesIO(body)
            raise AssertionError("unexpected urlopen call")

        monkeypatch.setattr("pynakes.fetch._default_urlopen", fake_urlopen)
        monkeypatch.setattr(
            "pynakes.fetch.fetch_published_pdf", lambda url, **kwargs: b"%PDF published"
        )

        result = runner.invoke(
            app,
            [
                "ref",
                "import",
                "10.5555/provider",
                str(bib),
                "--fetch",
                "--cache-dir",
                str(cache),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        assert data["fetch"]["fetch_published"] is True
        assert data["fetch"]["fetched"] == [
            {
                "key": key,
                "doi": "10.5555/provider",
                "arxiv_id": None,
                "pdf_path": str(tmp_path / "refs.files" / f"{key}.published.pdf"),
                "source_path": None,
            }
        ]
        assert (tmp_path / "refs.files" / f"{key}.published.pdf").read_bytes() == b"%PDF published"
        assert len(list((cache / "openalex").glob("*.json"))) == 1

    def test_add_uses_jabref_key_pattern_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
        )
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["ref", "import", "10.5555/provider", str(bib), "--json"])

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
            ["ref", "import", "10.5555/provider", str(bib), "--key-source", "provider", "--json"],
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
                "ref",
                "import",
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
            ["ref", "import", "10.5555/provider", str(bib), "--key-source", "garbage", "--json"],
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidKeySource"

    def test_add_duplicate_doi_conflicts(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            ["ref", "import", "https://doi.org/10.1234/nature.ml.2020", str(bib), "--json"],
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
            ["ref", "import", "10.5555/provider", str(bib), "--key", "Smith2020", "--json"],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "CitationKeyConflict"
        assert data["key"] == "Smith2020"

    def test_add_citation_key_conflict_human(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(
            app, ["ref", "import", "10.5555/provider", str(bib), "--key", "Smith2020"]
        )
        assert result.exit_code == 2, result.output
        assert "CitationKeyConflict" in result.output

    def test_add_unrecognized_identifier_errors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "import", "not-an-identifier", str(bib), "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UnsupportedIdentifier"

    def test_add_provider_failure_errors(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")

        def _boom(doi: str) -> str:
            raise importer_ops.DOIImportError("resolver offline")

        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", _boom)
        result = runner.invoke(app, ["ref", "import", "10.5555/provider", str(bib), "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "ReferenceImportError"

    def test_import_dry_run_failure_reports_no_write_context(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()

        def _boom(doi: str) -> str:
            raise importer_ops.DOIImportError("resolver offline")

        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", _boom)
        result = runner.invoke(
            app, ["ref", "import", "10.5555/provider", str(bib), "--dry-run", "--json"]
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "ReferenceImportError"
        assert data["dry_run"] is True
        assert data["modified"] is False
        assert "No changes were written" in data["message"]
        assert bib.read_text() == original

    def test_add_duplicate_doi_human_output(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["ref", "import", "https://doi.org/10.1234/nature.ml.2020", str(bib)]
        )
        assert result.exit_code == 2, result.output
        assert "DuplicateReference" in result.output
        assert "--allow-duplicate" in result.output


class TestAddCommand:
    def test_add_manual_entry_dry_run_diff_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()

        result = runner.invoke(
            app,
            [
                "ref",
                "add",
                "Manual2026",
                str(bib),
                "--type",
                "book",
                "--field",
                "author=Ada Lovelace",
                "--field",
                "title=Notes on Analytical Engines",
                "--field",
                "year=1843",
                "--dry-run",
                "--diff",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "add"
        assert data["key"] == "Manual2026"
        assert data["entry_type"] == "book"
        assert data["fields"]["year"] == "1843"
        assert "@book{Manual2026," in data["diff"]
        assert bib.read_text() == original

    def test_add_manual_entry_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            [
                "ref",
                "add",
                "Manual2026",
                str(bib),
                "--field",
                "title=Manual Reference",
                "--field",
                "year=2026",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert "@article{Manual2026," in text
        assert "title = {Manual Reference}" in text
        assert "year = {2026}" in text

    def test_add_manual_entry_auto_detects_lone_bib(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["ref", "add", "Manual2026", "--field", "title=Manual Reference"]
        )

        assert result.exit_code == 0, result.output
        assert "@article{Manual2026," in bib.read_text()

    def test_add_manual_entry_rejects_existing_key(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "add", "Smith2020", str(bib), "--field", "title=X", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "InvalidInput"

    def test_add_manual_entry_rejects_bad_field_assignment(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "add", "Manual2026", str(bib), "--field", "title", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "InvalidInput"


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

    def test_list_auto_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        _copy(tmp_path, "jabref_groups.bib")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["groups", "list", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert "Machine Learning" in data["groups"]

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


class TestMetadataCommand:
    def test_list_auto_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{pynakes-meta: dialect:biblatex;}\n@article{A,\n  title = {T}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["metadata", "list", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["effective"]["dialect"] == "biblatex;"


class TestKeysCommand:
    def test_generate_help_uses_all_not_key_option(self) -> None:
        result = runner.invoke(app, ["keys", "generate", "--help"])

        assert result.exit_code == 0, result.output
        out = _plain_cli_output(result.output)
        assert "--all" in out
        assert "--key" not in out

    def test_generate_single_key_uses_preferred_pattern(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{Old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{Keep,\n  author = {Jane Doe},\n  year = {2023},\n  title = {Other}\n}\n"
        )

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["renames"] == [{"old": "Old", "new": "Smith24"}]
        text = bib.read_text()
        assert "@article{Smith24," in text
        assert "@article{Keep," in text

    def test_generate_single_key_accepts_key_before_file(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Archive.Ref.1,\n"
            "  author = {Ada Lovelace},\n"
            "  year = {1843},\n"
            "  title = {Notes on Computation}\n"
            "}\n"
        )
        (tmp_path / "other.bib").write_text("@article{Other,\n  title = {Other}\n}\n")

        result = runner.invoke(app, ["keys", "generate", "Archive.Ref.1", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["renames"] == [
            {"old": "Archive.Ref.1", "new": "Lovelace1843Notes"}
        ]
        assert "@article{Lovelace1843Notes," in bib.read_text()

    def test_generate_single_key_accepts_file_before_positional_key(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["renames"] == [{"old": "Old", "new": "Hopper1952Compiler"}]

    def test_generate_single_key_updates_linked_tex_sources(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Old}" "\n" r"% \cite{Old}" "\n")

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["renames"] == [{"old": "Old", "new": "Hopper1952Compiler"}]
        assert data["source_occurrences"] == 1
        assert data["sources"][0]["occurrences"] == 1
        assert "@article{Hopper1952Compiler," in bib.read_text()
        text = tex.read_text()
        assert r"\cite{Hopper1952Compiler}" in text
        assert r"% \cite{Old}" in text

    def test_generate_single_key_updates_all_linked_tex_sources(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex, supplement.tex;}\n"
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )
        paper = tmp_path / "paper.tex"
        supplement = tmp_path / "supplement.tex"
        paper.write_text(r"\cite{Old}" "\n")
        supplement.write_text(r"\citep{Old}" "\n")

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["source_occurrences"] == 2
        assert {Path(source["path"]).name for source in data["sources"]} == {
            "paper.tex",
            "supplement.tex",
        }
        assert paper.read_text() == r"\cite{Hopper1952Compiler}" "\n"
        assert supplement.read_text() == r"\citep{Hopper1952Compiler}" "\n"

    def test_generate_single_key_merges_jabref_and_pynakes_tex_sources(
        self, tmp_path: Path
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: tex-sources:paper.tex;}\n"
            "@comment{pynakes-meta:\ntex-sources: supplement.tex\n}\n"
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )
        paper = tmp_path / "paper.tex"
        supplement = tmp_path / "supplement.tex"
        paper.write_text(r"\cite{Old}" "\n")
        supplement.write_text(r"\citep{Old}" "\n")

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["source_occurrences"] == 2
        assert paper.read_text() == r"\cite{Hopper1952Compiler}" "\n"
        assert supplement.read_text() == r"\citep{Hopper1952Compiler}" "\n"

    def test_generate_single_key_updates_linked_tex_sources_dry_run_diff(
        self, tmp_path: Path
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Old}" "\n")
        original_bib = bib.read_text()
        original_tex = tex.read_text()

        result = runner.invoke(
            app, ["keys", "generate", str(bib), "Old", "--dry-run", "--diff", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["source_occurrences"] == 1
        assert "@article{Hopper1952Compiler," in data["diff"]
        assert r"\cite{Hopper1952Compiler}" in data["diff"]
        assert bib.read_text() == original_bib
        assert tex.read_text() == original_tex

    def test_generate_all_updates_linked_tex_sources_simultaneously(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
            "@article{A,\n"
            "  author = {Alice Beta},\n"
            "  year = {2020},\n"
            "  title = {Target}\n"
            "}\n"
            "@article{Beta2020Target,\n"
            "  author = {Carol Clark},\n"
            "  year = {2021},\n"
            "  title = {Other}\n"
            "}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{A,Beta2020Target}" "\n")

        result = runner.invoke(app, ["keys", "generate", str(bib), "--all", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["renames"] == [
            {"old": "A", "new": "Beta2020Target"},
            {"old": "Beta2020Target", "new": "Clark2021Other"},
        ]
        assert data["source_occurrences"] == 2
        assert tex.read_text() == r"\cite{Beta2020Target,Clark2021Other}" "\n"

    def test_generate_requires_key_or_all(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(app, ["keys", "generate", str(bib), "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidInput"
        assert "--all" in data["message"]

    def test_check_reports_duplicates(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        result = runner.invoke(app, ["keys", "check", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["has_duplicates"] is True
        assert any(
            issue["type"] == "duplicate_key" and issue["severity"] == "error"
            for issue in data["issues"]
        )

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

    def test_repair_auto_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["keys", "repair", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["renames"]
        assert bib.exists()

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
        (files / "Smith2020.preprint.pdf").write_bytes(b"pdf")
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
        assert not (files / "Smith2020.preprint.pdf").exists()
        assert (files / "Smith2020ML.preprint.pdf").read_bytes() == b"pdf"

    def test_generate_pinax_material_move_respects_dry_run(self, tmp_path: Path) -> None:
        files = tmp_path / "refs.files"
        files.mkdir()
        (files / "Old.preprint.pdf").write_bytes(b"pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Old,\n  author = {Jane Smith},\n  title = {A Test},\n  year = {2020}\n}\n"
            "@comment{pynakes-meta:\nfiles-dir:\n}\n"
        )

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        assert (files / "Old.preprint.pdf").read_bytes() == b"pdf"
        assert not (files / "Smith2020Test.preprint.pdf").exists()

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

    def test_normalize_dry_run_diff_json_with_duplicate_keys(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (
            "@article{Smith2020,\n"
            "  author = {Jane Smith and Alan Doe},\n"
            "  title = {A Small Study of Deterministic Widgets},\n"
            "  journal = {Journal of Widget Studies},\n"
            "  year = {2020},\n"
            "  doi = {https://doi.org/10.5555/widget.2020}\n"
            "}\n\n"
            "@article{Smith2020,\n"
            "  author = {Jane Smith and Alan Doe},\n"
            "  title = {A Small Study of Deterministic Widgets},\n"
            "  journal = {Journal of Widget Studies},\n"
            "  year = {2020},\n"
            "  doi = {10.5555/widget.2020}\n"
            "}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--doi-normalization",
                "on",
                "--identifier-case",
                "on",
                "--metadata-formatting",
                "on",
                "--title-protection",
                "off",
                "--author-style",
                "none",
                "--journal-style",
                "none",
                "--sort-by",
                "original",
                "--dry-run",
                "--diff",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified_entries"] == 1
        assert data["plan"]["summary"]["modified"] == 1
        assert data["plan"]["entries"] == [
            {
                "change": "modified",
                "key": "Smith2020",
                "entry_index": 0,
                "fields": {
                    "doi": {
                        "old": "https://doi.org/10.5555/widget.2020",
                        "new": "10.5555/widget.2020",
                    }
                },
            }
        ]
        assert "+  doi = {10.5555/widget.2020}\n" in data["diff"]
        assert "+  doi = {10.5555/widget.2020}}" not in data["diff"]
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

    def test_normalize_consolidates_metadata_by_namespace_position(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@Comment{jabref-meta: databaseType:bibtex;}\n"
            "\n"
            "@article{A,\n  author = {Smith, John},\n  title = {T}\n}\n"
            "\n"
            "@comment{pynakes-meta: normalize-journal-style:none;}\n"
        )

        result = runner.invoke(app, ["normalize", str(bib)])

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("@comment{pynakes-meta:") < text.index("@article{A,")
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

    def test_normalize_sort_by_key(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Zebra1980,\n  author = {Zebra, Z.},\n  title = {Z}\n}\n"
            "\n"
            "@article{Alpha2020,\n  author = {Alpha, A.},\n  title = {A}\n}\n"
        )

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "key",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("Alpha2020") < text.index("Zebra1980")

    def test_normalize_sort_by_year(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Later2020,\n  year = {2020},\n  author = {B, B.},\n  title = {B}\n}\n"
            "\n"
            "@article{Earlier1990,\n  year = {1990},\n  author = {A, A.},\n  title = {A}\n}\n"
        )

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "year",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("Earlier1990") < text.index("Later2020")

    def test_normalize_sort_dry_run_does_not_write(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (
            "@article{Zebra1980,\n  title = {Z}\n}\n\n@article{Alpha2020,\n  title = {A}\n}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "key",
                "--dry-run",
                "--json",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert bib.read_text() == original

    def test_normalize_sort_reported_in_operations(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Zebra1980,\n  title = {Z}\n}\n@article{Alpha2020,\n  title = {A}\n}\n"
        )

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "key",
                "--json",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["sorted_entries"] == 2

    def test_normalize_honors_jabref_save_order_config(self, tmp_path: Path) -> None:
        # With no --sort-by, normalize follows JabRef's own saveOrderConfig.
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: saveOrderConfig:specified;citationkey;false;}\n"
            "\n"
            "@article{Zebra1980,\n  title = {Z}\n}\n"
            "\n"
            "@article{Alpha2020,\n  title = {A}\n}\n"
        )

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
                "--metadata-formatting",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        assert text.index("Alpha2020") < text.index("Zebra1980")

    def test_normalize_save_order_original_is_not_sorted(self, tmp_path: Path) -> None:
        # saveOrderConfig type "original" means keep current order — no reorder.
        bib = tmp_path / "refs.bib"
        original = (
            "@comment{jabref-meta: saveOrderConfig:original;}\n"
            "\n"
            "@article{Zebra1980,\n  title = {Z}\n}\n"
            "\n"
            "@article{Alpha2020,\n  title = {A}\n}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
                "--metadata-formatting",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        assert bib.read_text() == original

    def test_normalize_sort_by_overrides_save_order_config(self, tmp_path: Path) -> None:
        # An explicit --sort-by original overrides a "specified" saveOrderConfig.
        bib = tmp_path / "refs.bib"
        original = (
            "@comment{jabref-meta: saveOrderConfig:specified;citationkey;false;}\n"
            "\n"
            "@article{Zebra1980,\n  title = {Z}\n}\n"
            "\n"
            "@article{Alpha2020,\n  title = {A}\n}\n"
        )
        bib.write_text(original)

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "original",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
                "--metadata-formatting",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        assert bib.read_text() == original

    def test_normalize_multi_criterion_sort_with_descending(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{C,\n  author = {Smith, A.},\n  year = {1990}\n}\n"
            "@article{A,\n  author = {Jones, B.},\n  year = {2020}\n}\n"
            "@article{B,\n  author = {Jones, B.},\n  year = {1995}\n}\n"
        )

        # Primary author ascending, secondary year descending.
        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--sort-by",
                "author",
                "--sort-by",
                "year:desc",
                "--author-style",
                "none",
                "--title-protection",
                "off",
                "--doi-normalization",
                "off",
            ],
        )

        assert result.exit_code == 0, result.output
        text = bib.read_text()
        # Jones entries come first (author asc); within Jones, 2020 before 1995.
        assert text.index("{A,") < text.index("{B,") < text.index("{C,")


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

    def test_convert_export_to_csv_stdout(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A, author = {Doe, J}, title = {T}, journal = {J}, year = {2020}}\n"
        )

        result = runner.invoke(app, ["convert", str(bib), "--to", "csv"])

        assert result.exit_code == 0, result.output
        assert "key,type,author,title,year" in result.output
        assert "A,article,\"Doe, J\",T,2020" in result.output
        assert bib.read_text().startswith("@article{A,")

    def test_convert_export_to_csv_file(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A, author = {Doe, J}, title = {T}, journal = {J}, year = {2020}}\n"
        )
        out = tmp_path / "refs.csv"

        result = runner.invoke(
            app, ["convert", str(bib), "--to", "csv", "--out", str(out), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert (data["to"], data["written"], data["entry_count"]) == ("csv", True, 1)
        csv_text = out.read_text()
        assert "key,type,author,title,year" in csv_text
        assert "A,article,\"Doe, J\",T,2020" in csv_text

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

    def test_convert_import_from_csv_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "in.csv"
        src.write_text("key,title\nA,T\n")

        result = runner.invoke(
            app, ["convert", str(src), "--from", "csv", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UnknownConvertSource"

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

    def test_omitted_bib_multiple_candidates_is_structured(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A multi-positional command (remove) with the library omitted and two
        # local .bib files must report the real cause as structured JSON — not
        # leak Click's misleading "Missing argument CITEKEYS" usage error.
        (tmp_path / "a.bib").write_text("@article{A,\n  title = {T}\n}\n")
        (tmp_path / "b.bib").write_text("@article{B,\n  title = {U}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["ref", "remove", "A", "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)  # parseable JSON, not a usage banner
        assert data["status"] == "error"
        assert data["error"] == "InvalidInput"
        assert "Multiple" in data["message"]

    def test_omitted_bib_no_candidates_is_structured(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # empty dir: no .bib to discover
        result = runner.invoke(app, ["fields", "rename", "journal", "journaltitle", "--json"])
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidInput"
        assert "No *.bib" in data["message"]

    def test_residual_usage_error_is_structured_json(self, tmp_path: Path) -> None:
        # File supplied, but a required positional is missing: the catch-all
        # reframes Click's usage error as the JSON envelope under --json.
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "remove", str(bib), "--json"])
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["error"] == "UsageError"

    def test_usage_error_human_mode_keeps_click_text(self, tmp_path: Path, monkeypatch) -> None:
        # Without --json, humans keep Click's usage text and its exit code 2.
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "remove", str(bib)])
        assert result.exit_code == 2
        assert not result.output.strip().startswith("{")
        assert "Usage:" in result.output

    def test_init_does_not_substitute_existing_bib(self, tmp_path: Path, monkeypatch) -> None:
        # init creates a library, so it must NOT auto-detect and clobber an
        # existing local .bib when its path argument is omitted.
        existing = tmp_path / "refs.bib"
        existing.write_text("@article{Keep,\n  title = {Original}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["init", "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "InvalidInput"  # missing FILE, not a clobber
        assert existing.read_text() == "@article{Keep,\n  title = {Original}\n}\n"

    def test_shell_completion_does_not_emit_missing_bib_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        (tmp_path / "a.bib").write_text("@article{A,\n  title = {T}\n}\n")
        (tmp_path / "b.bib").write_text("@article{B,\n  title = {U}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            [],
            env={
                "COMP_WORDS": "pynakes keys generate A a",
                "COMP_CWORD": "4",
                "_PYNAKES_COMPLETE": "complete_bash",
            },
            prog_name="pynakes",
        )

        assert result.exit_code == 0, result.output
        assert "InvalidInput" not in result.output


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
            [
                "tex",
                "scan",
                str(bib),
                str(FIXTURES / "paper.aux"),
                "--group",
                "X",
                "--dry-run",
                "--json",
            ],
        )
        data = json.loads(r.output)
        assert self.ENVELOPE <= set(data)
        assert "input_path" not in data  # standardized to "file"


# Each case: (command prefix, positional suffix after <file>, fixture). The
# runner inserts the bib path right after the prefix. Every case is chosen to
# actually modify its fixture, so --diff must produce a diff.
class TestSourcesCommand:
    def test_list_no_sources(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        result = runner.invoke(app, ["tex", "list", "--file", str(bib)])
        assert result.exit_code == 0, result.output
        assert "no TeX sources linked" in result.output

    def test_list_with_sources(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )
        result = runner.invoke(app, ["tex", "list", "--file", str(bib)])
        assert result.exit_code == 0, result.output
        assert "paper.tex" in result.output

    def test_list_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )
        result = runner.invoke(app, ["tex", "list", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["sources"] == [str(tmp_path / "paper.tex")]

    def test_add(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(
            app, ["tex", "add", "paper.tex", "supplement.tex", "--file", str(bib)]
        )
        assert result.exit_code == 0, result.output
        assert "linked" in result.output.lower() or "link" in result.output.lower()
        text = bib.read_text()
        assert "tex-sources" in text
        assert "tex-sources: paper.tex, supplement.tex" in text

    @pytest.mark.parametrize(
        "args",
        [
            ["refs.bib", "paper.tex", "supplement.tex"],
            ["paper.tex", "supplement.tex", "refs.bib"],
        ],
    )
    def test_add_accepts_one_positional_bib_with_multiple_local_bibs(
        self, tmp_path: Path, monkeypatch, args: list[str]
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        other = tmp_path / "notes.bib"
        other.write_text("@article{B,\n  title = {U}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["tex", "add", *args, "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["added"] == ["paper.tex", "supplement.tex"]
        assert "tex-sources: paper.tex, supplement.tex" in bib.read_text()
        assert "tex-sources" not in other.read_text()

    def test_add_dry_run(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        before = bib.read_text()

        result = runner.invoke(
            app, ["tex", "add", "paper.tex", "--file", str(bib), "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert bib.read_text() == before
        data = json.loads(result.output)
        assert data["dry_run"] is True

    def test_add_duplicate_is_noop(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )
        before = bib.read_text()

        result = runner.invoke(app, ["tex", "add", "paper.tex", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        assert bib.read_text() == before
        data = json.loads(result.output)
        assert data["added"] == []

    def test_remove(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )

        result = runner.invoke(app, ["tex", "remove", "paper.tex", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "paper.tex" in data["removed"]
        assert "tex-sources" not in bib.read_text()

    def test_remove_accepts_one_positional_bib_with_multiple_local_bibs(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )
        other = tmp_path / "notes.bib"
        other.write_text("@article{B,\n  title = {U}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["tex", "remove", "paper.tex", "refs.bib", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["removed"] == ["paper.tex"]
        assert "tex-sources" not in bib.read_text()
        assert "tex-sources" not in other.read_text()

    def test_remove_canonicalizes_split_metadata_namespaces(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: tex-sources:paper.tex;}\n"
            "@comment{pynakes-meta:\ntex-sources: supplement.tex\n}\n"
            "@article{A,\n  title = {T}\n}\n"
        )

        result = runner.invoke(app, ["tex", "remove", "paper.tex", "--file", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["removed"] == ["paper.tex"]
        text = bib.read_text()
        assert "@comment{jabref-meta: tex-sources" not in text
        assert "tex-sources: supplement.tex" in text

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(app, ["tex", "remove", "paper.tex", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["removed"] == []

    def test_clear(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )

        result = runner.invoke(app, ["tex", "clear", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["cleared"] is True
        assert "tex-sources" not in bib.read_text()

    def test_clear_when_empty(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")

        result = runner.invoke(app, ["tex", "clear", "--file", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["cleared"] is False

    def test_add_discoverable_via_help(self) -> None:
        result = runner.invoke(app, ["tex", "--help"])
        assert result.exit_code == 0, result.output
        assert "add" in result.output
        assert "list" in result.output
        assert "remove" in result.output
        assert "clear" in result.output

    def test_auto_discover_bib(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T}\n}\n")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["tex", "add", "paper.tex", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert "paper.tex" in str(data["sources"])

    def test_add_dry_run_diff_json_integration(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        before = bib.read_text()
        result = runner.invoke(
            app,
            ["tex", "add", "paper.tex", "--file", str(bib), "--dry-run", "--diff", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert {
            "status",
            "action",
            "file",
            "dry_run",
            "modified",
            "modified_entries",
            "warnings",
        } <= set(data)
        assert data["dry_run"] is True
        assert data["modified"] is True
        assert data["diff"]
        assert bib.read_text() == before

    def test_list_auto_discover_bib(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex;}\n@article{A,\n  title = {T}\n}\n"
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["tex", "list", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert data["sources"]


_MODIFYING_CASES = [
    (["groups", "add-entry"], ["Smith2020", "Fav"], "simple.bib"),
    (["keys", "repair"], [], "duplicate_entries.bib"),
    (["keys", "generate"], ["--all"], "simple.bib"),
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


class TestAssetFetchPublished:
    """`asset fetch` with `fetch-published` metadata."""

    def test_fetch_published_downloads_oa_pdf(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Einstein1905,\n"
            '  title = {Zur Elektrodynamik bewegter K{\\"o}rper},\n'
            "  doi = {10.1002/andp.19053221004}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "files-dir: refs.files\n"
            "fetch-published: true\n"
            "}\n"
        )

        def fake_urlopen(request: object, timeout: float = 30.0) -> BytesIO:
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "openalex.org" in str(url):
                body = json.dumps(
                    {"best_oa_location": {"host_type": "publisher", "pdf_url": "https://example.com/paper.pdf"}}
                ).encode("utf-8")
                return BytesIO(body)
            raise AssertionError("unexpected urlopen call")

        monkeypatch.setattr("pynakes.fetch._default_urlopen", fake_urlopen)
        monkeypatch.setattr(
            "pynakes.fetch.fetch_published_pdf", lambda url, **kwargs: b"%PDF published"
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetch_published"] is True
        assert len(data["fetched"]) == 1
        assert data["fetched"][0]["key"] == "Einstein1905"
        assert data["fetched"][0]["pdf_path"] is not None
        assert (tmp_path / "refs.files" / "Einstein1905.published.pdf").read_bytes() == (b"%PDF published")
        assert len(list((tmp_path / ".pynakes-cache" / "openalex").glob("*.json"))) == 1

    def test_fetch_published_reports_malformed_doi_per_entry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{BadDoi,\n"
            "  title = {A Generic Example},\n"
            "  doi = {not-a-doi}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "files-dir: refs.files\n"
            "fetch-published: true\n"
            "}\n"
        )

        def fail_urlopen(request: object, timeout: float = 30.0) -> None:
            raise AssertionError("network should not be called for a malformed DOI")

        monkeypatch.setattr("pynakes.fetch._default_urlopen", fail_urlopen)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetched"] == []
        assert data["skipped"] == []
        assert len(data["failed"]) == 1
        assert data["failed"][0]["key"] == "BadDoi"
        assert "Malformed DOI" in data["failed"][0]["error"]

    def test_fetch_dry_run_reports_would_fetch(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Einstein1905,\n"
            "  title = {Zur Elektrodynamik},\n"
            "  doi = {10.1002/andp.19053221004}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "files-dir: refs.files\n"
            "fetch-published: true\n"
            "}\n"
        )

        def fail_urlopen(request: object, timeout: float = 30.0) -> None:
            raise AssertionError("dry-run should not call network")

        monkeypatch.setattr("pynakes.fetch._default_urlopen", fail_urlopen)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetched"] == []
        assert data["skipped"] == [{"key": "Einstein1905", "reason": "would fetch"}]
        assert data["failed"] == []

    def test_fetch_published_skips_when_disabled(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Einstein1905,\n"
            "  title = {Zur Elektrodynamik},\n"
            "  doi = {10.1002/andp.19053221004}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "files-dir: refs.files\n"
            "fetch-published: false\n"
            "}\n"
        )

        def fail_urlopen(request: object, timeout: float = 30.0) -> None:
            raise AssertionError("network should not be called")

        monkeypatch.setattr("pynakes.fetch._default_urlopen", fail_urlopen)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetch_published"] is False
        assert len(data["fetched"]) == 0
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "no arXiv id"
