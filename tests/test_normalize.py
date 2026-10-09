"""Tests for high-level normalization."""

from pynakes.authors import normalize_authors, normalize_name_list
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.journals import normalize_journals
from pynakes.normalize import (
    SKIPPABLE_STEPS,
    NormalizeOptions,
    normalize_library,
    skipped_step_flag,
    sort_entries,
)


def test_author_list_conservative_style_normalizes_separators_and_others() -> None:
    assert normalize_name_list("Smith, J. & Jones, A.; et al.", "conservative") == (
        "Smith, J. and Jones, A. and others"
    )


def test_author_list_jabref_style_rewrites_person_names() -> None:
    assert normalize_name_list("John Smith") == "Smith, John"
    assert normalize_name_list("John von Neumann") == "von Neumann, John"
    assert normalize_name_list("John Smith and Black Brown, Peter") == (
        "Smith, John and Black Brown, Peter"
    )
    assert normalize_name_list("{World Bank} and John Smith") == ("{World Bank} and Smith, John")


def test_normalize_authors_updates_author_and_editor_fields_jabref_style() -> None:
    lib = parse_bib(
        "@book{A,\n"
        "  author = {Jane Smith & John von Neumann},\n"
        "  editor = {Jane Doe; et al.},\n"
        "  title = {Book}\n"
        "}\n"
    )

    assert normalize_authors(lib) == 2
    assert lib.entries["A"].fields["author"] == "Smith, Jane and von Neumann, John"
    assert lib.entries["A"].fields["editor"] == "Doe, Jane and others"


def test_journal_abbreviation_and_expansion() -> None:
    lib = parse_bib(
        "@article{A,\n  journal = {Nature Machine Intelligence},\n  title = {Paper}\n}\n"
    )

    abbreviated = normalize_journals(lib, "abbreviated")
    assert abbreviated.changed == 1
    assert lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."

    expanded = normalize_journals(lib, "full")
    assert expanded.changed == 1
    assert lib.entries["A"].fields["journal"] == "Nature Machine Intelligence"


def test_normalize_library_runs_standard_pass() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {Jane Smith & John Doe},\n"
        "  title = {DNA repair with eBay},\n"
        "  journal = {Nature Machine Intelligence},\n"
        "  doi = {https://doi.org/10.5555/ABC}\n"
        "}\n"
    )

    report = normalize_library(lib)

    entry = lib.entries["A"]
    assert entry.fields["author"] == "Smith, Jane and Doe, John"
    assert entry.fields["title"] == "{DNA} repair with {eBay}"
    # Journal abbreviation is off by default; the title is left as-is.
    assert entry.fields["journal"] == "Nature Machine Intelligence"
    assert entry.fields["doi"] == "10.5555/ABC"
    assert report.operations == {
        "title_fields": {"title": 1},
        "dropped_fields": 0,
        "authors": 1,
        "journals": 0,
        "dois": 1,
        "pages": 0,
        "months": 0,
        "save_action_fields": 0,
        "entry_types": 0,
        "field_names": 0,
        "keys": 0,
        "sorted_entries": 0,
        # A step that never ran says so, so a caller can tell it apart from one
        # that ran and changed nothing.
        "skipped": {
            "journals": report.skipped["journals"],
            "keys": report.skipped["keys"],
        },
    }
    assert "--journal-style" in report.skipped["journals"]
    assert "--key-generation" in report.skipped["keys"]


def test_every_skippable_step_can_be_named_and_turned_back_on() -> None:
    """A "did not run" that does not say how to make it run is only half a report."""
    options = NormalizeOptions(
        protect_titles=False,
        author_style="none",
        normalize_dois=False,
        normalize_pages=False,
        identifier_case=False,
        normalize_keys=False,
    )

    report = normalize_library(parse_bib("@article{A, title = {T}}\n"), options)

    assert set(report.skipped) == set(SKIPPABLE_STEPS)
    for step, reason in report.skipped.items():
        invocation, metadata_key = SKIPPABLE_STEPS[step]
        assert invocation in reason
        assert metadata_key in reason
        assert skipped_step_flag(step).startswith("--")


def test_normalize_reports_a_step_that_ran_but_changed_nothing_as_not_skipped() -> None:
    """``journals=0`` must mean "checked, nothing to do" once a style is set."""
    lib = parse_bib("@article{A,\n  journal = {Nat. Mach. Intell.}\n}\n")

    report = normalize_library(lib, NormalizeOptions(journal_style="abbreviated"))

    assert report.journals == 0
    assert "journals" not in report.skipped


def test_normalize_repairs_and_canonicalizes_bare_month_names_surgically() -> None:
    lib = parse_bib(
        "@article{A,\n  title = {Paper},\n  month = june,\n  note = {Keep this exact}\n}\n"
        "@article{B, month = Jan}\n"
    )

    report = normalize_library(
        lib,
        NormalizeOptions(protect_titles=False, author_style="none", normalize_dois=False),
    )

    assert report.months == 2
    assert lib.entries["A"].fields["month"] == "June"
    assert lib.entries["A"].raw_content == (
        "@article{A,\n  title = {Paper},\n  month = jun,\n  note = {Keep this exact}\n}"
    )
    assert lib.entries["B"].raw_content == "@article{B, month = jan}"


def test_normalize_repairs_abbreviation_variants_like_sept() -> None:
    lib = parse_bib(
        "@article{A, month = Sept}\n@article{B, month = Sept.}\n@article{C, month = sept}\n"
    )

    assert normalize_library(lib).months == 3
    assert lib.entries["A"].raw_content == "@article{A, month = sep}"
    assert lib.entries["B"].raw_content == "@article{B, month = sep}"
    assert lib.entries["C"].raw_content == "@article{C, month = sep}"


def test_normalize_leaves_literal_and_declared_month_names_unchanged() -> None:
    lib = parse_bib(
        "@string{june = {Custom month}}\n"
        "@article{Literal, month = {June}}\n"
        "@article{Declared, month = june}\n"
    )

    assert normalize_library(lib).months == 0
    assert "month = {June}" in lib.entries["Literal"].raw_content
    assert "month = june" in lib.entries["Declared"].raw_content


def test_normalize_uses_literal_if_standard_month_macro_is_overridden() -> None:
    lib = parse_bib("@string{jun = {A custom value}}\n@article{A, month = june}\n")

    assert normalize_library(lib).months == 1
    assert "month = {June}" in lib.entries["A"].raw_content


def test_normalize_lowercases_entry_types_and_field_names_surgically() -> None:
    original = (
        "@Article{A,\n"
        "  TITLE = {A Field},\n"
        "  DOI = {10.1234/ABC},\n"
        "  note = {Preserve FIELD = text}\n"
        "}\n"
    )
    lib = parse_bib(original)

    report = normalize_library(
        lib,
        NormalizeOptions(
            protect_titles=False,
            author_style="none",
            journal_style="none",
            normalize_dois=False,
        ),
    )

    assert report.entry_types == 1
    assert report.field_names == 2
    assert lib.entries["A"].raw_content == (
        original.replace("@Article", "@article")
        .replace("  TITLE", "  title")
        .replace("  DOI", "  doi")
        .rstrip()
    )


def test_normalize_identifier_case_honors_metadata_setting() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-identifier-case:false;}\n"
        "@Article{A,\n  TITLE = {Paper}\n}\n"
    )

    report = normalize_library(
        lib,
        NormalizeOptions(
            protect_titles=False,
            author_style="none",
            journal_style="none",
            normalize_dois=False,
        ),
    )

    assert report.entry_types == 0
    assert report.field_names == 0
    assert lib.entries["A"].raw_content.startswith("@Article")


def test_normalize_keeps_entry_types_under_preserve_type_case() -> None:
    # `format-entry-type-case: preserve` owns type spelling for every command,
    # so normalize recases field names but leaves `@Article` alone.
    lib = parse_bib(
        "@comment{pynakes-meta: format-entry-type-case: preserve;}\n"
        "@Article{A,\n  TITLE = {Paper}\n}\n"
    )

    report = normalize_library(
        lib,
        NormalizeOptions(
            protect_titles=False,
            author_style="none",
            journal_style="none",
            normalize_dois=False,
        ),
    )

    assert report.entry_types == 0
    assert report.field_names == 1
    assert lib.entries["A"].raw_content == "@Article{A,\n  title = {Paper}\n}"


def test_normalize_abbreviates_journals_only_when_style_configured() -> None:
    src = "@article{A,\n  title = {Paper},\n  journal = {Nature Machine Intelligence}\n}\n"

    # Default: journals untouched.
    default_lib = parse_bib(src)
    assert normalize_library(default_lib).journals == 0
    assert default_lib.entries["A"].fields["journal"] == "Nature Machine Intelligence"

    # Metadata opts in.
    meta_lib = parse_bib("@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n" + src)
    assert normalize_library(meta_lib).journals == 1
    assert meta_lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."

    # CLI option opts in.
    cli_lib = parse_bib(src)
    normalize_library(cli_lib, NormalizeOptions(journal_style="abbreviated"))
    assert cli_lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."


def test_normalize_metadata_key_canonical() -> None:
    src = "@article{A,\n  title = {Paper},\n  journal = {Nature Machine Intelligence}\n}\n"

    canonical = parse_bib("@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n" + src)
    assert normalize_library(canonical).journals == 1


def test_normalize_honors_jabref_saveactions_for_authors() -> None:
    # saveActions is enabled but configures no name normalization, so pynakes
    # defers to JabRef and leaves author names untouched (only journal runs).
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\ntitle[html_to_latex]\n;}\n"
        "@article{A,\n  author = {John Smith},\n  title = {T},\n  journal = {J}\n}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["author"] == "John Smith"  # not rewritten


def test_saveactions_apply_formatters_in_configured_order_and_warn_for_unsupported() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\n"
        "note[html_to_unicode,unicode_to_latex]\n"
        "abstract[unknown_formatter]\n;}\n"
        "@article{A,\n  note = {&auml;},\n  abstract = {Keep}\n}\n"
    )

    report = normalize_library(
        lib,
        NormalizeOptions(protect_titles=False, author_style="none", normalize_dois=False),
    )

    assert lib.entries["A"].fields["note"] == r"{\"{a}}"
    assert report.save_action_fields == 1
    assert report.warnings == [
        {
            "type": "unsupported_save_action_formatter",
            "field": "abstract",
            "formatter": "unknown_formatter",
            "message": "saveActions formatter 'unknown_formatter' on field 'abstract' is not supported",
        }
    ]


def test_disabled_saveactions_do_not_modify_or_warn() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:disabled;\nnote[html_to_unicode]\n;}\n"
        "@article{A,\n  note = {&auml;}\n}\n"
    )

    report = normalize_library(
        lib,
        NormalizeOptions(protect_titles=False, author_style="none", normalize_dois=False),
    )

    assert lib.entries["A"].fields["note"] == "&auml;"
    assert report.save_action_fields == 0
    assert report.warnings == []


def test_normalize_saveactions_normalize_names_enables_author_style() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\nauthor[normalize_names]\n;}\n"
        "@article{A,\n  author = {John Smith},\n  title = {T},\n  journal = {J}\n}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["author"] == "Smith, John"


def test_pynakes_meta_author_style_overrides_saveactions() -> None:
    # An explicit pynakes-meta author-style wins over JabRef's saveActions.
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\ntitle[html_to_latex]\n;}\n"
        "@comment{pynakes-meta: normalize-author-style:jabref;}\n"
        "@article{A,\n  author = {John Smith},\n  title = {T},\n  journal = {J}\n}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["author"] == "Smith, John"


def test_normalize_library_honors_metadata_overrides() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:none;}\n"
        "@comment{pynakes-meta: normalize-protect-titles:false;}\n"
        "@article{A,\n"
        "  author = {Jane Smith & John Doe},\n"
        "  title = {DNA repair},\n"
        "  journal = {Nature Machine Intelligence}\n"
        "}\n"
    )

    report = normalize_library(lib)

    entry = lib.entries["A"]
    assert entry.fields["author"] == "Smith, Jane and Doe, John"
    assert entry.fields["title"] == "DNA repair"
    assert entry.fields["journal"] == "Nature Machine Intelligence"
    assert report.title_fields == {}
    assert report.journals == 0


def test_normalize_library_cli_options_override_metadata() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:none;}\n"
        "@article{A,\n"
        "  title = {DNA repair},\n"
        "  journal = {Nature Machine Intelligence}\n"
        "}\n"
    )

    normalize_library(lib, NormalizeOptions(journal_style="abbreviated", protect_titles=False))

    assert lib.entries["A"].fields["title"] == "DNA repair"
    assert lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."


def test_normalize_leaves_fields_untouched_when_no_drop_fields_configured() -> None:
    lib = parse_bib("@article{A,\n  title = {Paper},\n  abstract = {A long summary.}\n}\n")

    report = normalize_library(lib)

    assert lib.entries["A"].fields["abstract"] == "A long summary."
    assert report.dropped_fields == 0


def test_normalize_drop_fields_removes_configured_fields() -> None:
    lib = parse_bib(
        "@article{A,\n  title = {Paper},\n  abstract = {A long summary.},\n  note = {x}\n}\n"
        "@article{B,\n  title = {Other},\n  abstract = {Another summary.}\n}\n"
    )

    report = normalize_library(lib, NormalizeOptions(drop_fields=["abstract"]))

    assert "abstract" not in lib.entries["A"].fields
    assert "abstract" not in lib.entries["B"].fields
    assert lib.entries["A"].fields["note"] == "x"
    assert report.dropped_fields == 2


def test_normalize_drop_fields_reads_metadata_key() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-drop-fields:abstract,note;}\n"
        "@article{A,\n  title = {Paper},\n  abstract = {Summary},\n  note = {x}\n}\n"
    )

    report = normalize_library(lib)

    assert "abstract" not in lib.entries["A"].fields
    assert "note" not in lib.entries["A"].fields
    assert report.dropped_fields == 2


def test_normalize_drop_fields_combines_cli_and_metadata() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-drop-fields:abstract;}\n"
        "@article{A,\n  title = {Paper},\n  abstract = {Summary},\n  note = {x}\n}\n"
    )

    normalize_library(lib, NormalizeOptions(drop_fields=["note"]))

    assert "abstract" not in lib.entries["A"].fields
    assert "note" not in lib.entries["A"].fields


def test_normalize_library_author_style_conservative_override() -> None:
    lib = parse_bib("@article{A,\n  author = {Jane Smith & John Doe},\n  title = {Paper}\n}\n")

    normalize_library(
        lib,
        NormalizeOptions(
            author_style="conservative",
            journal_style="none",
            protect_titles=False,
            normalize_dois=False,
        ),
    )

    assert lib.entries["A"].fields["author"] == "Jane Smith and John Doe"


def test_bibtex_and_biblatex_author_styles_alias_jabref() -> None:
    assert normalize_name_list("Jane Smith", "bibtex") == "Smith, Jane"
    assert normalize_name_list("Jane Smith", "biblatex") == "Smith, Jane"


def test_crossref_parent_sinking_handles_multiple_parents_and_is_idempotent() -> None:
    lib = parse_bib(
        "@proceedings{P2}\n"
        "@proceedings{P1}\n"
        "@inproceedings{child1, crossref={P1}}\n"
        "@inproceedings{child2, crossref={P2}}\n"
    )
    sort_entries(lib, [("title", False)])
    assert lib.entries.keys() == ["child2", "P2", "child1", "P1"]
    sort_entries(lib, [("title", False)])
    assert lib.entries.keys() == ["child2", "P2", "child1", "P1"]


def test_crossref_parent_sinking_resolves_first_duplicate_and_parent_chains() -> None:
    lib = parse_bib(
        "@proceedings{grand}\n"
        "@proceedings{parent, crossref={grand}}\n"
        "@proceedings{parent}\n"
        "@inproceedings{child, crossref={parent}}\n"
    )
    first_parent = lib.entries.get_all("parent")[0]
    duplicate_parent = lib.entries.get_all("parent")[1]
    sort_entries(lib, [("title", False)])
    assert lib.entries.values() == [
        lib.entries["child"],
        first_parent,
        lib.entries["grand"],
        duplicate_parent,
    ]


def test_crossref_parent_already_after_child_preserves_source_bytes() -> None:
    source = "@inproceedings{C, crossref={P}}\n\n@proceedings{P}\n"
    lib = parse_bib(source)
    sort_entries(lib, [("title", False)])
    assert write_bib(lib) == source


def test_crossref_cycles_retain_stable_order_and_are_idempotent() -> None:
    lib = parse_bib(
        "@article{A, crossref={B}}\n@article{B, crossref={C}}\n@article{C, crossref={A}}\n"
    )
    sort_entries(lib, [("title", False)])
    assert lib.entries.keys() == ["A", "B", "C"]
    sort_entries(lib, [("title", False)])
    assert lib.entries.keys() == ["A", "B", "C"]


def test_saveactions_malformed_doi_warns_and_short_doi_is_unsupported() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\n"
        "doi[clean_up_doi,short_doi]\n;}\n"
        "@article{A, doi={not-a-doi}}\n"
    )
    report = normalize_library(lib)
    warning_types = [warning["type"] for warning in report.warnings if isinstance(warning, dict)]
    assert "invalid_doi" in warning_types
    assert "unsupported_save_action_formatter" in warning_types


# --- page ranges ------------------------------------------------------------


def test_normalize_rewrites_unicode_dash_page_ranges() -> None:
    # Crossref hands out ranges punctuated with U+2013. It renders under UTF-8
    # but breaks 8-bit bibtex with some styles, and is invisible in a diff.
    lib = parse_bib("@article{A, pages = {1052–1055}}\n@article{B, pages = {865—942}}\n")

    result = normalize_library(lib)

    assert lib.entries["A"].fields["pages"] == "1052--1055"
    assert lib.entries["B"].fields["pages"] == "865--942"
    assert result.pages == 2


def test_normalize_leaves_correct_and_non_range_page_values_alone() -> None:
    lib = parse_bib(
        "@article{A, pages = {4546--4563}}\n"
        "@article{B, pages = {012345}}\n"
        "@article{C, pages = {7,41,73--97}}\n"
    )

    result = normalize_library(lib)

    assert lib.entries["A"].fields["pages"] == "4546--4563"
    assert lib.entries["B"].fields["pages"] == "012345"
    assert lib.entries["C"].fields["pages"] == "7,41,73--97"
    assert result.pages == 0


def test_normalize_pages_can_be_turned_off() -> None:
    lib = parse_bib("@article{A, pages = {1052–1055}}\n")

    normalize_library(lib, NormalizeOptions(normalize_pages=False))

    assert lib.entries["A"].fields["pages"] == "1052–1055"


def test_normalize_pages_honors_a_stored_metadata_preference() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-pages:false;}\n\n@article{A, pages = {1052–1055}}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["pages"] == "1052–1055"
