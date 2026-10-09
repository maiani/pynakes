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
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories import ssrn

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
        assert "→ add, import, show, edit, directive, compare, find, remove" in out
        assert "→ fetch, check" in out
        assert "→ combine, split, batch" in out
        assert "→ list, add, remove, clear, scan" in out

    def test_leaf_commands_have_no_arrow(self) -> None:
        result = runner.invoke(app, ["--help"])
        out = _plain_cli_output(result.output)
        # A flat command like `normalize` is not a group; it gets no subcommand list.
        assert "normalize →" not in out


class TestFormatCommand:
    def test_help_exposes_layout_role_and_controls(self) -> None:
        result = runner.invoke(app, ["format", "--help"])
        assert result.exit_code == 0, result.output
        output = _plain_cli_output(result.output)
        assert "Rewrite layout only" in output
        assert "--indent" in output
        assert "--alignment" in output
        assert "--field-order" in output
        assert "--entry-order" in output
        assert "--block-order" in output
        assert "--wrap-values" in output
        assert "--line-width" in output
        assert "--sort-fields" not in output
        assert "--preserve-field-order" not in output
        assert "--tabular" not in output
        assert "--settings" not in output

        normalize_help = _plain_cli_output(runner.invoke(app, ["normalize", "--help"]).output)
        assert "--layout" not in normalize_help
        assert "--check" not in normalize_help

    def test_format_refuses_repeated_fields_with_lint_findings(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        original = "@misc{A, title={First}, title={Second}}\n"
        path.write_text(original)
        result = runner.invoke(app, ["format", str(path), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "FormatLintError"
        assert [issue["type"] for issue in payload["issues"]] == ["duplicate_field"]
        assert path.read_text() == original

    def test_format_reads_profile_and_explicit_options_win(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text(
            "@comment{pynakes-meta:\n"
            "format-indent: 4\n"
            "format-field-order: alphabetical\n"
            "format-block-order: preserve\n"
            "}\n"
            "@misc{B, zeta={Z}, alpha={A}}\n"
        )
        result = runner.invoke(
            app,
            ["format", str(path), "--indent", "\t", "--field-order", "preserve"],
        )
        assert result.exit_code == 0, result.output
        output = path.read_text()
        assert "\tzeta = {Z}," in output
        assert output.index("zeta =") < output.index("alpha =")

    def test_stdin_stdout_bypasses_lone_bib_autodiscovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        Path("local.bib").write_text("@article{Local, title={Local}}\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["format", "-", "--stdout"],
            input='@article{Pipe, month = jan, title="Quoted"}\n',
        )
        assert result.exit_code == 0, result.output
        assert "@article{Pipe," in result.output
        assert "month = jan," in result.output
        assert 'title = "Quoted",' in result.output

    def test_stdin_without_stdout_is_structured_error(self) -> None:
        result = runner.invoke(app, ["format", "-", "--json"], input="@article{A}\n")
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "error"
        assert payload["error"] == "InvalidInput"

    def test_check_envelope_distinguishes_dirty_from_error(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{A,title={T}}\n")
        result = runner.invoke(app, ["format", str(path), "--check", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "success"
        assert payload["modified"] is True
        assert {"action", "file", "dry_run", "modified_entries", "warnings"} <= payload.keys()

        runner.invoke(app, ["format", str(path)])
        clean = runner.invoke(app, ["format", str(path), "--check", "--json"])
        assert clean.exit_code == 0, clean.output
        assert json.loads(clean.output)["modified"] is False

    def test_check_passes_on_jabref_spelled_types_under_preserve(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@Article{A,\n  title = {T},\n}\n")

        assert runner.invoke(app, ["format", str(path), "--check"]).exit_code == 1
        flag = runner.invoke(app, ["format", str(path), "--check", "--entry-type-case", "preserve"])
        assert flag.exit_code == 0, flag.output

        path.write_text(
            "@comment{pynakes-meta: format-entry-type-case: preserve;}\n\n"
            "@Article{A,\n  title = {T},\n}\n"
        )
        runner.invoke(app, ["format", str(path)])
        assert "@Article{A," in path.read_text()
        clean = runner.invoke(app, ["format", str(path), "--check"])
        assert clean.exit_code == 0, clean.output
        lowered = runner.invoke(app, ["format", str(path), "--entry-type-case", "lower"])
        assert lowered.exit_code == 0, lowered.output
        assert "@article{A," in path.read_text()

    def test_check_ignores_content_normalization_deviations(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text(
            "@article{A,\n  author = {John Smith},\n  doi = {https://doi.org/10.1000/ABC},\n}\n"
        )
        result = runner.invoke(app, ["format", str(path), "--check", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["modified"] is False

    def test_flags_configure_layout(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{A, year={2020}, title={T}}\n")
        result = runner.invoke(
            app,
            ["format", str(path), "--indent", "\t", "--field-order", "preserve"],
        )
        assert result.exit_code == 0, result.output
        output = path.read_text()
        assert "\tyear = {2020}," in output
        assert output.index("year") < output.index("title")

    def test_recursive_applies_flags_skips_hidden_and_exits_on_error(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested"
        hidden = tmp_path / ".hidden"
        nested.mkdir()
        hidden.mkdir()
        (tmp_path / "one.bib").write_text("@article{A,title={A}}\n")
        (nested / "two.bib").write_text("@article{B,title={B}}\n")
        hidden_path = hidden / "ignored.bib"
        hidden_path.write_text("@article{H,title={H}}\n")
        result = runner.invoke(app, ["format", str(tmp_path), "--recursive", "--indent", "\t"])
        assert result.exit_code == 0, result.output
        assert "\ttitle" in (tmp_path / "one.bib").read_text()
        assert "\ttitle" in (nested / "two.bib").read_text()
        assert hidden_path.read_text() == "@article{H,title={H}}\n"

        (nested / "broken.bib").write_text("@article{")
        failed = runner.invoke(app, ["format", str(tmp_path), "--recursive", "--json"])
        assert failed.exit_code == 1
        assert json.loads(failed.output)["status"] == "error"

    def test_where_reformats_only_matching_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text(
            "@book{Newton1687,\n"
            "    title={Principia},\n"
            "      author = {Newton, Isaac},\n"
            "  year={1687},\n"
            "}\n\n"
            "@article{Euler1748,\n"
            "   title={Introductio},   year={1748}\n"
            "}\n"
        )

        result = runner.invoke(app, ["format", str(path), "--where", "type = book", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["where"] == "type = book"
        assert payload["modified_entries"] == 1
        output = path.read_text()
        # The selected entry is canonical; the untouched one is byte-identical.
        assert "@book{Newton1687,\n  author = {Newton, Isaac},\n  title = {Principia},\n" in output
        assert "   title={Introductio},   year={1748}\n" in output

    def test_where_selection_reports_no_change_when_already_formatted(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{A,\n  title = {T},\n}\n\n@misc{B,title={T}}\n")

        check = runner.invoke(app, ["format", str(path), "--where", "key = A", "--check", "--json"])

        assert check.exit_code == 0, check.output
        payload = json.loads(check.output)
        assert payload["modified"] is False
        assert payload["message"] == "Selected entries are already formatted"

    def test_where_rejects_whole_file_layout_options(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{A,title={T}}\n")

        result = runner.invoke(
            app,
            ["format", str(path), "--where", "type = article", "--entry-order", "key", "--json"],
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "InvalidInput"
        assert "--entry-order" in payload["message"]
        assert path.read_text() == "@article{A,title={T}}\n"

    def test_where_expression_error_is_structured(self, tmp_path: Path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{A,title={T}}\n")

        result = runner.invoke(app, ["format", str(path), "--where", "type ==", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "InvalidInput"
        assert path.read_text() == "@article{A,title={T}}\n"


def test_verb_past_tense_handles_verbs_not_ending_in_e() -> None:
    from pynakes.cli_common import RunParams, _verb

    params = RunParams(dry_run=False, diff=False, json_output=False, backup=False)
    # Trailing "e" takes "d"; otherwise "ed" is appended (the former "add" →
    # "Addd" / "convert" → "Convertd" bug).
    assert _verb("rename", params) == "Renamed"
    assert _verb("add", params) == "Added"
    assert _verb("convert", params) == "Converted"
    assert _verb("repair", params) == "Repaired"
    assert _verb("link", params) == "Linked"
    # Explicit past wins for irregular/doubled forms; dry-run reads as "Would …".
    assert _verb("tag", params, "Tagged") == "Tagged"
    assert _verb("add", RunParams(dry_run=True, diff=False, json_output=False, backup=False)) == (
        "Would add"
    )


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

    def test_report_json_locates_every_citation(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Smith2020,\n  title = {T}\n}\n@article{Unused2019,\n  title = {U}\n}\n"
        )
        tex = tmp_path / "paper.tex"
        tex.write_text(
            "Intro.\n"
            r"See~\cite{Smith2020} and \citep{Missing2099}." + "\n"
            r"Again \cite{Smith2020}." + "\n"
        )

        result = runner.invoke(app, ["tex", "scan", str(bib), str(tex), "--json"])

        assert result.exit_code == 0, result.output
        usages = json.loads(result.output)["report"]["usages"]
        # Every cited key is located, including one no entry declares — the
        # client turns that into "undefined citation" without scanning itself.
        assert sorted(usages) == ["Missing2099", "Smith2020"]
        assert [(m["line"], m["column"], m["macro"]) for m in usages["Smith2020"]] == [
            (2, 5, "cite"),
            (3, 7, "cite"),
        ]
        assert usages["Smith2020"][0]["path"] == str(tex)
        # An entry cited nowhere has no occurrences at all.
        assert "Unused2019" not in usages

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

    def test_used_warns_on_missing_tex_source(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex,missing.tex;}\n"
            "@article{Smith2020,\n  title = {T}\n}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["tex", "scan", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        missing = [w for w in data["warnings"] if w["type"] == "missing_tex_source"]
        assert len(missing) == 1
        assert missing[0]["path"].endswith("missing.tex")
        assert data["report"]["used"] == ["Smith2020"]


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

    def test_inspect_json_omits_display_by_default(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["inspect", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert all("display" not in e for e in data["entries"])

    def test_inspect_json_display_cleans_titles_and_splits_names(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n"
            "  title   = {The {DNA} Helix},\n"
            "  author  = {Watson, James and {Crick and Sons}},\n"
            "  year    = {1953}\n"
            "}\n"
        )
        result = runner.invoke(app, ["inspect", str(bib), "--display", "--json"])
        assert result.exit_code == 0, result.output
        entry = json.loads(result.output)["entries"][0]
        # A brace-protected "and" inside a name must survive the split, then
        # lose its braces only once cleaned as its own name.
        assert entry["display"]["title"] == "The DNA Helix"
        assert entry["display"]["author"] == ["Watson, James", "Crick and Sons"]

    def test_inspect_json_display_uses_resolved_fields_when_both_given(
        self, tmp_path: Path
    ) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@proceedings{p, title = {The {Proc}eedings}, year = {2020}}\n\n"
            "@inproceedings{c, crossref = {p}, title = {Paper}, author = {A, B}}\n"
        )
        result = runner.invoke(app, ["inspect", str(bib), "--resolved", "--display", "--json"])
        assert result.exit_code == 0, result.output
        child = next(e for e in json.loads(result.output)["entries"] if e["key"] == "c")
        # booktitle only exists on the resolved view; display must clean that
        # inherited value, not silently fall back to the entry's own fields.
        assert child["display"]["booktitle"] == "The Proceedings"

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
            "pinax-files-dir:\n"
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
        assert data["summary"]["errors"] >= 1
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
        assert data["summary"]["errors"] == 1
        assert data["issues"][-1] == {
            "type": "undefined_string_reference",
            "severity": "error",
            "category": "correctness",
            "fixer": None,
            "message": "Entry 'A' field 'month' references undefined BibTeX string name 'june'",
            "key": "A",
            "field": "month",
            "line": 1,
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

    _NEWTON = (
        "@article{Newton1687,\n"
        "  author = {Newton, Isaac},\n"
        "  title = {Philosophiae Naturalis Principia Mathematica},\n"
        "  journal = {Royal Society},\n"
        "  year = {1687}\n"
        "}\n"
    )

    def test_lint_ignore_leaves_out_a_type_or_category_and_counts_it(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self._NEWTON)

        for name in ("missing_doi", "consistency"):
            result = runner.invoke(app, ["lint", str(bib), "--ignore", name, "--json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert all(issue["type"] != "missing_doi" for issue in payload["issues"])
            assert payload["summary"]["suppressed"] >= 1

        plain = json.loads(runner.invoke(app, ["lint", str(bib), "--json"]).output)
        assert plain["summary"]["suppressed"] == 0
        human = runner.invoke(app, ["lint", str(bib), "--ignore", "missing_doi"])
        assert "suppressed" in human.output

    def test_lint_ignore_setting_lets_a_strict_gate_pass(self, tmp_path: Path) -> None:
        # A profile-required field the venue never assigns fails --strict; the
        # library can accept that once, and a commit hook then passes.
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{pynakes-meta: lint-required-fields: volume;}\n\n" + self._NEWTON)
        assert runner.invoke(app, ["lint", str(bib), "--strict"]).exit_code == 1

        bib.write_text(
            "@comment{pynakes-meta:\n"
            "lint-required-fields: volume\n"
            "lint-ignore: missing_profile_required_field, missing_doi\n"
            "}\n\n" + self._NEWTON
        )
        result = runner.invoke(app, ["lint", str(bib), "--strict", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["summary"]["suppressed"] == 2

    def test_lint_ignore_refuses_an_unknown_name(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self._NEWTON)

        result = runner.invoke(app, ["lint", str(bib), "--ignore", "missing_dio", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "InvalidInput"
        assert "missing_dio" in payload["message"]

    def test_lint_ignore_totals_suppressed_across_files(self, tmp_path: Path) -> None:
        first, second = tmp_path / "a.bib", tmp_path / "b.bib"
        first.write_text(self._NEWTON)
        second.write_text(self._NEWTON)

        result = runner.invoke(
            app, ["lint", str(first), str(second), "--ignore", "missing_doi", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["summary"]["suppressed"] == 2

    def test_lint_strict_fails_on_metadata_drift(self, tmp_path: Path) -> None:
        # A typo'd stored metadata value is stored-profile drift: advisory in
        # interactive lint, but a failed conformance gate under --strict.
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: pinax-fetch-policy:bestpdf,unfamiliar;}\n\n"
            "@article{A,\n"
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
            issue["type"] == "invalid_metadata_value"
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

    def test_search_empty_query_selects_by_where_alone(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Graph Widgets},\n"
            "  doi = {10.1000/alpha},\n"
            "  year = {2024}\n"
            "}\n\n"
            "@book{Beta2023,\n"
            "  title = {Manual Widgets},\n"
            "  year = {2023}\n"
            "}\n"
        )

        result = runner.invoke(app, ["search", "", str(bib), "--where", "doi missing", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [match["key"] for match in data["matches"]] == ["Beta2023"]
        assert data["query"] == ""
        assert data["matches"][0]["matched_fields"] == []
        # Ranking is reported honestly: there are no terms to rank by.
        assert data["ranked"] is False

    def test_search_empty_query_without_where_is_structured(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", "", str(bib), "--json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert "query or a where predicate" in data["message"]

    def test_search_predicate_only_human_output_omits_the_match_tag(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", "", str(bib), "--where", "doi missing"])

        assert result.exit_code == 0, result.output
        assert "@misc{Alpha} — Plain Widget Note" in result.output
        # No matched fields means no empty bracket pair.
        assert "[]" not in result.output

    def test_search_human_output_is_clean(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", "widget", str(bib)])

        assert result.exit_code == 0, result.output
        assert "1 matching entry" in result.output
        assert "@misc{Alpha}" in result.output

    def test_search_show_abstract_adds_an_excerpt_per_hit(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Widgets in Practice},\n"
            "  abstract = {A study of widgets\n    across many libraries.}\n"
            "}\n\n"
            "@book{Beta2023,\n"
            "  title = {More Widgets}\n"
            "}\n"
        )

        result = runner.invoke(app, ["search", "widgets", str(bib), "--show-abstract"])

        assert result.exit_code == 0, result.output
        assert "A study of widgets across many libraries." in result.output
        assert "(no abstract)" in result.output

    def test_search_show_abstract_survives_a_field_restriction(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Widgets in Practice},\n"
            "  abstract = {Restricted output still carries this.}\n"
            "}\n"
        )

        options = ["--in-field", "title", "--abstract", "--json"]
        reported = runner.invoke(app, ["search", str(bib), "widgets", *options])
        # A term that only occurs in the abstract still does not match, so
        # reporting the field has not widened the search.
        searched = runner.invoke(app, ["search", str(bib), "restricted", *options])

        assert reported.exit_code == 0, reported.output
        data = json.loads(reported.output)
        assert data["abstract"] is True
        assert data["in_fields"] == ["title"]
        assert data["matches"][0]["fields"]["abstract"] == "Restricted output still carries this."
        assert data["matches"][0]["matched_fields"] == ["title"]
        assert searched.exit_code == 0, searched.output
        assert json.loads(searched.output)["count"] == 0

    def test_search_ranks_by_match_strength_by_default(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Small Libraries},\n"
            "  groups = {widgets}\n"
            "}\n\n"
            "@misc{widgets_2022,\n"
            "  title = {An Unrelated Note}\n"
            "}\n"
        )

        result = runner.invoke(app, ["search", "widgets", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ranked"] is True
        assert [match["key"] for match in data["matches"]] == ["widgets_2022", "Alpha2024"]

    def test_search_no_rank_keeps_file_order(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n"
            "  title = {Small Libraries},\n"
            "  groups = {widgets}\n"
            "}\n\n"
            "@misc{widgets_2022,\n"
            "  title = {An Unrelated Note}\n"
            "}\n"
        )

        result = runner.invoke(app, ["search", "widgets", str(bib), "--no-rank", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ranked"] is False
        assert [match["key"] for match in data["matches"]] == ["Alpha2024", "widgets_2022"]

    def test_search_invalid_query_is_structured(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Plain Widget Note}\n}\n")

        result = runner.invoke(app, ["search", '"unterminated', str(bib), "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["error"] == "InvalidInput"

    def test_search_composed_where_covers_ranges_and_missing_fields(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Alpha2024,\n  title = {Widgets}, year = {2024}\n}\n\n"
            "@article{Beta2019,\n  title = {Widgets}, year = {2019}, doi = {10.0/b}\n}\n\n"
            "@article{Gamma2025,\n  title = {Widgets}, year = {2025}, doi = {10.0/g}\n}\n"
        )

        result = runner.invoke(
            app,
            [
                "search",
                "widgets",
                str(bib),
                "--where",
                "year >= 2020 and doi missing",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [match["key"] for match in data["matches"]] == ["Alpha2024"]
        assert data["where_parsed"] == {
            "and": [
                {"field": "year", "op": ">=", "value": "2020"},
                {"field": "doi", "op": "missing"},
            ]
        }

    def test_search_fuzzy_reports_explained_matches(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Neural Widgets for Small Libraries}\n}\n")

        strict = runner.invoke(app, ["search", "nueral widgts", str(bib), "--json"])
        assert json.loads(strict.output)["count"] == 0

        result = runner.invoke(app, ["search", "nueral widgts", str(bib), "--fuzzy", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fuzzy"] is True
        match = data["matches"][0]
        assert match["key"] == "Alpha"
        assert {hit["kind"] for hit in match["matches"]} == {"fuzzy"}
        assert all(hit["field"] == "title" for hit in match["matches"])
        assert 0.8 <= match["score"] < 1.0

    def test_search_fuzzy_human_output_shows_the_score(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@misc{Alpha,\n  title = {Neural Widgets for Small Libraries}\n}\n")

        result = runner.invoke(app, ["search", "nueral", str(bib), "--fuzzy"])

        assert result.exit_code == 0, result.output
        assert "[title, ~0." in result.output


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
        bib.write_text(
            "@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
        )

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
        bib.write_text(
            "@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
        )

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
        bib.write_text(
            "@article{A,\n  title = {T}\n}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
        )

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

    def _stub_provider(self, monkeypatch, known: dict[str, str]) -> None:
        """Resolve only the DOIs in ``known``; anything else does not exist."""

        def fetch(doi: str) -> str:
            if doi not in known:
                raise importer_ops.ReferenceImportError(f"DOI not found: {doi}")
            return known[doi]

        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", fetch)

    def _record(self, key: str, doi: str, title: str) -> str:
        """One provider-shaped BibTeX record."""
        return (
            f"@article{{{key},\n"
            f"  author = {{Ada Lovelace}},\n"
            f"  title = {{{title}}},\n"
            f"  journal = {{Notes}},\n"
            f"  year = {{1843}},\n"
            f"  doi = {{{doi}}}\n"
            f"}}\n"
        )

    def test_several_identifiers_import_in_one_write(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        self._stub_provider(
            monkeypatch,
            {
                "10.5555/one": self._record("P1", "10.5555/one", "First Work"),
                "10.5555/two": self._record("P2", "10.5555/two", "Second Work"),
            },
        )

        result = runner.invoke(
            app,
            ["ref", "import", "10.5555/one", "10.5555/two", str(bib), "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["requested"] == 2
        assert data["imported"] == 2
        assert [entry["status"] for entry in data["results"]] == ["imported", "imported"]
        text = bib.read_text()
        assert "10.5555/one" in text
        assert "10.5555/two" in text

    def test_one_unresolvable_identifier_does_not_lose_the_others(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A list an assistant produced routinely names a work that does not exist."""
        bib = _copy(tmp_path, "simple.bib")
        self._stub_provider(
            monkeypatch, {"10.5555/real": self._record("P1", "10.5555/real", "A Real Work")}
        )

        result = runner.invoke(
            app,
            ["ref", "import", "10.5555/real", "10.5555/invented", str(bib), "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["imported"] == 1
        assert data["failed"] == 1
        failed = next(entry for entry in data["results"] if entry["status"] == "failed")
        assert failed["identifier"] == "10.5555/invented"
        assert "10.5555/real" in bib.read_text()

    def test_no_identifier_resolving_is_an_error_and_writes_nothing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        self._stub_provider(monkeypatch, {})

        result = runner.invoke(app, ["ref", "import", "10.5555/a", "10.5555/b", str(bib), "--json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["error"] == "ReferenceImportError"
        assert len(data["results"]) == 2
        assert bib.read_text() == original

    def test_an_already_present_reference_is_skipped_not_a_conflict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Exit 2 is for a question only the caller can answer; here the rest
        of the list still has to resolve."""
        bib = _copy(tmp_path, "simple.bib")
        self._stub_provider(
            monkeypatch,
            {
                "10.1234/nature.ml.2020": self._record(
                    "Dup", "10.1234/nature.ml.2020", "Already Here"
                ),
                "10.5555/new": self._record("P1", "10.5555/new", "Brand New"),
            },
        )

        result = runner.invoke(
            app,
            ["ref", "import", "10.1234/nature.ml.2020", "10.5555/new", str(bib), "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["imported"] == 1
        assert data["skipped"] == 1
        skipped = next(entry for entry in data["results"] if entry["status"] == "skipped")
        assert skipped["existing_keys"] == ["Smith2020"]

    def test_identifiers_can_be_piped_one_per_line(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        self._stub_provider(
            monkeypatch,
            {
                "10.5555/one": self._record("P1", "10.5555/one", "First Work"),
                "10.5555/two": self._record("P2", "10.5555/two", "Second Work"),
            },
        )

        result = runner.invoke(
            app,
            ["ref", "import", "-", str(bib), "--json"],
            input="# pasted from a chat\n10.5555/one\n\n  10.5555/two  \n",
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["imported"] == 2

    def test_key_is_refused_for_several_identifiers(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "import", "10.5555/a", "10.5555/b", str(bib), "--key", "Mine", "--json"]
        )

        assert result.exit_code == 1
        assert "--key" in json.loads(result.output)["message"]

    def test_library_can_be_given_with_file_option(self, tmp_path: Path, monkeypatch) -> None:
        bib = _copy(tmp_path, "simple.bib")
        self._stub_provider(
            monkeypatch, {"10.5555/one": self._record("P1", "10.5555/one", "First Work")}
        )

        result = runner.invoke(app, ["ref", "import", "10.5555/one", "--file", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        assert "10.5555/one" in bib.read_text()

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

    def test_add_repository_identifier_uses_registered_provider(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bib = _copy(tmp_path, "simple.bib")
        monkeypatch.setattr(
            ssrn,
            "fetch_metadata",
            lambda identifier, **kwargs: ReferenceMetadata(
                provider="SSRN",
                entry_type="techreport",
                fields={
                    "author": "Alan Turing",
                    "title": "On Computable Numbers",
                    "year": "1936",
                    "ssrn": identifier,
                    "doi": "10.5555/archive.1",
                },
                identifiers={"ssrn": identifier, "doi": "10.5555/archive.1"},
            ),
        )

        result = runner.invoke(app, ["ref", "import", "SSRN:123456", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["identifier_type"] == "ssrn"
        assert data["identifier"] == "123456"
        assert data["doi"] == "10.5555/archive.1"
        assert "ssrn = {123456}" in bib.read_text()

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
        assert data["fetch"]["fetch_policy"] == {
            "preprint": False,
            "published": False,
            "source": False,
            "supplement": False,
            "bestpdf": True,
        }
        assert (tmp_path / "refs.files" / f"{key}.preprint.pdf").read_bytes() == b"%PDF fixture"
        assert not (tmp_path / "refs.files" / f"{key}.source").exists()
        assert "pinax-files-dir: refs.files" in bib.read_text()

    def test_add_fetch_honors_fetch_source_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@comment{pynakes-meta:\npinax-fetch-policy: preprint\n}\n")
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
        assert data["fetch"]["fetch_policy"] == {
            "preprint": True,
            "published": False,
            "source": False,
            "supplement": False,
            "bestpdf": False,
        }
        assert fetched["pdf_path"] == str(tmp_path / "refs.files" / f"{key}.preprint.pdf")
        assert fetched["source_path"] is None
        assert not (tmp_path / "refs.files" / f"{key}.source").exists()

    def test_import_fetch_reuses_published_fetch_path(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        cache = tmp_path / "provider-cache"
        bib.write_text("@comment{pynakes-meta:\npinax-fetch-policy: published\n}\n")
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        monkeypatch.setattr(
            "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi",
            lambda doi, **kwargs: "https://example.com/provider.pdf",
        )
        monkeypatch.setattr(
            "pynakes.fetch.fetch_published_pdf", lambda url, **kwargs: b"%PDF published"
        )
        monkeypatch.setattr("pynakes.fetch._url_serves_pdf", lambda url: True)

        result = runner.invoke(
            app,
            [
                "ref",
                "import",
                "10.5555/provider",
                str(bib),
                "--fetch",
                "--cache-file",
                str(cache),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        key = data["key"]
        assert data["fetch"]["fetch_policy"] == {
            "preprint": False,
            "published": True,
            "source": False,
            "supplement": False,
            "bestpdf": False,
        }
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

    def test_add_uses_jabref_key_pattern_metadata(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
        )
        monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: self.provider_bibtex)

        result = runner.invoke(app, ["ref", "import", "10.5555/provider", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["key"] == "smith24practical"
        assert data["key_source"] == "generated"
        assert "@article{smith24practical," in bib.read_text()

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
            ["ref", "import", str(bib), "10.5555/provider", "--key-source", "garbage", "--json"],
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "UsageError"

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
        assert data["action"] == "ref_add"
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

    def test_add_manual_entry_reports_an_existing_key_as_a_conflict(self, tmp_path: Path) -> None:
        """A taken key is the caller's decision, and `ref import` already says so."""
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()

        result = runner.invoke(
            app, ["ref", "add", "Smith2020", str(bib), "--field", "title=X", "--json"]
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "CitationKeyConflict"
        assert data["key"] == "Smith2020"
        assert {option["id"] for option in data["options"]} == {"choose_key", "allow_duplicate"}
        assert bib.read_text() == original

    def test_add_manual_entry_honours_the_conflict_option_it_offers(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            [
                "ref",
                "add",
                "Smith2020",
                str(bib),
                "--field",
                "title=X",
                "--allow-duplicate",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        # Duplicate citation keys are tolerated, not an error: the option the
        # conflict offered does exactly what it says.
        assert bib.read_text().count("@article{Smith2020,") == 2

    def test_add_manual_entry_rejects_bad_field_assignment(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "add", "Manual2026", str(bib), "--field", "title", "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "InvalidInput"

    def test_add_stub_entry_warns_about_missing_required_fields(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("")

        result = runner.invoke(app, ["ref", "add", str(bib), "Stub2026", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["warnings"], "expected a missing-required-field warning"
        warning = data["warnings"][0]
        assert warning["type"] == "missing_required_fields"
        assert "Stub2026" in warning["message"]
        assert "author" in warning["fields"] and "title" in warning["fields"]
        # The entry is still created.
        assert "@article{Stub2026," in bib.read_text()

    def test_add_complete_entry_has_no_warning(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("")

        result = runner.invoke(
            app,
            [
                "ref",
                "add",
                str(bib),
                "Curie1911",
                "--field",
                "author=Marie Curie",
                "--field",
                "title=Radioactive Substances",
                "--field",
                "journal=Le Radium",
                "--field",
                "year=1911",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["warnings"] == []


class TestReferenceCrud:
    def test_show_one_reference_json(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "show", "Smith2020", str(bib), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "ref_show"
        assert data["key"] == "Smith2020"
        assert data["entry_type"] == "article"
        assert data["fields"]["title"] == "A Comprehensive Study on Machine Learning"

    def test_show_one_reference_human_output_lists_every_field(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(app, ["ref", "show", "Smith2020", str(bib)])

        assert result.exit_code == 0, result.output
        assert "@article{Smith2020}" in result.output
        assert "  pages = 123--145" in result.output
        assert "  doi = 10.1234/nature.ml.2020" in result.output

    def test_show_summarizes_several_keys_in_one_call(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "show", "--keys", "Brown2022,Smith2020", str(bib), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["action"] == "ref_show"
        assert data["count"] == 2
        # Requested order is preserved rather than file order.
        assert [entry["key"] for entry in data["entries"]] == ["Brown2022", "Smith2020"]
        assert data["entries"][0]["entry_type"] == "inproceedings"
        assert data["entries"][0]["summary"]["booktitle"] == "Proceedings of ICML 2022"
        # The summary is compact: stored fields outside it are not reported.
        assert "pages" not in data["entries"][0]["summary"]
        assert "abstract" not in data["entries"][1]["summary"]

    def test_show_keys_accepts_repeated_options_and_drops_repeats(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app,
            [
                "ref",
                "show",
                "--keys",
                "Smith2020, Jones2021",
                "--keys",
                "Smith2020",
                str(bib),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["keys"] == ["Smith2020", "Jones2021"]
        assert data["count"] == 2

    def test_show_keys_abstract_distinguishes_empty_from_unrequested(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Fermi1934,\n"
            "  title = {Versuch einer Theorie der Betastrahlen},\n"
            "  abstract = {An attempt at a quantitative\n    theory of beta decay.}\n"
            "}\n\n"
            "@article{Noether1918,\n"
            "  title = {Invariante Variationsprobleme}\n"
            "}\n",
            encoding="utf-8",
            newline="",
        )

        result = runner.invoke(
            app,
            ["ref", "show", "--keys", "Fermi1934,Noether1918", str(bib), "--abstract", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["abstract"] is True
        assert data["entries"][0]["summary"]["abstract"] == (
            "An attempt at a quantitative\n    theory of beta decay."
        )
        assert data["entries"][1]["summary"]["abstract"] is None

    def test_show_keys_human_output_is_scannable(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(app, ["ref", "show", "--keys", "Smith2020,Green2023", str(bib)])

        assert result.exit_code == 0, result.output
        assert "2 entries." in result.output
        assert "@article{Smith2020}" in result.output
        assert "@phdthesis{Green2023}" in result.output
        assert "Quantum Computing Algorithms" in result.output

    def test_show_keys_reports_every_unknown_key_at_once(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        result = runner.invoke(
            app, ["ref", "show", "--keys", "Smith2020,Ghost,Phantom", str(bib), "--json"]
        )

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["error"] == "KeyNotFound"
        assert data["keys"] == ["Ghost", "Phantom"]

    def test_show_keys_conflicts_on_a_duplicated_key(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "duplicate_entries.bib")

        result = runner.invoke(app, ["ref", "show", "--keys", "Smith2020", str(bib), "--json"])

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["status"] == "conflict"
        assert data["error"] == "DuplicateCitationKey"
        assert data["keys"] == ["Smith2020"]
        assert [option["id"] for option in data["options"]] == [
            "repair_duplicates",
            "inspect_all",
        ]

    def test_show_keys_resolves_inherited_fields(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@book{Collection,\n"
            "  title = {A Collected Volume},\n"
            "  publisher = {Example Press},\n"
            "  year = {1900}\n"
            "}\n\n"
            "@inbook{Chapter,\n"
            "  crossref = {Collection},\n"
            "  title = {A Single Chapter}\n"
            "}\n"
        )

        plain = runner.invoke(app, ["ref", "show", "--keys", "Chapter", str(bib), "--json"])
        inherited = runner.invoke(
            app, ["ref", "show", "--keys", "Chapter", str(bib), "--resolved", "--json"]
        )

        assert plain.exit_code == 0, plain.output
        assert inherited.exit_code == 0, inherited.output
        assert "year" not in json.loads(plain.output)["entries"][0]["summary"]
        assert json.loads(inherited.output)["entries"][0]["summary"]["year"] == "1900"

    def test_show_rejects_conflicting_and_missing_key_selections(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")

        both = runner.invoke(
            app, ["ref", "show", "Smith2020", str(bib), "--keys", "Jones2021", "--json"]
        )
        empty = runner.invoke(app, ["ref", "show", str(bib), "--keys", "", "--json"])
        nothing = runner.invoke(app, ["ref", "show", "--json"])
        stray_abstract = runner.invoke(
            app, ["ref", "show", "Smith2020", str(bib), "--abstract", "--json"]
        )

        for result in (both, empty, nothing, stray_abstract):
            assert result.exit_code == 1, result.output
            assert json.loads(result.output)["error"] == "InvalidInput"

    def test_edit_patches_fields_and_type_in_one_transaction(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            [
                "ref",
                "edit",
                "Smith2020",
                str(bib),
                "--field",
                "title=Replacement Title",
                "--field",
                "year=2025",
                "--clear-field",
                "doi",
                "--type",
                "online",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "ref_edit"
        assert data["modified_entries"] == 1
        text = bib.read_text()
        assert "@online{Smith2020," in text
        assert "title = {Replacement Title}" in text
        assert "year = {2025}" in text
        assert "doi =" not in text.split("@article{Jones2021", 1)[0]

    def test_edit_requires_changes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "edit", "Smith2020", str(bib), "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error"] == "InvalidInput"

    def test_remove_deletes_entry_without_doubling_blank_lines(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n  title = {One}\n}\n\n"
            "@article{B,\n  title = {Two}\n}\n\n"
            "@article{C,\n  title = {Three}\n}\n"
        )

        result = runner.invoke(app, ["ref", "remove", str(bib), "B", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["removed_keys"] == ["B"]
        assert bib.read_text() == (
            "@article{A,\n  title = {One}\n}\n\n@article{C,\n  title = {Three}\n}\n"
        )

    def test_remove_does_not_back_up_by_default(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "remove", str(bib), "Smith2020", "--json"])
        assert result.exit_code == 0, result.output
        assert not Path(f"{bib}.bak").exists()

    def test_remove_reports_pinax_material_policy(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Noether1918, title = {Invariant Variational Problems}}\n"
            "@article{Einstein1905, title = {On the Electrodynamics of Moving Bodies}}\n"
            "@comment{pynakes-meta:\npinax-files-dir: refs.files\n}\n"
        )
        files = tmp_path / "refs.files"
        files.mkdir()
        noether_pdf = files / "Noether1918.preprint.pdf"
        einstein_pdf = files / "Einstein1905.preprint.pdf"
        noether_pdf.write_bytes(b"%PDF fixture")
        einstein_pdf.write_bytes(b"%PDF fixture")

        preview = runner.invoke(
            app, ["ref", "remove", str(bib), "Noether1918", "--dry-run", "--json"]
        )
        assert preview.exit_code == 0, preview.output
        assert json.loads(preview.output)["material_removals"] == {
            "Noether1918": ["Noether1918.preprint.pdf"]
        }
        assert noether_pdf.exists()

        removed = runner.invoke(app, ["ref", "remove", str(bib), "Noether1918"])
        assert removed.exit_code == 0, removed.output
        assert "Removed Pinax materials" in removed.output
        assert not noether_pdf.exists()

        kept = runner.invoke(app, ["ref", "remove", str(bib), "Einstein1905", "--keep-files"])
        assert kept.exit_code == 0, kept.output
        assert "Kept Pinax materials" in kept.output
        assert einstein_pdf.exists()

    @pytest.mark.parametrize("command", ["show", "edit"])
    def test_duplicate_key_is_a_conflict(self, tmp_path: Path, command: str) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A, title={One}}\n@article{A, title={Two}}\n")
        args = ["ref", command, "A", str(bib), "--json"]
        if command == "edit":
            args.extend(["--field", "year=2025"])
        result = runner.invoke(app, args)
        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["error"] == "DuplicateCitationKey"
        assert data["options"]


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
        # With a tree present, the CLI returns tree node names (flat format
        # uses escaped colons, so "Machine Learning:AI Papers" is one node).
        assert "Machine Learning:AI Papers" in groups

    def test_list_auto_discovers_lone_bib_file(self, tmp_path: Path, monkeypatch) -> None:
        _copy(tmp_path, "jabref_groups.bib")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["groups", "list", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "refs.bib"
        assert "Machine Learning:AI Papers" in data["groups"]

    def test_add_entry_dry_run_does_not_write(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        original = bib.read_text()
        result = runner.invoke(
            app, ["groups", "add-entry", str(bib), "Smith2020", "Fav", "--create", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert bib.read_text() == original

    def test_add_entry_writes(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["groups", "add-entry", str(bib), "Smith2020", "Fav", "--create"]
        )
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

    def test_set_key_completion_does_not_error(self) -> None:
        result = runner.invoke(
            app,
            [],
            env={
                "COMP_WORDS": "pynakes metadata set sort",
                "COMP_CWORD": "3",
                "_PYNAKES_COMPLETE": "complete_bash",
            },
            prog_name="pynakes",
        )

        assert result.exit_code == 0, result.output
        assert "InvalidInput" not in result.output


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
        assert json.loads(result.output)["renames"] == [{"old": "Old", "new": "smith24"}]
        text = bib.read_text()
        assert "@article{smith24," in text
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
            "@article{Smith2020,\n  title = {T}\n}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
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
            "@comment{pynakes-meta:\npinax-files-dir:\n}\n"
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

    def test_rename_without_sources_succeeds_with_warning(self, tmp_path: Path) -> None:
        # A fresh library with no manuscript linked has zero citations to update,
        # so the rename succeeds (0 TeX updates) and warns instead of hard-failing.
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{Smith2020,\n  title = {T}\n}\n")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified"] is True
        assert data["source_occurrences"] == 0
        assert "@article{Smith2020ML," in bib.read_text()
        assert [w for w in data["warnings"] if w["type"] == "no_tex_sources"]

    def test_rename_with_explicit_nontex_source_still_errors(self, tmp_path: Path) -> None:
        # Explicitly pointing at a source that resolves to no .tex files remains an
        # error — only the "no sources configured at all" case is now tolerated.
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{Smith2020,\n  title = {T}\n}\n")
        empty_dir = tmp_path / "manuscript"
        empty_dir.mkdir()

        result = runner.invoke(
            app,
            ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", str(empty_dir), "--json"],
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "NoSources"

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

    def test_generate_warns_on_missing_tex_source(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex,missing.tex;}\n"
            "@article{Old,\n"
            "  author = {Grace Hopper},\n"
            "  year = {1952},\n"
            "  title = {Compiler Methods}\n"
            "}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Old}" "\n")

        result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        missing = [w for w in data["warnings"] if w["type"] == "missing_tex_source"]
        assert len(missing) == 1
        assert missing[0]["path"].endswith("missing.tex")
        assert data["source_occurrences"] == 1

    def test_rename_warns_on_missing_tex_source(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex,missing.tex;}\n"
            "@article{Smith2020,\n  title = {T}\n}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(
            app, ["keys", "rename", str(bib), "Smith2020", "Smith2020ML", "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        missing = [w for w in data["warnings"] if w["type"] == "missing_tex_source"]
        assert len(missing) == 1
        assert missing[0]["path"].endswith("missing.tex")
        assert data["source_occurrences"] == 1

    def test_repair_warns_on_missing_tex_source(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:paper.tex,missing.tex;}\n"
            "@article{Smith2020,\n  title = {A}\n}\n"
            "@article{Smith2020,\n  title = {B}\n}\n"
        )
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["keys", "repair", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        missing = [w for w in data["warnings"] if w["type"] == "missing_tex_source"]
        assert len(missing) == 1
        assert missing[0]["path"].endswith("missing.tex")

    def test_repair_missing_tex_source_is_not_reported_as_ambiguous_citation(
        self, tmp_path: Path
    ) -> None:
        # A missing tex-sources path is a different problem from a citation
        # made ambiguous by the repair; the human summary must not conflate
        # the two counts, and the missing-source message must be visible
        # without needing --json.
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: tex-sources:missing.tex;}\n"
            "@article{Smith2020,\n  title = {A}\n}\n"
            "@article{Smith2020,\n  title = {B}\n}\n"
        )

        result = runner.invoke(app, ["keys", "repair", str(bib), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "not found" in result.output
        assert "now ambiguous" not in result.output


class TestKeysUsageCommand:
    def test_finds_citations_without_a_bib_file(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n" r"\citep{Smith2020,Brown2022}" "\n")

        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--path", str(tex), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["key"] == "Smith2020"
        assert data["count"] == 2
        assert [m["line"] for m in data["matches"]] == [1, 2]
        assert data["matches"][0]["text"] == r"\cite{Smith2020}"
        assert data["matches"][1]["text"] == r"\citep{Smith2020,Brown2022}"

    def test_ignores_commented_out_citations(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text(r"% \cite{Smith2020}" "\n" r"\cite{Brown2022}" "\n")

        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--path", str(tex), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["count"] == 0

    def test_scans_a_directory_recursively(self, tmp_path: Path) -> None:
        sub = tmp_path / "chapters"
        sub.mkdir()
        (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")
        (sub / "intro.tex").write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(
            app, ["keys", "usage", "Smith2020", "--path", str(tmp_path), "--json"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["count"] == 2
        assert len(data["scanned"]) == 2

    def test_does_not_require_tex_sources_metadata_or_registration(self, tmp_path: Path) -> None:
        # A frozen snapshot or generated diff pynakes never tracked via `tex
        # add` must still be scannable directly.
        frozen = tmp_path / "frozen-snapshot.tex"
        frozen.write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--path", str(frozen), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["count"] == 1

    def test_no_matches_reports_zero_count(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Brown2022}" "\n")

        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--path", str(tex), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["count"] == 0
        assert data["matches"] == []

    def test_missing_path_reports_file_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["keys", "usage", "Smith2020", "--path", str(tmp_path / "missing.tex"), "--json"]
        )

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "FileNotFound"

    def test_missing_path_option_is_a_structured_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--json"])

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UsageError"

    def test_invalid_key_is_a_structured_error(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["keys", "usage", "bad key", "--path", str(tex), "--json"])

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "InvalidInput"

    def test_human_output_lists_each_occurrence(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text(r"\cite{Smith2020}" "\n")

        result = runner.invoke(app, ["keys", "usage", "Smith2020", "--path", str(tex)])

        assert result.exit_code == 0, result.output
        assert "paper.tex:1" in result.output
        assert r"\cite{Smith2020}" in result.output


class TestFieldsCommand:
    def test_set_replaces_field_on_matching_references(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            [
                "fields",
                "set",
                str(bib),
                "year",
                "2025",
                "--where",
                'key = "Smith2020"',
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "fields_set"
        assert data["modified_entries"] == 1
        assert bib.read_text().count("year = {2025}") == 1

    def test_set_accepts_a_composed_selector(self, tmp_path: Path) -> None:
        # The bulk-edit selection an agent actually wants: a range plus a
        # missing-field test, in one expression rather than several passes.
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            [
                "fields",
                "set",
                str(bib),
                "note",
                "review",
                "--where",
                "year >= 2021 and doi missing and type in [book, inproceedings]",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified_entries"] == 2
        text = bib.read_text()
        assert text.count("note = {review}") == 2
        assert "note" not in text.split("@book")[0]  # Smith2020 (2020, has a DOI) untouched

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


class TestKeySelector:
    """``--key`` selects by citation key wherever ``--where`` is accepted."""

    def test_key_selects_one_entry_without_the_where_grammar(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "set", str(bib), "note", "checked", "--key", "Smith2020", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified_entries"] == 1
        assert data["keys"] == ["Smith2020"]
        entries = bib.read_text().split("@")
        noted = [entry for entry in entries if "note = {checked}" in entry]
        assert len(noted) == 1
        assert noted[0].startswith("article{Smith2020,")

    def test_key_accepts_several_keys_comma_separated_and_repeated(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            [
                "fields",
                "set",
                str(bib),
                "note",
                "checked",
                "--key",
                "Smith2020,Jones2021",
                "--key",
                "Brown2022",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["modified_entries"] == 3
        assert data["keys"] == ["Smith2020", "Jones2021", "Brown2022"]

    def test_key_and_where_narrow_rather_than_replace(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app,
            [
                "fields",
                "set",
                str(bib),
                "note",
                "checked",
                "--key",
                "Smith2020,Jones2021",
                "--where",
                "type = article",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["modified_entries"] == 1

    def test_key_is_accepted_by_search_and_format_too(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        found = runner.invoke(app, ["search", "", str(bib), "--key", "Jones2021", "--json"])
        assert found.exit_code == 0, found.output
        matches = json.loads(found.output)["matches"]
        assert [match["key"] for match in matches] == ["Jones2021"]

        formatted = runner.invoke(
            app, ["format", str(bib), "--key", "Jones2021", "--dry-run", "--json"]
        )
        assert formatted.exit_code == 0, formatted.output
        assert json.loads(formatted.output)["keys"] == ["Jones2021"]

    def test_unknown_key_selects_nothing_rather_than_erroring(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "set", str(bib), "note", "x", "--key", "Nobody1999", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["modified_entries"] == 0

    def test_key_on_a_command_that_cannot_select_points_at_what_it_takes(
        self, tmp_path: Path
    ) -> None:
        """Click's bare "No such option" left the caller nowhere to go."""
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "edit", str(bib), "--key", "Smith2020", "--json"])
        assert result.exit_code != 0
        assert "positional argument" in result.output

    def test_near_miss_of_the_selector_names_both_selectors(self, tmp_path: Path) -> None:
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(
            app, ["fields", "set", str(bib), "note", "x", "--citekey", "Smith2020", "--json"]
        )
        assert result.exit_code != 0
        assert "--key" in result.output


class TestNormalizeCommand:
    def test_a_step_that_never_ran_reports_off_not_zero(self, tmp_path: Path) -> None:
        """journals=0 read as "checked, nothing to do" when it meant "did not run"."""
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  journal = {Physical Review Letters}\n}\n")

        result = runner.invoke(app, ["normalize", str(bib), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "journals=off" in result.output
        assert "journals=0" not in result.output
        assert "--journal-style" in result.output

    def test_a_step_that_ran_without_changes_still_reports_zero(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  journal = {Phys. Rev. Lett.}\n}\n")

        result = runner.invoke(
            app, ["normalize", str(bib), "--journal-style", "abbreviated", "--dry-run", "--json"]
        )

        assert result.exit_code == 0, result.output
        operations = json.loads(result.output)["operations"]
        assert operations["journals"] == 0
        assert "journals" not in operations["skipped"]

    def test_skipped_steps_carry_their_reason_in_json(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  journal = {Physical Review Letters}\n}\n")

        result = runner.invoke(app, ["normalize", str(bib), "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        skipped = json.loads(result.output)["operations"]["skipped"]
        assert "--journal-style" in skipped["journals"]
        assert "--key-generation" in skipped["keys"]

    def test_normalize_rewrites_a_unicode_en_dash_page_range(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  pages = {2446\u20132449}\n}\n", encoding="utf-8")

        result = runner.invoke(app, ["normalize", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["operations"]["pages"] == 1
        assert "pages = {2446--2449}" in bib.read_text(encoding="utf-8")

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
        bib.write_text(original, encoding="utf-8", newline="")

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

    def test_normalize_drop_field_removes_field_across_library(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {Paper},\n  abstract = {A long summary.}\n}\n")

        result = runner.invoke(app, ["normalize", str(bib), "--drop-field", "abstract", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["dropped_fields"] == 1
        assert "abstract" not in bib.read_text()

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
        assert data["error"] == "UsageError"

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

    def test_normalize_journal_source_none_skips_bundled_data(self, tmp_path: Path) -> None:
        # With the bundled JabRef exact table off, an already-abbreviated
        # value with no user table has nothing to resolve it and is left
        # alone (reported unknown), unlike the "jabref" default.
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {Paper},\n  journal = {Phys. Rev. Lett.}\n}\n")

        result = runner.invoke(
            app,
            [
                "normalize",
                str(bib),
                "--journal-style",
                "abbreviated",
                "--journal-source",
                "none",
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
        assert data["operations"]["journals"] == 0
        assert any(w.get("journal") == "Phys. Rev. Lett." for w in data["warnings"])

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
        assert data["error"] == "UsageError"

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
        assert 'A,article,"Doe, J",T,2020' in result.output
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
        assert 'A,article,"Doe, J",T,2020' in csv_text

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

        result = runner.invoke(app, ["convert", str(src), "--from", "csv", "--json"])

        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["error"] == "UsageError"

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
        # Without --json, humans keep Click's usage text, on stderr, with exit
        # code 1: exit 2 is pynakes's conflict code, never a usage error.
        bib = _copy(tmp_path, "simple.bib")
        result = runner.invoke(app, ["ref", "remove", str(bib)])
        assert result.exit_code == 1
        assert result.stdout == ""
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
            app,
            ["groups", "add-entry", str(bib), "Smith2020", "X", "--create", "--dry-run", "--json"],
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
    (["groups", "add-entry"], ["Smith2020", "Fav", "--create"], "simple.bib"),
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
    """`asset fetch` with `pinax-fetch-policy` metadata."""

    def test_fetch_published_downloads_oa_pdf(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Einstein1905,\n"
            '  title = {Zur Elektrodynamik bewegter K{\\"o}rper},\n'
            "  doi = {10.1002/andp.19053221004}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "pinax-files-dir: refs.files\n"
            "pinax-fetch-policy: published\n"
            "}\n"
        )

        monkeypatch.setattr(
            "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi",
            lambda doi, **kwargs: "https://example.com/paper.pdf",
        )
        monkeypatch.setattr(
            "pynakes.fetch.fetch_published_pdf", lambda url, **kwargs: b"%PDF published"
        )
        monkeypatch.setattr("pynakes.fetch._url_serves_pdf", lambda url: True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetch_policy"] == {
            "preprint": False,
            "published": True,
            "source": False,
            "supplement": False,
            "bestpdf": False,
        }
        assert len(data["fetched"]) == 1
        assert data["fetched"][0]["key"] == "Einstein1905"
        assert data["fetched"][0]["pdf_path"] is not None
        assert (tmp_path / "refs.files" / "Einstein1905.published.pdf").read_bytes() == (
            b"%PDF published"
        )

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
            "pinax-files-dir: refs.files\n"
            "pinax-fetch-policy: published\n"
            "}\n"
        )

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
            "pinax-files-dir: refs.files\n"
            "pinax-fetch-policy: published\n"
            "}\n"
        )

        def fail_resolver(doi: str, **kwargs) -> str | None:
            raise AssertionError("dry-run should not call network")

        monkeypatch.setattr(
            "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi",
            fail_resolver,
        )
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
            "pinax-files-dir: refs.files\n"
            "pinax-fetch-policy: source\n"
            "}\n"
        )

        def fail_resolver(doi: str, **kwargs) -> str | None:
            raise AssertionError("network should not be called")

        monkeypatch.setattr(
            "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi",
            fail_resolver,
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["asset", "fetch", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["fetch_policy"] == {
            "preprint": False,
            "published": False,
            "source": True,
            "supplement": False,
            "bestpdf": False,
        }
        assert len(data["fetched"]) == 0
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "no arXiv id"

    def test_fetch_supplement_with_institutional_access(self, tmp_path: Path, monkeypatch) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Noether1918,\n"
            "  title = {Invariant Variational Problems},\n"
            "  doi = {10.5555/entitled}\n"
            "}\n"
            "@comment{pynakes-meta:\n"
            "pinax-files-dir: refs.files\n"
            "}\n"
        )
        monkeypatch.setattr(
            "pynakes.fetch.publisher_supplement_pdf_urls",
            lambda doi: ("https://publisher.example/supporting-information.pdf",),
        )
        monkeypatch.setattr("pynakes.fetch.fetch_bytes", lambda url, **kwargs: b"%PDF supplement")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            ["asset", "fetch", "--supplement", "--access", "institutional", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["access"] == "institutional"
        assert data["fetch_policy"]["supplement"] is True
        assert data["fetched"][0]["artifact"] == "supplement_pdf"
        assert data["fetched"][0]["access"] == "institutional"
        assert (tmp_path / "refs.files" / "Noether1918.supplement.pdf").read_bytes() == (
            b"%PDF supplement"
        )


class TestAssetFetchLibraryTargeting:
    """Naming the library for a whole-library `asset fetch`."""

    LIB = (
        "@article{Newton1687,\n"
        "  title = {Principia},\n"
        "  eprint = {1234.5678},\n"
        "  archiveprefix = {arXiv}\n"
        "}\n"
        "@comment{pynakes-meta:\n"
        "pinax-files-dir: main.files\n"
        "}\n"
    )

    def _library_pair(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "main.bib").write_text(self.LIB)
        (tmp_path / "other.bib").write_text(self.LIB)
        monkeypatch.chdir(tmp_path)

    def test_file_option_targets_a_library_among_siblings(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # With siblings present, auto-detection cannot decide; --file names one.
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(app, ["asset", "fetch", "--file", "main.bib", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["file"] == "main.bib"
        assert data["dry_run"] is True

    def test_a_lone_library_argument_fetches_the_whole_library(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The library comes first, so naming only it is the whole-library form.
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(app, ["asset", "fetch", "main.bib", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == "main.bib"

    def test_library_given_twice_is_refused(self, tmp_path: Path, monkeypatch) -> None:
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(
            app,
            ["asset", "fetch", "main.bib", "Newton1687", "--file", "other.bib", "--json"],
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "UsageError"
        assert "main.bib looks like a library" in payload["message"]

    def test_blank_key_means_every_entry(self, tmp_path: Path, monkeypatch) -> None:
        # An unset variable in a script ("$KEY") must not become a lookup for
        # the empty citation key.
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(app, ["asset", "fetch", "", "main.bib", "--dry-run", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == "main.bib"

    def test_key_with_positional_library_still_works(self, tmp_path: Path, monkeypatch) -> None:
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(
            app, ["asset", "fetch", "Newton1687", "main.bib", "--dry-run", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["file"] == "main.bib"

    def test_check_accepts_explicit_libraries(self, tmp_path: Path, monkeypatch) -> None:
        # `asset check` takes libraries as variadic positionals, so it never had
        # the targeting gap `fetch` did.
        self._library_pair(tmp_path, monkeypatch)

        result = runner.invoke(app, ["asset", "check", "main.bib", "other.bib", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [item["file"] for item in data["files"]] == ["main.bib", "other.bib"]


class TestLintCategories:
    """`lint` reports which command fixes a finding and can filter by category."""

    MIXED = (
        "@Article{A,\n"
        "  Author = {Jane Doe},\n"
        "  title = {A Study},\n"
        "  journal = {Nature},\n"
        "  YEAR = {2020}\n"
        "}\n"
    )

    def test_json_reports_severity_tiers_and_category_counts(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(app, ["lint", str(bib), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["summary"]["info"] > 0
        assert data["summary"]["by_category"]["formatting"] == 3
        assert set(data["summary"]["by_category"]) >= {"consistency", "formatting"}
        layout = [i for i in data["issues"] if i["category"] == "formatting"]
        assert all(i["severity"] == "info" and i["fixer"] == "format" for i in layout)

    def test_human_output_names_the_fixing_command(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(app, ["lint", str(bib)])

        assert "Run `pynakes format` to resolve 3 of them." in result.output

    def test_key_pattern_hint_enables_key_normalization(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta: key-pattern: [auth]_[year];}\n"
            "@article{Old, author = {Jane Doe}, year = {2024}, title = {Study}}\n"
        )

        result = runner.invoke(app, ["lint", str(bib)])

        assert "Run `pynakes normalize --key-generation on` to resolve 1 of them." in result.output

    def test_key_normalization_stops_with_actionable_error(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        original = (
            "@comment{pynakes-meta:\n"
            "key-pattern: [auth]_[year]\n"
            "tex-sources: missing.tex\n"
            "}\n"
            "@article{Old, author = {Jane Doe}, year = {2024}, title = {Study}}\n"
        )
        bib.write_text(original)

        result = runner.invoke(app, ["normalize", str(bib), "--key-generation", "on", "--json"])

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["error"] == "MissingTexSource"
        assert data["sources"] == [str(tmp_path / "missing.tex")]
        assert "--ignore-missing-tex" in data["message"] + data["hint"]
        assert bib.read_text() == original

    def test_force_key_normalization_skips_missing_tex_sources(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@comment{pynakes-meta:\n"
            "key-pattern: [auth]_[year]\n"
            "tex-sources: missing.tex\n"
            "}\n"
            "@article{Old, author = {Jane Doe}, year = {2024}, title = {Study}}\n"
        )

        result = runner.invoke(
            app,
            ["normalize", str(bib), "--key-generation", "on", "--ignore-missing-tex", "--json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["operations"]["keys"] == 1
        assert data["warnings"][-1] == {
            "type": "missing_tex_source",
            "message": f"TeX source {str(tmp_path / 'missing.tex')!r} not found",
            "path": str(tmp_path / "missing.tex"),
        }
        assert "@article{doe_2024," in bib.read_text()

    def test_category_filter_narrows_the_report(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(app, ["lint", str(bib), "--category", "formatting", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data["summary"]["by_category"]) == {"formatting"}
        assert data["summary"]["issues"] == 3

    def test_layout_category_is_a_deprecated_alias(self, tmp_path: Path) -> None:
        # `layout` was renamed `formatting` in 0.7; the old value still works
        # through 0.7.x with a structured deprecation warning.
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(app, ["lint", str(bib), "--category", "layout", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data["summary"]["by_category"]) == {"formatting"}
        assert data["warnings"][0]["type"] == "deprecated"
        assert data["warnings"][0]["new"] == "--category formatting"

    def test_category_filter_accepts_several_categories(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(
            app,
            ["lint", str(bib), "--category", "formatting", "--category", "consistency", "--json"],
        )

        data = json.loads(result.output)
        assert set(data["summary"]["by_category"]) == {"formatting", "consistency"}

    def test_unknown_category_is_an_error(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        result = runner.invoke(app, ["lint", str(bib), "--category", "nope", "--json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["error"] == "UsageError"

    def test_format_clears_every_layout_finding(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        assert runner.invoke(app, ["format", str(bib)]).exit_code == 0
        result = runner.invoke(app, ["lint", str(bib), "--category", "formatting", "--json"])

        data = json.loads(result.output)
        assert data["summary"]["issues"] == 0

    def test_advisory_findings_fail_strict_until_suppressed(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(self.MIXED)

        # --strict means clean: an info finding fails it as an error would...
        strict = runner.invoke(app, ["lint", str(bib), "--strict", "--json"])
        assert strict.exit_code == 1, strict.output
        assert json.loads(strict.output)["summary"]["errors"] == 0
        # ...until the library or the run says it is accepted.
        accepted = runner.invoke(
            app,
            ["lint", str(bib), "--strict", "--ignore", "formatting", "--ignore", "consistency"],
        )
        assert accepted.exit_code == 0, accepted.output
        # Without --strict, lint only reports.
        assert runner.invoke(app, ["lint", str(bib)]).exit_code == 0
