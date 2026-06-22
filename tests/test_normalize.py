"""Tests for high-level normalization."""

from pynakes.authors import normalize_authors, normalize_name_list
from pynakes.bibtex_parser import parse_bib
from pynakes.journals import normalize_journals
from pynakes.normalize import NormalizeOptions, normalize_library


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
        "authors": 1,
        "journals": 0,
        "dois": 1,
        "save_action_fields": 0,
    }


def test_normalize_abbreviates_journals_only_when_style_configured() -> None:
    src = "@article{A,\n  title = {Paper},\n  journal = {Nature Machine Intelligence}\n}\n"

    # Default: journals untouched.
    default_lib = parse_bib(src)
    assert normalize_library(default_lib).journals == 0
    assert default_lib.entries["A"].fields["journal"] == "Nature Machine Intelligence"

    # Metadata opts in.
    meta_lib = parse_bib(
        "@comment{jabref-meta: pynakes-normalize-journal-style:abbreviated;}\n" + src
    )
    assert normalize_library(meta_lib).journals == 1
    assert meta_lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."

    # CLI option opts in.
    cli_lib = parse_bib(src)
    normalize_library(cli_lib, NormalizeOptions(journal_style="abbreviated"))
    assert cli_lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."


def test_normalize_metadata_key_canonical_and_legacy_alias() -> None:
    src = "@article{A,\n  title = {Paper},\n  journal = {Nature Machine Intelligence}\n}\n"

    # Canonical bare key.
    canonical = parse_bib("@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n" + src)
    assert normalize_library(canonical).journals == 1

    # Legacy pynakes-normalize- alias still honored.
    legacy = parse_bib(
        "@comment{pynakes-meta: pynakes-normalize-journal-style:abbreviated;}\n" + src
    )
    assert normalize_library(legacy).journals == 1

    # When both are present, the canonical key wins.
    both = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:none;}\n"
        "@comment{pynakes-meta: pynakes-normalize-journal-style:abbreviated;}\n" + src
    )
    assert normalize_library(both).journals == 0


def test_normalize_honors_jabref_saveactions_for_authors() -> None:
    # saveActions is enabled but configures no name normalization, so pynakes
    # defers to JabRef and leaves author names untouched (only journal runs).
    lib = parse_bib(
        "@comment{jabref-meta: saveActions:enabled;\ntitle[html_to_latex]\n;}\n"
        "@article{A,\n  author = {John Smith},\n  title = {T},\n  journal = {J}\n}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["author"] == "John Smith"  # not rewritten


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
        "@comment{pynakes-meta: pynakes-normalize-author-style:jabref;}\n"
        "@article{A,\n  author = {John Smith},\n  title = {T},\n  journal = {J}\n}\n"
    )

    normalize_library(lib)

    assert lib.entries["A"].fields["author"] == "Smith, John"


def test_normalize_library_honors_metadata_overrides() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: pynakes-normalize-journal-style:none;}\n"
        "@comment{jabref-meta: pynakes-normalize-protect-titles:false;}\n"
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
        "@comment{jabref-meta: pynakes-normalize-journal-style:none;}\n"
        "@article{A,\n"
        "  title = {DNA repair},\n"
        "  journal = {Nature Machine Intelligence}\n"
        "}\n"
    )

    normalize_library(lib, NormalizeOptions(journal_style="abbreviated", protect_titles=False))

    assert lib.entries["A"].fields["title"] == "DNA repair"
    assert lib.entries["A"].fields["journal"] == "Nat. Mach. Intell."


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
