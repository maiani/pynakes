"""Tests for structured JabRef library metadata support."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.metadata import (
    DuplicateMetadataError,
    MetadataUpdate,
    consolidate_metadata,
    default_namespace,
    library_database_type,
    library_is_jabref_tracked,
    library_save_actions,
    library_save_order,
    metadata_category,
    metadata_owner,
    parse_save_actions,
    parse_save_order,
    remove_metadata,
    set_metadata,
)
from pynakes.model import MetadataBlock
from pynakes.usage import subset_library

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


def test_metadata_category_covers_pinned_jabref_metadata_constants() -> None:
    # MetaData.java constants at JabRef v5.15, release commit 1eb3493.
    expected_categories = {
        "databaseType": "library",
        "saveOrderConfig": "save",
        "saveActions": "save",
        "keypatterndefault": "citation-key",
        "keypattern_article": "citation-key",
        "grouping": "groups",
        "groupstree": "groups",
        "fileDirectory": "files",
        "fileDirectoryLatex": "files",
        "protectedFlag": "library",
        "VersionDBStructure": "library",
        "selector_journal": "selectors",
        "BibDesk Static Groups": "groups",
    }
    assert {key: metadata_category(key) for key in expected_categories} == expected_categories


def test_metadata_owner_separates_jabref_and_pynakes_keys() -> None:
    assert metadata_owner("databaseType") == "jabref"
    assert metadata_owner("keypattern_article") == "jabref"
    assert metadata_owner("normalize-journal-style") == "pynakes"
    assert metadata_owner("files-dir") == "pynakes"
    assert metadata_owner("unknownThing") == "unknown"


def test_pynakes_owned_keys_have_domain_categories() -> None:
    assert metadata_category("normalize-journal-style") == "normalization"
    assert metadata_category("protected-terms") == "normalization"
    assert metadata_category("lint-required-fields-article") == "lint"
    assert metadata_category("tex-sources") == "usage"
    assert metadata_category("files-dir") == "pinax"


def test_default_namespace_routes_by_owner() -> None:
    # Without file context the answer is by owner (the static "belongs to" view).
    assert default_namespace("databaseType") == "jabref"
    assert default_namespace("files-dir") == "pynakes"
    assert default_namespace("unknownThing") == "pynakes"


def test_library_is_jabref_tracked_follows_presence() -> None:
    untracked = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert library_is_jabref_tracked(untracked) is False

    tracked = parse_bib("@comment{jabref-meta: databaseType:bibtex;}\n")
    assert library_is_jabref_tracked(tracked) is True


def test_default_namespace_is_file_context_aware() -> None:
    untracked = parse_bib("@article{A,\n  title = {T}\n}\n")
    # A JabRef-native key stays in pynakes-meta on an untracked file...
    assert default_namespace("databaseType", untracked) == "pynakes"
    # ...but pynakes-owned keys are always pynakes-meta regardless.
    assert default_namespace("files-dir", untracked) == "pynakes"

    tracked = parse_bib("@comment{jabref-meta: protectedflag:true;}\n")
    assert default_namespace("databaseType", tracked) == "jabref"
    assert default_namespace("files-dir", tracked) == "pynakes"


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
    assert lib.jabref_metadata_blocks[0].value == "biblatex;"
    assert lib.jabref_metadata_blocks[0].normalized_value == "biblatex"
    assert lib.jabref_metadata_blocks[0].to_dict()["raw_value"] == "biblatex;"
    assert lib.jabref_metadata_blocks[0].to_dict()["value"] == "biblatex"
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


def test_parse_save_order_reads_jabref_criteria() -> None:
    # JabRef's serialized form: type, then field;descending pairs, trailing ';'.
    order = parse_save_order("specified;author;false;year;true;")
    assert order is not None
    assert order.order_type == "specified"
    assert order.criteria == [("author", False), ("year", True)]


def test_parse_save_order_original_and_absent() -> None:
    assert parse_save_order(None) is None
    assert parse_save_order("") is None
    keep = parse_save_order("original;")
    assert keep is not None and keep.order_type == "original" and keep.criteria == []


def test_parse_save_order_is_case_insensitive_on_type() -> None:
    order = parse_save_order("SPECIFIED;citationkey;TRUE;")
    assert order is not None
    assert order.order_type == "specified"
    assert order.criteria == [("citationkey", True)]


def test_parse_save_order_unknown_even_token_list_keeps_original() -> None:
    # An unrecognized leading token with an even token count cannot form whole
    # criteria pairs, so (like JabRef) the order degrades to "original".
    order = parse_save_order("citationkey;false;")
    assert order is not None
    assert order.order_type == "original"
    assert order.criteria == []


def test_library_save_order_reads_from_metadata() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveOrderConfig:specified;citationkey;false;}\n"
        "@article{A,\n  title = {T},\n  year = {2020}\n}\n"
    )
    order = library_save_order(lib)
    assert order is not None
    assert order.order_type == "specified"
    assert order.criteria == [("citationkey", False)]


def test_library_database_type_reads_biblatex() -> None:
    lib = parse_bib("@comment{jabref-meta: databaseType:biblatex;}\n")
    assert library_database_type(lib) == "biblatex"


def test_library_database_type_reads_bibtex() -> None:
    lib = parse_bib("@comment{jabref-meta: databaseType:bibtex;}\n")
    assert library_database_type(lib) == "bibtex"


def test_library_database_type_defaults_to_bibtex_when_absent() -> None:
    lib = parse_bib("@article{A, title = {T}}\n")
    assert library_database_type(lib) == "bibtex"


def test_parse_both_namespaces_and_merge_precedence() -> None:
    text = (
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
        "@comment{pynakes-meta: keypatterndefault:[auth][shorttitle];}\n"
        "@comment{pynakes-meta: normalize-journal-style:full;}\n\n"
        "@article{Smith2020,\n  author = {John Smith},\n  title = {A Paper},\n  year = {2020}\n}\n"
    )

    lib = parse_bib(text)

    # Blocks are split by namespace.
    assert isinstance(lib.jabref_metadata_blocks[0], MetadataBlock)
    assert [b.key for b in lib.jabref_metadata_blocks] == ["databaseType", "keypatterndefault"]
    assert [b.key for b in lib.pynakes_metadata_blocks] == [
        "keypatterndefault",
        "normalize-journal-style",
    ]
    assert lib.pynakes_metadata_blocks[0].namespace == "pynakes"
    # Merged view: pynakes-meta wins on a conflicting key.
    assert lib.metadata["keypatterndefault"] == "[auth][shorttitle];"
    assert lib.metadata["databaseType"] == "bibtex;"
    assert lib.metadata["normalize-journal-style"] == "full;"
    # metadata_blocks returns both namespaces in source order.
    assert [b.key for b in lib.metadata_blocks] == [
        "databaseType",
        "keypatterndefault",
        "keypatterndefault",
        "normalize-journal-style",
    ]
    # Round-trip is byte-for-byte.
    assert write_bib(lib) == text


def test_pynakes_meta_round_trips_after_set(tmp_path: Path) -> None:
    lib = parse_bib("@comment{jabref-meta: databaseType:bibtex;}\n")
    # Native key updates jabref-meta in place; pynakes-only key appends pynakes-meta.
    set_metadata(lib, "databaseType", "biblatex")
    set_metadata(lib, "normalize-journal-style", "abbreviated")

    out = write_bib(lib)
    assert "@comment{jabref-meta: databaseType:biblatex;}" in out
    # pynakes-meta is written as one consolidated block, one `key: value` per line.
    assert "@comment{pynakes-meta:\nnormalize-journal-style: abbreviated\n}" in out
    # Re-parsing yields the same split + merged view.
    reparsed = parse_bib(out)
    assert reparsed.jabref_metadata["databaseType"] == "biblatex;"
    assert reparsed.metadata["normalize-journal-style"] == "abbreviated"


def test_set_multiple_pynakes_keys_share_one_consolidated_block() -> None:
    lib = parse_bib("")
    set_metadata(lib, "normalize-journal-style", "abbreviated")
    set_metadata(lib, "protected-terms", "GPU,API")
    set_metadata(lib, "normalize-dois", "on")

    out = write_bib(lib)
    # Exactly one pynakes-meta comment, holding all three settings.
    assert out.count("@comment{pynakes-meta:") == 1
    assert "normalize-journal-style: abbreviated" in out
    assert "protected-terms: GPU,API" in out
    assert "normalize-dois: on" in out

    reparsed = parse_bib(out)
    assert reparsed.metadata["normalize-journal-style"] == "abbreviated"
    assert reparsed.metadata["protected-terms"] == "GPU,API"
    assert reparsed.metadata["normalize-dois"] == "on"


def test_update_one_key_in_consolidated_block_leaves_others() -> None:
    lib = parse_bib("")
    set_metadata(lib, "normalize-journal-style", "abbreviated")
    set_metadata(lib, "protected-terms", "GPU,API")
    # Changing one key rewrites the block but preserves the other setting.
    update = set_metadata(lib, "normalize-journal-style", "full")

    assert update.created is False
    reparsed = parse_bib(write_bib(lib))
    assert reparsed.metadata["normalize-journal-style"] == "full"
    assert reparsed.metadata["protected-terms"] == "GPU,API"


def test_pynakes_block_round_trips_both_layouts_byte_for_byte() -> None:
    # Default `key: value` layout.
    new_form = (
        "@comment{pynakes-meta:\n"
        "normalize-journal-style: abbreviated\n"
        "protected-terms: GPU,API\n"
        "}\n"
    )
    lib = parse_bib(new_form)
    assert [b.key for b in lib.pynakes_metadata_blocks] == [
        "normalize-journal-style",
        "protected-terms",
    ]
    assert lib.metadata["protected-terms"] == "GPU,API"
    assert write_bib(lib) == new_form

    # Legacy `key:value;` layout is still read, and round-trips verbatim.
    legacy_form = (
        "@comment{pynakes-meta:\n"
        "normalize-journal-style:abbreviated;\n"
        "protected-terms:GPU,API;\n"
        "}\n"
    )
    legacy = parse_bib(legacy_form)
    assert legacy.metadata["protected-terms"] == "GPU,API;"
    assert write_bib(legacy) == legacy_form


def test_consolidate_merges_separate_pynakes_comments_into_one_block() -> None:
    text = (
        "@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n"
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{pynakes-meta: protected-terms:GPU,API;}\n\n"
        "@article{A,\n  title = {T}\n}\n"
    )
    lib = parse_bib(text)
    result = consolidate_metadata(lib, text, lib.line_ending)
    assert result is not None
    # jabref-meta stays its own comment; the two pynakes comments merge into one.
    assert result.count("@comment{pynakes-meta:") == 1
    assert result.count("@comment{jabref-meta:") == 1
    # Legacy `key:value;` inputs are rewritten in the default `key: value` form.
    assert "normalize-journal-style: abbreviated" in result
    assert "protected-terms: GPU,API" in result
    reparsed = parse_bib(result)
    assert reparsed.metadata["normalize-journal-style"] == "abbreviated"
    assert reparsed.metadata["protected-terms"] == "GPU,API"


def test_normalize_honors_pynakes_meta_journal_style(tmp_path: Path) -> None:
    # journal-style preference stored in pynakes-meta drives `normalize`.
    text = (
        "@comment{pynakes-meta: normalize-journal-style:full;}\n\n"
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


def test_set_metadata_untracked_file_keeps_native_key_in_pynakes() -> None:
    # On a pynakes-native file (no jabref-meta blocks), even a JabRef-native key
    # stays in pynakes-meta: pynakes does not inject jabref-meta until adoption.
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")

    update = set_metadata(lib, "keypatterndefault", "[auth][year]")

    assert isinstance(update, MetadataUpdate)
    assert update.created is True
    assert update.namespace == "pynakes"
    assert lib.pynakes_metadata["keypatterndefault"] == "[auth][year]"


def test_set_metadata_tracked_file_appends_known_jabref_block() -> None:
    # A JabRef-tracked file (already carries jabref-meta) keeps native keys there.
    lib = parse_bib("@comment{jabref-meta: protectedflag:true;}\n\n@article{A,\n  title = {T}\n}\n")

    update = set_metadata(lib, "keypatterndefault", "[auth][year]")

    assert update.created is True
    assert update.namespace == "jabref"
    assert "@comment{jabref-meta: keypatterndefault:[auth][year];}" in lib.raw_comments
    assert lib.jabref_metadata["keypatterndefault"] == "[auth][year];"


def test_set_metadata_routes_unknown_to_pynakes_by_default() -> None:
    # A key JabRef cannot represent is no longer rejected; it lands in the
    # pynakes-meta namespace, which is pynakes' own superset.
    lib = parse_bib("")

    update = set_metadata(lib, "not-a-jabref-key", "value")

    assert update.namespace == "pynakes"
    assert update.created is True
    assert update.new_raw == "@comment{pynakes-meta:\nnot-a-jabref-key: value\n}"
    assert lib.pynakes_metadata["not-a-jabref-key"] == "value"
    # ...but forcing it into jabref-meta still requires --allow-unknown.
    try:
        set_metadata(lib, "another-unknown", "value", namespace="jabref")
    except ValueError as exc:
        assert "Unknown JabRef metadata key" in str(exc)
    else:
        raise AssertionError("expected ValueError when forcing unknown key into jabref-meta")


def test_set_metadata_routes_native_key_by_file_context() -> None:
    # Untracked (no jabref-meta): a JabRef-native key stays in pynakes-meta.
    untracked = parse_bib("")
    u = set_metadata(untracked, "databaseType", "biblatex")
    assert u.namespace == "pynakes"

    # Tracked (already carries jabref-meta): the native key routes to jabref-meta.
    tracked = parse_bib("@comment{jabref-meta: protectedflag:true;}\n")
    t = set_metadata(tracked, "databaseType", "biblatex")
    assert t.namespace == "jabref"
    assert t.new_raw == "@comment{jabref-meta: databaseType:biblatex;}"


def test_set_metadata_refuses_duplicate_blocks() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{jabref-meta: databaseType:biblatex;}\n"
    )

    try:
        set_metadata(lib, "databaseType", "biblatex")
    except DuplicateMetadataError as exc:
        assert exc.key == "databaseType"
        assert exc.count == 2
    else:
        raise AssertionError("expected DuplicateMetadataError")


def test_remove_metadata_pynakes_key_rewrites_block_in_place() -> None:
    lib = parse_bib("@comment{pynakes-meta:\ndatabaseType: biblatex;\nfiles-dir: refs.files;\n}\n")

    update = remove_metadata(lib, "databaseType", namespace="pynakes")

    assert update is not None
    assert update.namespace == "pynakes"
    assert "databaseType" not in lib.pynakes_metadata
    assert lib.pynakes_metadata["files-dir"] == "refs.files"


def test_remove_metadata_drops_emptied_pynakes_comment() -> None:
    lib = parse_bib("@comment{pynakes-meta:\ndatabaseType: biblatex;\n}\n")

    update = remove_metadata(lib, "databaseType", namespace="pynakes")

    assert update is not None
    assert update.new_raw == ""
    assert "databaseType" not in lib.pynakes_metadata


def test_remove_metadata_jabref_drops_whole_comment() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{jabref-meta: protectedflag:true;}\n"
    )

    update = remove_metadata(lib, "databaseType", namespace="jabref")

    assert update is not None
    assert update.new_raw == ""
    assert "databaseType" not in lib.jabref_metadata
    assert lib.jabref_metadata["protectedflag"] == "true;"


def test_remove_metadata_absent_key_returns_none() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert remove_metadata(lib, "databaseType") is None


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
    # A JabRef-tracked file (carries jabref-meta) keeps native keys in jabref-meta.
    bib.write_text("@comment{jabref-meta: protectedflag:true;}\n\n@article{A,\n  title = {T}\n}\n")

    result = runner.invoke(
        app, ["metadata", "set", str(bib), "keypatterndefault", "[auth][year]", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["created"] is True
    assert data["namespace"] == "jabref"
    text = bib.read_text()
    # New metadata is appended at the canonical bottom position, after the entry.
    assert text.index("@article{A,") < text.index("@comment{jabref-meta: keypatterndefault")
    assert text.rstrip().endswith("@comment{jabref-meta: keypatterndefault:[auth][year];}")


def test_metadata_set_unknown_key_goes_to_pynakes(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    result = runner.invoke(app, ["metadata", "set", str(bib), "unknownThing", "value", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["namespace"] == "pynakes"
    assert data["created"] is True
    assert "@comment{pynakes-meta:\nunknownThing: value\n}" in bib.read_text()


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
    assert data["error"] == "DuplicateMetadata"
    assert data["count"] == 2


def test_metadata_adopt_jabref_anchors_databasetype(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Curie1898,\n  title = {T}\n}\n\n@comment{pynakes-meta:\nfiles-dir: refs.files;\n}\n"
    )

    result = runner.invoke(app, ["metadata", "adopt-jabref", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["database_type_added"] is True
    assert data["was_tracked"] is False
    assert data["moved_keys"] == []
    text = bib.read_text()
    assert "@comment{jabref-meta: databaseType:bibtex;}" in text
    # The entry is left byte-for-byte untouched.
    assert "@article{Curie1898,\n  title = {T}\n}" in text


def test_metadata_adopt_jabref_rehomes_native_key(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n  title = {T}\n}\n\n"
        "@comment{pynakes-meta:\ndatabaseType: biblatex;\nfiles-dir: refs.files;\n}\n"
    )

    result = runner.invoke(app, ["metadata", "adopt-jabref", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["moved_keys"] == ["databaseType"]
    text = bib.read_text()
    assert "@comment{jabref-meta: databaseType:biblatex;}" in text
    # databaseType is gone from the pynakes-meta comment, but its companions remain.
    pynakes_block = text.split("pynakes-meta:")[1].split("}")[0]
    assert "databaseType" not in pynakes_block
    assert "files-dir" in pynakes_block


def test_metadata_adopt_jabref_idempotent(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{jabref-meta: databaseType:bibtex;}\n\n@article{A,\n  title = {T}\n}\n")

    result = runner.invoke(app, ["metadata", "adopt-jabref", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["modified"] is False
    assert data["was_tracked"] is True
    assert data["moved_keys"] == []
    assert data["database_type_added"] is False


def test_metadata_adopt_then_native_set_routes_to_jabref(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n  title = {T}\n}\n\n@comment{pynakes-meta:\nfiles-dir: refs.files;\n}\n"
    )

    runner.invoke(app, ["metadata", "adopt-jabref", str(bib)])
    result = runner.invoke(app, ["metadata", "set", str(bib), "protectedflag", "true", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["namespace"] == "jabref"


def test_metadata_adopt_jabref_dry_run_does_not_write(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (
        "@article{A,\n  title = {T}\n}\n\n@comment{pynakes-meta:\nfiles-dir: refs.files;\n}\n"
    )
    bib.write_text(original)

    result = runner.invoke(app, ["metadata", "adopt-jabref", str(bib), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert bib.read_text() == original
