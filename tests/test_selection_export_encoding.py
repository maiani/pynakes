"""Selection exports and stored-field encoding retain bibliography semantics."""

import json

import pytest
from typer.testing import CliRunner

from pynakes._field_encoding import encode_text
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.export import export_selection
from pynakes.fields import encode_field

runner = CliRunner()
SOURCE = """@string{press = {Example Press}}
@book{Parent, title={Collected Works}, publisher=press, year={1900}}
@incollection{Child, title={One}, crossref={Parent}}
@misc{Other, title={Other}}
"""


def test_native_export_dependency_closure_and_source_fidelity():
    lib = parse_bib(SOURCE)
    result = export_selection(lib, [lib.entries["Child"]], "bib")
    exported = parse_bib(result.content)
    assert list(exported.entries.keys()) == ["Parent", "Child"]
    assert result.dependency_keys == ["Parent"]
    assert result.selected_entries == 1
    assert result.exported_entries == 2
    assert exported.strings == lib.strings
    assert exported.entries["Child"].raw_content == lib.entries["Child"].raw_content
    assert write_bib(lib) == SOURCE


def test_interchange_resolves_inheritance_without_exporting_parent():
    lib = parse_bib(SOURCE)
    result = export_selection(lib, [lib.entries["Child"]], "csl-json")
    entries = json.loads(result.content)
    assert len(entries) == 1
    assert entries[0]["id"] == "Child"
    assert entries[0]["publisher"] == "Example Press"
    assert result.dependency_keys == []
    assert write_bib(lib) == SOURCE


def test_export_cycles_duplicate_and_missing_dependencies():
    lib = parse_bib(
        "@misc{A, related={B, Missing}}\n@misc{B, related={A}}\n@misc{B, title={Second}}"
    )
    result = export_selection(lib, [lib.entries["A"]], "bib")
    assert result.exported_entries == 3
    assert {w["type"] for w in result.warnings} == {
        "missing_export_dependency",
        "ambiguous_export_dependency",
    }
    assert export_selection(lib, [], "bib").content == ""


def test_cli_export_selection_and_output_safety(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(SOURCE)
    out = tmp_path / "selected.bib"
    args = ["convert", str(bib), "--to", "bib", "--key", "Child", "--out", str(out), "--json"]
    preview = runner.invoke(app, [*args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert not out.exists()
    assert json.loads(preview.output)["dependency_keys"] == ["Parent"]
    applied = runner.invoke(app, args)
    assert applied.exit_code == 0, applied.output
    assert list(parse_bib(out.read_text()).entries.keys()) == ["Parent", "Child"]
    assert runner.invoke(app, args).exit_code != 0
    assert bib.read_text() == SOURCE
    selected = runner.invoke(
        app, ["convert", str(bib), "--to", "csl-json", "--where", "key = Child", "--json"]
    )
    assert selected.exit_code == 0, selected.output
    assert len(json.loads(json.loads(selected.output)["content"])) == 1
    rejected = runner.invoke(
        app, ["convert", str(bib), "--to", "biblatex", "--key", "Child", "--json"]
    )
    assert rejected.exit_code == 1


@pytest.mark.parametrize(
    "value, expected",
    [
        (r"Garc\'{i}a and M\"{u}ller", "García and Müller"),
        (
            r"{NASA} and $\alpha_i$ and \unknown{\"{o}}",
            r"{NASA} and $\alpha_i$ and \unknown{\"{o}}",
        ),
        (r"\aa{} word", "å word"),
        (r"\aa word", "åword"),
        (r"\(\alpha\) and \[x^2\]", r"\(\alpha\) and \[x^2\]"),
    ],
)
def test_unicode_text_conversion_preserves_tex_structure(value, expected):
    assert encode_text(value, "unicode")[0] == expected
    assert encode_text(expected, "unicode")[0] == expected


def test_latex_encoding_preserves_math_and_reports_unsupported():
    value = "Café and Cafe\u0301; $α$; 漢"
    converted, warnings = encode_text(value, "latex")
    assert converted == r"Caf{\'{e}} and Caf{\'{e}}; $α$; 漢"
    assert warnings == ["character 漢"]
    assert encode_text(converted, "latex")[0] == converted
    assert encode_text(r"\ensuremath{α}", "latex")[0] == r"\ensuremath{α}"


def test_field_encoding_selection_metadata_and_surgical_edits(tmp_path):
    source = "@comment{pynakes-meta: fields-encoding:latex;}\n@misc{A,\n  title = {Café},\n  note = {Untouched}\n}\n@misc{B, title={Café}}\n"
    lib = parse_bib(source)
    report = encode_field(lib, "title", where=lambda e: e.key == "A")
    assert report["changed_entries"] == 1
    assert lib.entries["B"].raw_content == parse_bib(source).entries["B"].raw_content
    assert "  note = {Untouched}" in write_bib(lib)
    assert (
        encode_field(lib, "title", to="unicode", where=lambda e: e.key == "A")["changed_entries"]
        == 1
    )
    bib = tmp_path / "refs.bib"
    bib.write_text(source)
    args = ["fields", "encode", str(bib), "title", "--key", "A", "--json"]
    preview = runner.invoke(app, [*args, "--dry-run", "--diff"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["modified_entries"] == 1
    assert bib.read_text() == source
    applied = runner.invoke(app, args)
    assert applied.exit_code == 0, applied.output
    override = runner.invoke(app, [*args, "--to", "unicode"])
    assert override.exit_code == 0, override.output


def test_encoding_requires_direction_and_invalid_setting_refused(tmp_path):
    with pytest.raises(ValueError):
        encode_field(parse_bib("@misc{A, title={One}}"), "title")
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{A, title={One}}")
    result = runner.invoke(app, ["metadata", "set", str(bib), "fields-encoding", "bad", "--json"])
    assert result.exit_code == 1


def test_unicode_text_punctuation_and_ligatures_are_encoded_without_touching_markup():
    text = "Œuvre—Straße; {NASA}"
    latex, warnings = encode_text(text, "latex")
    assert not warnings
    assert latex == r"{\OE}uvre{\textemdash}Stra{\ss}e; {NASA}"
    assert encode_text(latex, "unicode")[0] == "{Œ}uvre{—}Stra{ß}e; {NASA}"


def test_key_export_keeps_physical_duplicates_and_reports_empty_selection(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{A, title={One}}\n@misc{A, title={Two}}")
    result = runner.invoke(app, ["convert", str(bib), "--to", "bib", "--key", "A", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["selected_entries"] == 2
    assert len(parse_bib(report["content"]).entries.get_all("A")) == 2
    result = runner.invoke(
        app, ["convert", str(bib), "--to", "bib", "--where", "title = Missing", "--json"]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["content"] == ""
    assert report["warnings"][0]["type"] == "no_entries_selected"


def test_supported_text_formatting_is_retained_while_its_text_is_converted():
    converted, warnings = encode_text(r"\textit{Caf\'{e}} and \custom{Caf\'{e}}", "unicode")
    assert converted == r"\textit{Café} and \custom{Caf\'{e}}"
    assert warnings == [r"command \custom"]
    assert encode_text(r"\textbf{Café}", "latex")[0] == r"\textbf{Caf{\'{e}}}"
