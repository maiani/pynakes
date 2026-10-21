"""Engine contracts required by entry editors and existing JabRef libraries."""

import json

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.entry_types import entry_field_schema, entry_type_names
from pynakes.group_tree import list_entries_in_group_tree
from pynakes.groups import add_to_group, list_groups, remove_from_group, rename_group_memberships
from pynakes.saved_queries import compile_selector
from pynakes.usage import tag_with_group

runner = CliRunner()


@pytest.mark.parametrize("delimiter", [",", ";"])
def test_group_operations_share_separator_and_preserve_source(delimiter):
    source = f"@article{{A,\n  title = {{One}},\n  groups = {{Physics{delimiter} Optics}}\n}}\n"
    lib = parse_bib(source)
    assert write_bib(lib) == source
    assert list_groups(lib) == ["Physics", "Optics"]
    assert list_entries_in_group_tree(lib, "Optics") == ["A"]
    assert compile_selector(lib, 'group "Optics"')[0](lib.entries["A"])
    add_to_group(lib, "A", "Read")
    tag_with_group(lib, ["A"], "Cited")
    assert (
        lib.entries["A"].fields["groups"]
        == f"Physics{delimiter} Optics{delimiter} Read{delimiter} Cited"
    )
    assert rename_group_memberships(lib, "Physics", "Theory") == ["A"]
    remove_from_group(lib, "A", "Optics")
    assert lib.entries["A"].fields["groups"] == f"Theory{delimiter} Read{delimiter} Cited"
    assert "  title = {One}," in write_bib(lib)


def test_mixed_groups_require_explicit_choice_and_queries_respect_it():
    lib = parse_bib("@article{A, groups={Physics, Optics; History}}")
    with pytest.raises(ValueError, match="Ambiguous"):
        list_groups(lib)
    assert list_groups(lib, separator="semicolon") == ["Physics, Optics", "History"]
    # Unrelated reads are still possible to repair the configuration.
    assert compile_selector(lib, 'key = "A"')[0](lib.entries["A"])
    lib = parse_bib(
        "@comment{pynakes-meta: groups-separator:semicolon;}\n@article{A, groups={Physics, Optics; History}}"
    )
    assert compile_selector(lib, 'group "Physics, Optics"')[0](lib.entries["A"])
    with pytest.raises(ValueError, match="separator"):
        add_to_group(lib, "A", "Bad; Name")


def test_global_separator_override_is_scoped(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{pynakes-meta: groups-separator:semicolon;}\n@article{A, groups={Physics, Optics}}"
    )
    args = ["ref", "show", str(bib), "--where", 'group "Optics"', "--json"]
    result = runner.invoke(app, ["--groups-separator", "comma", *args])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["entries"]) == 1
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["entries"] == []
    result = runner.invoke(app, ["metadata", "set", str(bib), "groups-separator", "bad", "--json"])
    assert result.exit_code == 1


def test_field_schema_preserves_alternatives_profile_and_custom_fields():
    lib = parse_bib(
        "@comment{pynakes-meta: dialect:biblatex;}\n@comment{pynakes-meta: lint-required-fields:doi;}"
    )
    schema = entry_field_schema("online", lib=lib, fields=["title", "doi", "MyCustomField"])
    assert schema["dialect"] == "biblatex"
    assert ["author", "editor"] in schema["required"]
    assert ["doi", "eprint", "url"] in schema["required"]
    assert schema["profile_required"] == ["doi"]
    assert "doi" not in schema["optional"]
    assert schema["other"] == ["MyCustomField"]
    assert entry_field_schema("book", dialect="bibtex")["required"][0] == ["author", "editor"]
    assert entry_field_schema("book", dialect="biblatex")["required"][0] == ["author"]
    unknown = entry_field_schema("custom", fields=["title", "private"])
    assert not unknown["known_type"]
    assert unknown["other"] == ["title", "private"]
    for dialect in ("bibtex", "biblatex"):
        for name in entry_type_names(dialect=dialect):
            assert entry_field_schema(name, dialect=dialect)["known_type"]
    with pytest.raises(ValueError):
        entry_field_schema("book", dialect="invalid")
    with pytest.raises(ValueError):
        entry_type_names(dialect="invalid")


def test_schema_cli_is_readonly_and_includes_existing_types(tmp_path):
    bib = tmp_path / "refs.bib"
    original = "@article{A, title={One}, custom={Keep}}\n@unknown{B, note={Keep too}}"
    bib.write_text(original)
    result = runner.invoke(app, ["ref", "schema", str(bib), "--dialect", "biblatex", "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    schemas = {s["entry_type"]: s for s in envelope["entry_schemas"]}
    assert schemas["article"]["other"] == ["custom"]
    assert schemas["unknown"]["other"] == ["note"]
    assert envelope["source_sha256"]
    assert bib.read_text() == original


def test_generate_reports_same_material_plan_in_preview_and_apply(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Old, author={Isaac Newton}, title={Optics}, year={1704}}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    )
    materials = tmp_path / "refs.files"
    materials.mkdir()
    source = materials / "Old.preprint.pdf"
    source.write_bytes(b"pdf")
    args = ["keys", "generate", str(bib), "Old", "--json"]
    preview = runner.invoke(app, [*args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.output)["pinax_materials"]
    assert len(plan) == 1
    assert source.exists()
    applied = runner.invoke(app, args)
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["pinax_materials"] == plan
    assert not source.exists()
    assert (materials / "Newton1704Optics.preprint.pdf").read_bytes() == b"pdf"


def test_repair_keeps_shared_materials_under_surviving_key(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@misc{A, title={One}}\n@misc{A, title={Two}}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    )
    materials = tmp_path / "refs.files"
    materials.mkdir()
    source = materials / "A.preprint.pdf"
    source.write_bytes(b"pdf")
    result = runner.invoke(app, ["keys", "repair", str(bib), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["pinax_materials"] == []
    assert source.read_bytes() == b"pdf"


def test_generate_material_collision_fails_preview_without_writes(tmp_path):
    bib = tmp_path / "refs.bib"
    original = "@misc{Old, author={Isaac Newton}, title={Optics}, year={1704}}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    bib.write_text(original)
    materials = tmp_path / "refs.files"
    materials.mkdir()
    (materials / "Old.preprint.pdf").write_bytes(b"old")
    (materials / "Newton1704Optics.preprint.pdf").write_bytes(b"existing")
    result = runner.invoke(app, ["keys", "generate", str(bib), "Old", "--dry-run", "--json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["status"] in {"error", "conflict"}
    assert bib.read_text() == original
    assert (materials / "Old.preprint.pdf").read_bytes() == b"old"
    assert (materials / "Newton1704Optics.preprint.pdf").read_bytes() == b"existing"


def test_group_lint_uses_library_separator_and_reports_ambiguity():
    from pynakes.lint import lint

    comma = parse_bib("@misc{A, groups={One,, Two}}")
    assert any(issue.type == "malformed_groups" for issue in lint(comma))
    mixed = parse_bib("@misc{A, groups={One, Two; Three}}")
    assert any("Ambiguous" in issue.message for issue in lint(mixed))
    explicit = parse_bib(
        "@comment{pynakes-meta: groups-separator:semicolon;}\n@misc{A, groups={One,, Two; Three}}"
    )
    assert not any(issue.type == "malformed_groups" for issue in lint(explicit))


def test_auto_group_mutation_refuses_to_introduce_ambiguous_names():
    lib = parse_bib("@misc{A, title={One}}")
    with pytest.raises(ValueError, match="explicit"):
        add_to_group(lib, "A", "One; Two")
    assert "groups" not in lib.entries["A"].fields
    assert add_to_group(lib, "A", "One; Two", separator="comma") == 1


@pytest.mark.parametrize(
    "stored, expected", [(",;", ["One", "Two; Three"]), (r"\;;", ["One, Two", "Three"])]
)
def test_jabref_separator_declaration_precedes_detection(stored, expected):
    lib = parse_bib(
        "@comment{jabref-meta: keywordSeparator:" + stored + "}\n@misc{A, groups={One, Two; Three}}"
    )
    assert list_groups(lib) == expected
    assert compile_selector(lib, f'group "{expected[0]}"')[0](lib.entries["A"])
    assert list_groups(lib, separator="semicolon") == ["One, Two", "Three"]
    with pytest.raises(ValueError, match="Ambiguous"):
        list_groups(lib, separator="auto")


def test_native_separator_setting_overrides_jabref_and_unknown_is_not_guessed():
    source = "@comment{jabref-meta: keywordSeparator:|;}\n@misc{A, groups={One, Two}}"
    lib = parse_bib(source)
    with pytest.raises(ValueError, match="Unsupported JabRef"):
        list_groups(lib)
    lib = parse_bib(source + "\n@comment{pynakes-meta: groups-separator:comma;}")
    assert list_groups(lib) == ["One", "Two"]
