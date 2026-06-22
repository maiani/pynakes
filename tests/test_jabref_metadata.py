"""Tests for structured JabRef library metadata support."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.metadata import (
    DuplicateJabRefMetadataError,
    consolidate_metadata,
    library_save_actions,
    parse_save_actions,
    set_metadata,
)
from pynakes.usage import subset_library

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


def test_consolidate_metadata_moves_stranded_blocks_to_end_sorted() -> None:
    text = (
        "@Comment{jabref-meta: saveOrderConfig:specified;year;false;}\n"
        "\n"
        "@article{A,\n  author = {Smith, John},\n  title = {T}\n}\n"
        "\n"
        "@Comment{jabref-meta: databaseType:bibtex;}\n"
        "\n"
        "@article{B,\n  author = {Doe, Jane},\n  title = {U}\n}\n"
    )
    lib = parse_bib(text)

    result = consolidate_metadata(lib, text)

    assert result is not None
    # Both entries survive, in order, before the metadata section.
    a, b = result.index("@article{A,"), result.index("@article{B,")
    first_meta = result.index("@Comment{jabref-meta")
    assert a < b < first_meta
    # Metadata is sorted by key (databaseType before saveOrderConfig).
    assert result.index("databaseType") < result.index("saveOrderConfig")
    # One blank line separates the two metadata blocks.
    assert "databaseType:bibtex;}\n\n@Comment{jabref-meta: saveOrderConfig" in result
    # Ends with a single trailing newline.
    assert result.endswith(";}\n") and not result.endswith(";}\n\n")


def test_consolidate_metadata_is_idempotent() -> None:
    text = (
        "@article{A,\n  author = {Smith, John},\n  title = {T}\n}\n"
        "\n"
        "@Comment{jabref-meta: databaseType:bibtex;}\n"
    )
    lib = parse_bib(text)

    # Already canonical: nothing to do.
    assert consolidate_metadata(lib, text) is None


def test_consolidate_metadata_no_blocks_is_noop() -> None:
    text = "@article{A,\n  title = {T}\n}\n"
    assert consolidate_metadata(parse_bib(text), text) is None


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


def test_parse_save_actions_reads_jabref_formatters() -> None:
    sa = parse_save_actions("enabled;\nauthor[normalize_names]\npages[normalize_page_numbers]\n;")
    assert sa is not None
    assert sa.enabled is True
    assert sa.cleanups == {"author": ["normalize_names"], "pages": ["normalize_page_numbers"]}
    assert sa.has("normalize_names", ("author", "editor")) is True
    assert sa.has("normalize_names", ("title",)) is False
    assert sa.has(("clean_up_doi", "short_doi"), ("doi",)) is False


def test_parse_save_actions_disabled_and_absent() -> None:
    assert parse_save_actions(None) is None
    assert parse_save_actions("") is None
    disabled = parse_save_actions("disabled;\nauthor[normalize_names]\n;")
    assert disabled is not None and disabled.enabled is False


def test_library_save_actions_reads_from_metadata() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\ndoi[clean_up_doi]\n;}\n"
        "@article{A,\n  title = {T},\n  year = {2020}\n}\n"
    )
    sa = library_save_actions(lib)
    assert sa is not None
    assert sa.has(("clean_up_doi", "short_doi"), ("doi",)) is True


def test_parse_both_namespaces_and_merge_precedence() -> None:
    text = (
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
        "@comment{pynakes-meta: keypatterndefault:[auth][shorttitle];}\n"
        "@comment{pynakes-meta: pynakes-normalize-journal-style:full;}\n\n"
        "@article{Smith2020,\n  author = {John Smith},\n  title = {A Paper},\n  year = {2020}\n}\n"
    )

    lib = parse_bib(text)

    # Blocks are split by namespace.
    assert [b.key for b in lib.jabref_metadata_blocks] == ["databaseType", "keypatterndefault"]
    assert [b.key for b in lib.pynakes_metadata_blocks] == [
        "keypatterndefault",
        "pynakes-normalize-journal-style",
    ]
    assert lib.pynakes_metadata_blocks[0].namespace == "pynakes"
    # Merged view: pynakes-meta wins on a conflicting key.
    assert lib.metadata["keypatterndefault"] == "[auth][shorttitle];"
    assert lib.metadata["databaseType"] == "bibtex;"
    assert lib.metadata["pynakes-normalize-journal-style"] == "full;"
    # metadata_blocks returns both namespaces in source order.
    assert [b.key for b in lib.metadata_blocks] == [
        "databaseType",
        "keypatterndefault",
        "keypatterndefault",
        "pynakes-normalize-journal-style",
    ]
    # Round-trip is byte-for-byte.
    assert write_bib(lib) == text


def test_pynakes_meta_round_trips_after_set(tmp_path: Path) -> None:
    lib = parse_bib("@comment{jabref-meta: databaseType:bibtex;}\n")
    # Native key updates jabref-meta in place; pynakes-only key appends pynakes-meta.
    set_metadata(lib, "databaseType", "biblatex")
    set_metadata(lib, "pynakes-normalize-journal-style", "abbreviated")

    out = write_bib(lib)
    assert "@comment{jabref-meta: databaseType:biblatex;}" in out
    assert "@comment{pynakes-meta: pynakes-normalize-journal-style:abbreviated;}" in out
    # Re-parsing yields the same split + merged view.
    reparsed = parse_bib(out)
    assert reparsed.jabref_metadata["databaseType"] == "biblatex;"
    assert reparsed.metadata["pynakes-normalize-journal-style"] == "abbreviated;"


def test_normalize_honors_pynakes_meta_journal_style(tmp_path: Path) -> None:
    # journal-style preference stored in pynakes-meta drives `normalize`.
    text = (
        "@comment{pynakes-meta: pynakes-normalize-journal-style:full;}\n\n"
        "@article{S,\n  author = {A. Author},\n  title = {T},\n"
        "  journal = {Phys. Rev. Lett.},\n  year = {2020}\n}\n"
    )
    bib = tmp_path / "refs.bib"
    bib.write_text(text)

    result = runner.invoke(app, ["normalize", str(bib), "--json"])
    assert result.exit_code == 0, result.output
    # With journal-style=full from pynakes-meta, the abbreviation is expanded
    # (or left unchanged if unknown) — the point is normalize read the preference
    # without a --journal-style flag and did not abbreviate.
    assert "Phys. Rev. Lett." not in bib.read_text() or "Physical Review Letters" in bib.read_text()


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


def test_set_metadata_routes_unknown_to_pynakes_by_default() -> None:
    # A key JabRef cannot represent is no longer rejected; it lands in the
    # pynakes-meta namespace, which is pynakes' own superset.
    lib = parse_bib("")

    update = set_metadata(lib, "not-a-jabref-key", "value")

    assert update.namespace == "pynakes"
    assert update.created is True
    assert update.new_raw == "@comment{pynakes-meta: not-a-jabref-key:value;}"
    assert lib.pynakes_metadata["not-a-jabref-key"] == "value;"
    # ...but forcing it into jabref-meta still requires --allow-unknown.
    try:
        set_metadata(lib, "another-unknown", "value", namespace="jabref")
    except ValueError as exc:
        assert "Unknown JabRef metadata key" in str(exc)
    else:
        raise AssertionError("expected ValueError when forcing unknown key into jabref-meta")


def test_set_metadata_routes_native_key_to_jabref() -> None:
    lib = parse_bib("")
    update = set_metadata(lib, "databaseType", "biblatex")
    assert update.namespace == "jabref"
    assert update.new_raw == "@comment{jabref-meta: databaseType:biblatex;}"


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
    text = bib.read_text()
    # New metadata is appended at the canonical bottom position, after the entry.
    assert text.index("@article{A,") < text.index("@comment{jabref-meta:")
    assert text.rstrip().endswith("@comment{jabref-meta: keypatterndefault:[auth][year];}")


def test_metadata_set_unknown_key_goes_to_pynakes(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    result = runner.invoke(app, ["metadata", "set", str(bib), "unknownThing", "value", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["namespace"] == "pynakes"
    assert data["created"] is True
    assert "@comment{pynakes-meta: unknownThing:value;}" in bib.read_text()


def test_metadata_set_unknown_key_into_jabref_errors(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    result = runner.invoke(
        app,
        ["metadata", "set", str(bib), "unknownThing", "value", "--namespace", "jabref", "--json"],
    )

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
