"""Tests for structured JabRef library metadata support."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.jabref import DuplicateJabRefMetadataError, set_metadata
from pynakes.usage import subset_library

runner = CliRunner()


def test_parse_known_and_unknown_jabref_metadata_blocks() -> None:
    text = (
        "@Comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{jabref-meta: saveOrderConfig:specified;year;false;}\n"
        "@comment{jabref-meta: selector_journal:Physical Review B;Nature;}\n"
        "@comment{jabref-meta: unknownThing:keep:all:colons;}\n\n"
        "@article{Smith2020,\n"
        "  author = {John Smith},\n"
        "  title = {A Paper},\n"
        "  journal = {Journal},\n"
        "  year = {2020}\n"
        "}\n"
    )

    lib = parse_bib(text)

    assert lib.jabref_metadata["databaseType"] == "biblatex;"
    assert lib.jabref_metadata["unknownThing"] == "keep:all:colons;"
    assert [block.key for block in lib.jabref_metadata_blocks] == [
        "databaseType",
        "saveOrderConfig",
        "selector_journal",
        "unknownThing",
    ]
    assert lib.jabref_metadata_blocks[0].known is True
    assert lib.jabref_metadata_blocks[0].category == "library"
    assert lib.jabref_metadata_blocks[2].category == "selectors"
    assert lib.jabref_metadata_blocks[3].known is False
    assert write_bib(lib) == text


def test_set_metadata_updates_known_block_without_touching_unknown() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:bibtex;}\n@comment{jabref-meta: unknownThing:keep;}\n"
    )

    update = set_metadata(lib, "databaseType", "biblatex")

    assert update.created is False
    assert update.old_raw == "@comment{jabref-meta: databaseType:bibtex;}"
    assert update.new_raw == "@comment{jabref-meta: databaseType:biblatex;}"
    assert lib.raw_comments == [
        "@comment{jabref-meta: databaseType:biblatex;}",
        "@comment{jabref-meta: unknownThing:keep;}",
    ]
    assert lib.jabref_metadata["databaseType"] == "biblatex;"
    assert lib.jabref_metadata["unknownThing"] == "keep;"


def test_set_metadata_appends_missing_known_block() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")

    update = set_metadata(lib, "keypatterndefault", "[auth][year]")

    assert update.created is True
    assert lib.raw_comments == ["@comment{jabref-meta: keypatterndefault:[auth][year];}"]
    assert lib.jabref_metadata["keypatterndefault"] == "[auth][year];"


def test_set_metadata_rejects_unknown_by_default() -> None:
    lib = parse_bib("")

    try:
        set_metadata(lib, "not-a-jabref-key", "value")
    except ValueError as exc:
        assert "Unknown JabRef metadata key" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_set_metadata_refuses_duplicate_blocks() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{jabref-meta: databaseType:biblatex;}\n"
    )

    try:
        set_metadata(lib, "databaseType", "biblatex")
    except DuplicateJabRefMetadataError as exc:
        assert exc.key == "databaseType"
        assert exc.count == 2
    else:
        raise AssertionError("expected DuplicateJabRefMetadataError")


def test_subset_preserves_structured_metadata_blocks() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:biblatex;}\n\n@article{A,\n  title = {T}\n}\n"
    )

    subset = subset_library(lib, ["A"])

    assert subset.jabref_metadata == lib.jabref_metadata
    assert subset.jabref_metadata_blocks == lib.jabref_metadata_blocks


def test_inspect_json_includes_jabref_metadata(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{jabref-meta: unknownThing:keep;}\n\n"
        "@article{A,\n  title = {T}\n}\n"
    )

    result = runner.invoke(app, ["inspect", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    metadata = data["jabref_metadata"]
    assert metadata["values"]["databaseType"] == "biblatex;"
    assert metadata["blocks"][0]["category"] == "library"
    assert metadata["blocks"][1]["known"] is False


def test_metadata_list_json(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{jabref-meta: databaseType:biblatex;}\n")

    result = runner.invoke(app, ["metadata", "list", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["metadata"]["blocks"][0]["key"] == "databaseType"


def test_metadata_set_dry_run_diff_does_not_write(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = "@comment{jabref-meta: databaseType:bibtex;}\n"
    bib.write_text(original)

    result = runner.invoke(
        app,
        ["metadata", "set", str(bib), "databaseType", "biblatex", "--dry-run", "--diff", "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["created"] is False
    assert "databaseType:biblatex" in data["diff"]
    assert bib.read_text() == original


def test_metadata_set_writes_existing_block(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{jabref-meta: databaseType:bibtex;}\n")

    result = runner.invoke(app, ["metadata", "set", str(bib), "databaseType", "biblatex"])

    assert result.exit_code == 0, result.output
    assert bib.read_text() == "@comment{jabref-meta: databaseType:biblatex;}\n"


def test_metadata_set_appends_missing_block(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T}\n}\n")

    result = runner.invoke(
        app, ["metadata", "set", str(bib), "keypatterndefault", "[auth][year]", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["created"] is True
    assert bib.read_text().startswith("@comment{jabref-meta: keypatterndefault:[auth][year];}\n")


def test_metadata_set_unknown_key_errors(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    result = runner.invoke(app, ["metadata", "set", str(bib), "unknownThing", "value", "--json"])

    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["error"] == "InvalidInput"


def test_metadata_set_duplicate_key_conflicts(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{jabref-meta: databaseType:biblatex;}\n"
    )

    result = runner.invoke(app, ["metadata", "set", str(bib), "databaseType", "biblatex", "--json"])

    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert data["error"] == "DuplicateJabRefMetadata"
    assert data["count"] == 2
