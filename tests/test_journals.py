"""Tests for journal abbreviation sources."""

from pathlib import Path

from pynakes.bibtex_parser import parse_bib
from pynakes.journals import (
    abbreviate_title_with_ltwa,
    load_journal_table,
    load_ltwa_table,
    load_sources,
    normalize_journals,
)


def test_ltwa_generation_for_unseen_title() -> None:
    assert abbreviate_title_with_ltwa("Journal of Polymer Science") == "J. Polym. Sci."


def test_builtin_exact_mapping_overrides_word_generation() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  journal = {Science},\n"
        "  title = {Paper}\n"
        "}\n"
    )

    result = normalize_journals(lib)

    assert result.changed == 0
    assert result.unknown == []
    assert lib.entries["A"].fields["journal"] == "Science"


def test_user_table_title_mapping_takes_priority(tmp_path: Path) -> None:
    table = tmp_path / "journals.csv"
    table.write_text("title,abbreviation\nNature Machine Intelligence,NMI\n")
    sources = load_sources(journal_table=table)
    lib = parse_bib(
        "@article{A,\n"
        "  journal = {Nature Machine Intelligence},\n"
        "  title = {Paper}\n"
        "}\n"
    )

    result = normalize_journals(lib, sources=sources)

    assert result.changed == 1
    assert result.resolved[0]["source"] == str(table)
    assert lib.entries["A"].fields["journal"] == "NMI"


def test_user_table_issn_mapping_takes_priority(tmp_path: Path) -> None:
    table = tmp_path / "journals.csv"
    table.write_text("title,abbreviation,issn\nCanonical Journal,Can. J.,1234-567X\n")
    sources = load_journal_table(table)
    lib = parse_bib(
        "@article{A,\n"
        "  journal = {Publisher Variant Title},\n"
        "  issn = {1234-567X},\n"
        "  title = {Paper}\n"
        "}\n"
    )

    result = normalize_journals(lib, sources=sources)

    assert result.changed == 1
    assert lib.entries["A"].fields["journal"] == "Can. J."


def test_ltwa_table_extends_word_abbreviation_source(tmp_path: Path) -> None:
    table = tmp_path / "ltwa.csv"
    table.write_text("Word,Abbreviation,Language\nObscure,Obscur.,English\n")
    sources = load_ltwa_table(table)

    assert abbreviate_title_with_ltwa("Journal of Obscure Studies", sources) == (
        "J. Obscur. Stud."
    )


def test_expansion_uses_exact_tables_only() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  journal = {Nat. Mach. Intell.},\n"
        "  title = {Paper}\n"
        "}\n"
    )

    result = normalize_journals(lib, "full")

    assert result.changed == 1
    assert lib.entries["A"].fields["journal"] == "Nature Machine Intelligence"


def test_unknown_journal_warns_when_no_source_resolves() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  journal = {Completely Unknown Periodical},\n"
        "  title = {Paper}\n"
        "}\n"
    )

    result = normalize_journals(lib)

    assert result.changed == 0
    assert result.unknown == ["Completely Unknown Periodical"]
