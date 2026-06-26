"""Tests for citation-key generation, duplicate detection, and repair."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    duplicate_key_counts,
    generate_key,
    generate_key_from_pattern,
    has_duplicate_keys,
    regenerate_key,
    regenerate_keys,
    rename_key,
    repair_duplicate_keys,
)
from pynakes.model import BibEntry


def _entry(**fields) -> BibEntry:
    return BibEntry(key="orig", type="article", fields=fields)


class TestGenerateKey:
    def test_author_year_title(self) -> None:
        e = _entry(author="John Smith", year="2020", title="Big Data Analysis")
        assert generate_key(e) == "Smith2020Big"

    def test_last_comma_first_name_format(self) -> None:
        e = _entry(author="Smith, John", year="2020", title="Data")
        assert generate_key(e) == "Smith2020Data"

    def test_multiple_authors_uses_first(self) -> None:
        e = _entry(author="Jane Doe and John Smith", year="2019", title="Networks")
        assert generate_key(e) == "Doe2019Networks"

    def test_skips_title_stopwords(self) -> None:
        e = _entry(author="Smith", year="2020", title="The Theory of Everything")
        assert generate_key(e) == "Smith2020Theory"

    def test_strips_protective_braces(self) -> None:
        e = _entry(author="{World Bank}", year="2021", title="{GDP} Report")
        assert generate_key(e) == "WorldBank2021GDP"

    def test_falls_back_to_editor_then_anon(self) -> None:
        assert (
            generate_key(_entry(editor="Ann Lee", year="2020", title="Reader")) == "Lee2020Reader"
        )
        assert generate_key(_entry(year="2020", title="Untitled")).startswith("Anon2020")

    def test_year_from_biblatex_date(self) -> None:
        e = _entry(author="Smith", date="2022-07-15", title="Stuff")
        assert generate_key(e) == "Smith2022Stuff"

    def test_deterministic(self) -> None:
        e = _entry(author="Smith", year="2020", title="Data")
        assert generate_key(e) == generate_key(e)

    def test_jabref_default_pattern_from_library_metadata(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
            "@article{old,\n"
            "  author = {John Smith},\n"
            "  year = {2024},\n"
            "  title = {A Practical Test}\n"
            "}\n"
        )
        assert generate_key(lib.entries["old"], lib) == "Smith24Practical"

    def test_jabref_entry_type_pattern_overrides_default(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
            "@comment{jabref-meta: keypattern_article:[auth][year][veryshorttitle];}\n"
            "@article{old,\n"
            "  author = {John Smith},\n"
            "  year = {2024},\n"
            "  title = {A Practical Test}\n"
            "}\n"
        )
        assert generate_key(lib.entries["old"], lib) == "Smith2024Practical"

    def test_jabref_pattern_supports_literals_and_field_markers(self) -> None:
        e = _entry(
            author="John Smith", year="2024", title="A Practical Test", journal="Test Journal"
        )
        assert generate_key_from_pattern(e, "[auth]-[YEAR]-[journal:abbr]") == "Smith-2024-TJ"

    def test_unsupported_jabref_pattern_errors(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Practical Test")
        try:
            generate_key_from_pattern(e, "[auth][unknownSpecial]")
        except UnsupportedCitationKeyPatternError as exc:
            assert "unknownSpecial" in str(exc)
        else:
            raise AssertionError("expected unsupported pattern error")

    def test_marker_variants(self) -> None:
        e = _entry(
            author="John Smith and Jane Doe and Bob Roe",
            year="2024",
            title="A Practical Study of Things",
        )
        assert generate_key_from_pattern(e, "[auth3]") == "Smi"  # truncated last name
        assert generate_key_from_pattern(e, "[authors]") == "SmithDoeRoe"
        assert generate_key_from_pattern(e, "[shortyear]") == "24"
        assert generate_key_from_pattern(e, "[shorttitle]") == "PracticalStudyThings"
        assert generate_key_from_pattern(e, "[camel2]") == "APractical"
        assert generate_key_from_pattern(e, "[entrytype]") == "Article"

    def test_accented_author_names_fold_to_ascii(self) -> None:
        e = _entry(
            author="Šexample, Aa and Øfoo-Bär, Bb",
            year="2020",
            title="Generic Sample Title",
        )
        # The leading accented letter must fold to ASCII (Š → S), not be dropped.
        assert generate_key_from_pattern(e, "[auth]_[year]_[veryshorttitle]") == (
            "Sexample_2020_Generic"
        )
        assert generate_key_from_pattern(e, "[authors]") == "SexampleOfooBar"

    def test_modifier_variants(self) -> None:
        e = _entry(
            author="John Smith", year="2024", title="A Practical Study", journal="test journal"
        )
        assert generate_key_from_pattern(e, "[auth:lower]") == "smith"
        assert generate_key_from_pattern(e, "[auth:upper]") == "SMITH"
        assert generate_key_from_pattern(e, "[journal:abbr]") == "tj"
        assert generate_key_from_pattern(e, "[journal:capitalize]") == "TestJournal"
        assert generate_key_from_pattern(e, "[auth:truncate3]") == "Smi"

    def test_unsupported_modifier_errors(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study")
        with pytest.raises(UnsupportedCitationKeyPatternError, match="modifier"):
            generate_key_from_pattern(e, "[auth:bogusmod]")


class TestDuplicateDetection:
    def test_detects_duplicates(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@article{A,year={2}}\n@book{B,year={3}}\n")
        assert has_duplicate_keys(lib) is True
        assert duplicate_key_counts(lib) == {"A": 2}

    def test_no_duplicates(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@book{B,year={2}}\n")
        assert has_duplicate_keys(lib) is False
        assert duplicate_key_counts(lib) == {}


class TestRepair:
    def test_repair_suffixes_later_duplicates(self) -> None:
        lib = parse_bib(
            "@article{A,\n  year = {1}\n}\n\n@article{A,\n  year = {2}\n}\n\n"
            "@article{A,\n  year = {3}\n}\n"
        )
        renames = repair_duplicate_keys(lib)
        assert renames == [("A", "A_2"), ("A", "A_3")]
        assert sorted(lib.entries.keys()) == ["A", "A_2", "A_3"]
        assert not has_duplicate_keys(lib)

    def test_repair_avoids_existing_keys(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@article{A,year={2}}\n@article{A_2,year={3}}\n")
        renames = repair_duplicate_keys(lib)
        # A_2 is taken, so the duplicate becomes A_3.
        assert renames == [("A", "A_3")]
        assert not has_duplicate_keys(lib)

    def test_repair_round_trips(self) -> None:
        lib = parse_bib(
            "@article{Dup,\n  title = {First}\n}\n\n@article{Dup,\n  title = {Second}\n}\n"
        )
        repair_duplicate_keys(lib)
        out = write_bib(lib)
        assert "@article{Dup," in out
        assert "@article{Dup_2," in out
        assert parse_bib(out).entries.duplicate_keys() == {}


class TestRename:
    def test_rename_single_key(self) -> None:
        lib = parse_bib("@article{Old,\n  title = {T}\n}\n")

        assert rename_key(lib, "Old", "New") == 1

        assert "New" in lib.entries
        assert "@article{New," in write_bib(lib)

    def test_rename_rejects_existing_target(self) -> None:
        lib = parse_bib("@article{Old,year={1}}\n@article{New,year={2}}\n")

        with pytest.raises(ValueError, match="target key already exists"):
            rename_key(lib, "Old", "New")

    def test_rename_rejects_duplicated_source_key(self) -> None:
        lib = parse_bib("@article{Old,year={1}}\n@article{Old,year={2}}\n")

        with pytest.raises(ValueError, match="repair duplicates"):
            rename_key(lib, "Old", "New")


class TestRegenerate:
    def test_regenerate_one_uses_pattern_without_changing_other_keys(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{keep,\n  author = {Jane Doe},\n  year = {2023},\n  title = {Other}\n}\n"
        )

        assert regenerate_key(lib, "old") == ("old", "Smith24")

        assert "Smith24" in lib.entries
        assert "keep" in lib.entries

    def test_regenerate_one_disambiguates_against_existing_keys(self) -> None:
        lib = parse_bib(
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{Smith2024Data,\n  title = {Existing}\n}\n"
        )

        assert regenerate_key(lib, "old") == ("old", "Smith2024Dataa")

    def test_regenerate_applies_generated_keys(self) -> None:
        lib = parse_bib(
            "@article{old1,\n  author = {John Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("old1", "Smith2020Data")]
        assert "Smith2020Data" in lib.entries

    def test_regenerate_mints_key_for_empty_key_entry(self) -> None:
        # An entry parsed with an empty key must get a real key on generate,
        # surgically (only the header line changes).
        lib = parse_bib(
            "@article{,\n  author = {Bob White},\n  year = {2022},\n  title = {Findings}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("", "White2022Findings")]
        assert "White2022Findings" in lib.entries
        out = write_bib(lib)
        assert out.startswith("@article{White2022Findings,")
        assert "@article{," not in out

    def test_regenerate_disambiguates_collisions(self) -> None:
        lib = parse_bib(
            "@article{x,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n\n"
            "@article{y,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        new_keys = [n for _, n in renames]
        assert new_keys == ["Smith2020Data", "Smith2020Dataa"]

    def test_regenerate_uses_jabref_pattern_metadata(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n"
            "  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("old", "Smith24")]

    def test_regenerate_skips_xdata_entries(self) -> None:
        # @xdata entries are referenced by key from other entries via
        # ``xdata = {key}``; renaming them would silently break those refs.
        src = (
            "@xdata{pub, publisher = {Press}, location = {City}}\n"
            "@book{old, xdata = {pub}, title = {T}, author = {Doe, J.}, year = {2020}}\n"
        )
        lib = parse_bib(src)
        renames = regenerate_keys(lib)
        renamed_keys = {old for old, _ in renames}
        assert "pub" not in renamed_keys, "xdata entry key must not be renamed"
        assert lib.entries["pub"].type == "xdata"
        # The @book entry is still renamed normally.
        assert any(new == "Doe2020T" for _, new in renames)
        # The xdata reference in the @book entry still points to the original key.
        from pynakes.bibtex_writer import write_bib

        out = write_bib(lib)
        assert "xdata = {pub}" in out
