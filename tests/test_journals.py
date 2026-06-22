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


def test_series_letter_is_preserved_not_dropped_or_spaced() -> None:
    # Regression: "Phys. Rev. A" used to become "Phys . Rev ." — the section
    # letter "A" collided with the omitted stop word "a" and was dropped, and
    # punctuation was joined with stray spaces. An already-abbreviated title
    # with a series letter must round-trip unchanged.
    assert abbreviate_title_with_ltwa("Phys. Rev. A") is None
    # The full form abbreviates with the letter kept and no spaces before dots.
    assert abbreviate_title_with_ltwa("Physical Review A") == "Phys. Rev. A"
    assert abbreviate_title_with_ltwa("Physical Review B") == "Phys. Rev. B"


def test_punctuation_does_not_gain_leading_spaces() -> None:
    # Regression: "Phys. Rev. Applied" used to become "Phys . Rev . Appl.".
    assert " ." not in (abbreviate_title_with_ltwa("Physical Review Applied") or "")


def test_partial_coverage_declines_instead_of_half_abbreviating() -> None:
    # Regression: "Nature Nanotechnology" used to become "Nat. Nanotechnology"
    # because only "Nature" was in the seed table. A title we can only partially
    # abbreviate is left unchanged (and reported unknown) rather than mangled.
    assert abbreviate_title_with_ltwa("Nature Nanotechnology") is None
    assert abbreviate_title_with_ltwa("Nature Materials") is None
    assert abbreviate_title_with_ltwa("Materials Science and Engineering: R: Reports") is None
    # Fully-covered titles still abbreviate.
    assert abbreviate_title_with_ltwa("Communications Physics") == "Commun. Phys."


def test_abbreviation_never_produces_spaced_dots_or_dropped_letters() -> None:
    # A spread of real-world journals that previously tripped the LTWA fallback:
    # already-abbreviated series titles, period-bearing forms, and partially
    # known full titles.
    titles = [
        "Phys. Rev. A",
        "Phys. Rev. B",
        "Phys. Rev. Lett.",
        "Phys. Rev. Applied",
        "Nature Nanotechnology",
        "Nature Materials",
        "Communications Physics",
        "Materials Science and Engineering: R: Reports",
    ]
    src = "".join(
        f"@article{{e{i},\n  journal = {{{title}}},\n  title = {{T}}\n}}\n"
        for i, title in enumerate(titles)
    )
    lib = parse_bib(src)

    result = normalize_journals(lib, "abbreviated")

    for change in result.resolved:
        new = change["new"]
        assert " ." not in new, f"spaced period in {new!r}"
        assert " ," not in new, f"spaced comma in {new!r}"
    # Already-correct series titles are left untouched, not mangled.
    journals = [e.fields.get("journal", "") for e in lib.entries.values()]
    assert "Phys . Rev ." not in journals
    assert "Phys. Rev. A" in journals  # preserved verbatim
    assert "Nature Nanotechnology" in journals  # partial coverage → left alone


def test_builtin_exact_mapping_overrides_word_generation() -> None:
    lib = parse_bib("@article{A,\n  journal = {Science},\n  title = {Paper}\n}\n")

    result = normalize_journals(lib)

    assert result.changed == 0
    assert result.unknown == []
    assert lib.entries["A"].fields["journal"] == "Science"


def test_loads_headerless_jabref_format(tmp_path: Path) -> None:
    # JabRef's own abbrv.jabref.org lists are headerless:
    # "Full Name","Abbreviation"[,"Shortest unique abbreviation"]
    table = tmp_path / "journal_abbreviations_general.csv"
    table.write_text(
        '"Accounts of Chemical Research","Acc. Chem. Res.","ACHRE4"\n'
        '"Nature Communications","Nat. Commun."\n'
    )
    sources = load_journal_table(table)
    lib = parse_bib("@article{A,\n  journal = {Nature Communications},\n  title = {x}\n}\n")

    # Abbreviate, then expand back, using only the JabRef list.
    assert normalize_journals(lib, "abbreviated", sources).changed == 1
    assert lib.entries["A"].fields["journal"] == "Nat. Commun."
    assert normalize_journals(lib, "full", sources).changed == 1
    assert lib.entries["A"].fields["journal"] == "Nature Communications"


def test_user_table_title_mapping_takes_priority(tmp_path: Path) -> None:
    table = tmp_path / "journals.csv"
    table.write_text("title,abbreviation\nNature Machine Intelligence,NMI\n")
    sources = load_sources(journal_table=table)
    lib = parse_bib(
        "@article{A,\n  journal = {Nature Machine Intelligence},\n  title = {Paper}\n}\n"
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

    assert abbreviate_title_with_ltwa("Journal of Obscure Studies", sources) == ("J. Obscur. Stud.")


def test_expansion_uses_exact_tables_only() -> None:
    lib = parse_bib("@article{A,\n  journal = {Nat. Mach. Intell.},\n  title = {Paper}\n}\n")

    result = normalize_journals(lib, "full")

    assert result.changed == 1
    assert lib.entries["A"].fields["journal"] == "Nature Machine Intelligence"


def test_unknown_journal_warns_when_no_source_resolves() -> None:
    lib = parse_bib(
        "@article{A,\n  journal = {Completely Unknown Periodical},\n  title = {Paper}\n}\n"
    )

    result = normalize_journals(lib)

    assert result.changed == 0
    assert result.unknown == ["Completely Unknown Periodical"]
