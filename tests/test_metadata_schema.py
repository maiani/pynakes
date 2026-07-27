"""Tests for the pynakes canonical metadata schema and its JabRef fallback accessors."""

import pytest

import pynakes.metadata as metadata_pkg
from pynakes.bibtex_parser import parse_bib
from pynakes.engine import Bibliography
from pynakes.io import load_bib
from pynakes.metadata import library_dialect, library_sort_order


def test_library_dialect_reads_native_dialect_key() -> None:
    lib = parse_bib("@comment{pynakes-meta:\ndialect: biblatex\n}\n")
    assert library_dialect(lib) == "biblatex"


def test_library_dialect_native_key_wins_over_jabref_database_type() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:bibtex;}\n"
        "@comment{pynakes-meta:\ndialect: biblatex\n}\n"
    )
    assert library_dialect(lib) == "biblatex"


def test_library_dialect_falls_back_to_jabref_database_type() -> None:
    lib = parse_bib("@comment{jabref-meta: databaseType:biblatex;}\n")
    assert library_dialect(lib) == "biblatex"


def test_library_dialect_defaults_to_bibtex_when_neither_set() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert library_dialect(lib) == "bibtex"


def test_library_dialect_ignores_invalid_native_value() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{pynakes-meta:\ndialect: not-a-dialect\n}\n"
    )
    assert library_dialect(lib) == "biblatex"


def test_library_sort_order_reads_native_sort_order_key() -> None:
    lib = parse_bib("@comment{pynakes-meta:\nsort-order: year:desc,author\n}\n")
    assert library_sort_order(lib) == [("year", True), ("author", False)]


def test_library_sort_order_native_key_wins_over_jabref_save_order_config() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveOrderConfig:specified;author;false;}\n"
        "@comment{pynakes-meta:\nsort-order: year:desc\n}\n"
    )
    assert library_sort_order(lib) == [("year", True)]


def test_library_sort_order_native_original_keeps_current_order() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveOrderConfig:specified;author;false;}\n"
        "@comment{pynakes-meta:\nsort-order: original\n}\n"
    )
    assert library_sort_order(lib) == []


def test_library_sort_order_falls_back_to_jabref_when_specified() -> None:
    lib = parse_bib("@comment{jabref-meta: saveOrderConfig:specified;citationkey;true;}\n")
    assert library_sort_order(lib) == [("citationkey", True)]


def test_library_sort_order_jabref_fallback_gated_on_specified_type() -> None:
    lib = parse_bib("@comment{jabref-meta: saveOrderConfig:original;}\n")
    assert library_sort_order(lib) is None


def test_library_sort_order_none_when_neither_configured() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert library_sort_order(lib) is None


def test_metadata_package_reexports_every_previously_public_name() -> None:
    # `pynakes.metadata` used to be a flat module; every name it exposed before
    # the core/schema/jabref split must still resolve from the package.
    previously_public_names = [
        "metadata_value",
        "metadata_values",
        "metadata_list",
        "format_metadata_list",
        "metadata_list_values",
        "metadata_bool",
        "MetadataCategory",
        "MetadataOwner",
        "CATEGORY_LIBRARY",
        "CATEGORY_SAVE",
        "CATEGORY_FILES",
        "CATEGORY_GROUPS",
        "CATEGORY_SELECTORS",
        "CATEGORY_CITATION_KEY",
        "CATEGORY_NORMALIZATION",
        "CATEGORY_LINT",
        "CATEGORY_USAGE",
        "CATEGORY_PINAX",
        "CATEGORY_UNKNOWN",
        "JABREF_EXACT_KEYS",
        "JABREF_PREFIX_KEYS",
        "PYNAKES_EXACT_KEYS",
        "PYNAKES_PREFIX_KEYS",
        "JABREF_PREFIX",
        "PYNAKES_PREFIX",
        "DuplicateMetadataError",
        "MetadataUpdate",
        "metadata_category",
        "metadata_owner",
        "is_known_metadata_key",
        "SaveActions",
        "parse_save_actions",
        "library_save_actions",
        "SAVE_ORDER_KEY_FIELDS",
        "SAVE_ORDER_TYPES",
        "SaveOrder",
        "parse_save_order",
        "library_save_order",
        "library_database_type",
        "library_is_jabref_tracked",
        "default_namespace",
        "parse_metadata_comment",
        "metadata_blocks_to_dict",
        "format_metadata_comment",
        "format_pynakes_meta_block",
        "consolidate_metadata",
        "set_metadata",
        "remove_metadata",
        "JabRefAdoptReport",
    ]
    for name in previously_public_names:
        assert hasattr(metadata_pkg, name), f"pynakes.metadata.{name} no longer resolves"


def test_library_database_type_alias_matches_library_dialect() -> None:
    assert metadata_pkg.library_database_type is metadata_pkg.library_dialect


# --- native key-pattern ----------------------------------------------------


def test_key_pattern_is_pynakes_owned() -> None:
    assert metadata_pkg.metadata_owner("key-pattern") == "pynakes"
    assert metadata_pkg.metadata_owner("key-pattern-article") == "pynakes"
    assert metadata_pkg.metadata_category("key-pattern") == "citation-key"


def test_library_key_pattern_reads_native_first() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: keypatterndefault:[auth];}\n"
        "@comment{pynakes-meta:\nkey-pattern: [auth][year]\n}\n"
    )
    assert metadata_pkg.library_key_pattern(lib, "article") == "[auth][year]"


def test_library_key_pattern_type_specific_native_wins() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta:\nkey-pattern: [auth]\nkey-pattern-article: [auth][year]\n}\n"
    )
    assert metadata_pkg.library_key_pattern(lib, "article") == "[auth][year]"
    assert metadata_pkg.library_key_pattern(lib, "book") == "[auth]"


def test_library_key_pattern_falls_back_to_jabref() -> None:
    lib = parse_bib("@comment{jabref-meta: keypatterndefault:[auth][year];}\n")
    assert metadata_pkg.library_key_pattern(lib, "article") == "[auth][year]"


def test_library_key_pattern_none_when_neither_configured() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert metadata_pkg.library_key_pattern(lib, "article") is None


# --- jabref_projection -----------------------------------------------------


def test_jabref_projection_translates_aliased_native_keys() -> None:
    assert metadata_pkg.jabref_projection("dialect", "biblatex") == ("databaseType", "biblatex")
    assert metadata_pkg.jabref_projection("key-pattern", "[auth]") == (
        "keypatterndefault",
        "[auth]",
    )
    assert metadata_pkg.jabref_projection("key-pattern-article", "[auth]") == (
        "keypattern_article",
        "[auth]",
    )
    assert metadata_pkg.jabref_projection("sort-order", "year:desc,author") == (
        "saveOrderConfig",
        "specified;year;true;author;false",
    )


def test_jabref_projection_none_for_unaliased_key() -> None:
    assert metadata_pkg.jabref_projection("normalize-dois", "true") is None


# --- mirror-on-write -------------------------------------------------------


def test_set_native_dialect_mirrors_into_jabref_when_tracked(tmp_path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(
        "@comment{jabref-meta: databaseType:bibtex;}\n\n@article{A,\n  title = {T}\n}\n"
    )
    coll = Bibliography.open(str(path))
    update = coll.set_metadata("dialect", "biblatex")
    assert update.namespace == "pynakes"
    assert update.mirrored is not None and update.mirrored.key == "databaseType"
    coll.commit()
    lib = load_bib(str(path))
    assert lib.metadata["dialect"] == "biblatex"
    assert lib.metadata["databaseType"].rstrip(";") == "biblatex"


def test_set_native_dialect_no_mirror_when_untracked(tmp_path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("@article{A,\n  title = {T}\n}\n")
    coll = Bibliography.open(str(path))
    update = coll.set_metadata("dialect", "biblatex")
    assert update.mirrored is None
    coll.commit()
    lib = load_bib(str(path))
    assert "databaseType" not in lib.metadata
    assert lib.jabref_metadata_blocks == []


def test_set_native_sort_order_mirrors_as_save_order_config(tmp_path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(
        "@comment{jabref-meta: saveOrderConfig:original;}\n\n@article{A,\n  title = {T}\n}\n"
    )
    coll = Bibliography.open(str(path))
    update = coll.set_metadata("sort-order", "year:desc,author")
    assert update.mirrored is not None and update.mirrored.key == "saveOrderConfig"
    coll.commit()
    order = metadata_pkg.library_save_order(load_bib(str(path)))
    assert order is not None and order.order_type == "specified"
    assert order.criteria == [("year", True), ("author", False)]


# --- drift warnings --------------------------------------------------------


def test_aliased_drift_warns_when_dialect_disagrees() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:bibtex;}\n@comment{pynakes-meta:\ndialect: biblatex\n}\n"
    )
    warnings = metadata_pkg.aliased_drift_warnings(lib)
    assert any("drift" in w and "dialect" in w for w in warnings)


# --- validate_metadata_value ------------------------------------------------


def test_validate_dialect_accepts_bibtex() -> None:
    metadata_pkg.validate_metadata_value("dialect", "bibtex")


def test_validate_dialect_accepts_biblatex() -> None:
    metadata_pkg.validate_metadata_value("dialect", "biblatex")


def test_validate_dialect_accepts_database_type() -> None:
    metadata_pkg.validate_metadata_value("databaseType", "biblatex")


def test_validate_dialect_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="Invalid dialect"):
        metadata_pkg.validate_metadata_value("dialect", "nonsense")


def test_validate_dialect_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Invalid dialect"):
        metadata_pkg.validate_metadata_value("dialect", "")


def test_validate_fetch_policy_accepts_valid() -> None:
    for val in ("preprint", "published", "source", "supplement", "bestpdf"):
        metadata_pkg.validate_metadata_value("pinax-fetch-policy", val)


def test_validate_fetch_policy_accepts_comma_separated() -> None:
    metadata_pkg.validate_metadata_value("pinax-fetch-policy", "preprint, published")
    metadata_pkg.validate_metadata_value("pinax-fetch-policy", "bestpdf, source")
    metadata_pkg.validate_metadata_value("pinax-fetch-policy", "preprint,published,source")
    metadata_pkg.validate_metadata_value("pinax-fetch-policy", "published,supplement")


def test_parse_fetch_policy_selects_supplement() -> None:
    policy = metadata_pkg.parse_fetch_policy("published, supplement")

    assert policy.published is True
    assert policy.supplement is True
    assert policy.preprint is False


def test_validate_fetch_policy_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid pinax-fetch-policy"):
        metadata_pkg.validate_metadata_value("pinax-fetch-policy", "maybe")


def test_validate_known_key_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("sort-order", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("key-pattern", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("tex-sources", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("normalize-protected-terms", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("lint-required-fields", "")


def test_validate_known_prefix_key_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("key-pattern-article", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("normalize-title-case", "")
    with pytest.raises(ValueError, match="must not be empty"):
        metadata_pkg.validate_metadata_value("lint-required-fields-article", "")


def test_validate_unknown_key_skips_validation() -> None:
    metadata_pkg.validate_metadata_value("some-unknown-key", "")
    metadata_pkg.validate_metadata_value("some-unknown-key", "anything")


def test_validate_accepts_non_empty_known_values() -> None:
    metadata_pkg.validate_metadata_value("sort-order", "year:desc")
    metadata_pkg.validate_metadata_value("key-pattern", "[auth][year]")
    metadata_pkg.validate_metadata_value("tex-sources", "paper.tex")
    metadata_pkg.validate_metadata_value("normalize-protected-terms", "pH,NaCl")
    metadata_pkg.validate_metadata_value("pinax-files-dir", "refs.files")
    metadata_pkg.validate_metadata_value("normalize-journal-table", "J. Phys.: A, J. Chem.")
    metadata_pkg.validate_metadata_value("normalize-dois", "true")


def test_unprefixed_normalization_profile_keys_are_not_recognized() -> None:
    for key in ("protected-terms", "journal-table", "ltwa-table"):
        assert metadata_pkg.metadata_category(key) == "unknown"


def test_unprefixed_pinax_files_dir_is_not_recognized() -> None:
    assert metadata_pkg.metadata_category("files-dir") == "unknown"
    assert metadata_pkg.metadata_category("fetch-policy") == "unknown"


def test_validate_dialect_handles_trailing_semicolon() -> None:
    metadata_pkg.validate_metadata_value("databaseType", "biblatex;")


def test_validate_dialect_handles_case_insensitive() -> None:
    metadata_pkg.validate_metadata_value("dialect", "BibTeX")
    metadata_pkg.validate_metadata_value("dialect", "BIBLATEX")


# --- drift warnings --------------------------------------------------------


def test_aliased_drift_silent_when_consistent() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@comment{pynakes-meta:\ndialect: biblatex\n}\n"
    )
    assert metadata_pkg.aliased_drift_warnings(lib) == []
