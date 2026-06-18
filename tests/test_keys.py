"""Tests for citation-key generation, duplicate detection, and repair."""

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.keys import (
    duplicate_key_counts,
    generate_key,
    has_duplicate_keys,
    regenerate_keys,
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
        assert generate_key(_entry(editor="Ann Lee", year="2020", title="Reader")) == "Lee2020Reader"
        assert generate_key(_entry(year="2020", title="Untitled")).startswith("Anon2020")

    def test_year_from_biblatex_date(self) -> None:
        e = _entry(author="Smith", date="2022-07-15", title="Stuff")
        assert generate_key(e) == "Smith2022Stuff"

    def test_deterministic(self) -> None:
        e = _entry(author="Smith", year="2020", title="Data")
        assert generate_key(e) == generate_key(e)


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
        lib = parse_bib(
            "@article{A,year={1}}\n@article{A,year={2}}\n@article{A_2,year={3}}\n"
        )
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


class TestRegenerate:
    def test_regenerate_applies_generated_keys(self) -> None:
        lib = parse_bib(
            "@article{old1,\n  author = {John Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("old1", "Smith2020Data")]
        assert "Smith2020Data" in lib.entries

    def test_regenerate_disambiguates_collisions(self) -> None:
        lib = parse_bib(
            "@article{x,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n\n"
            "@article{y,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        new_keys = [n for _, n in renames]
        assert new_keys == ["Smith2020Data", "Smith2020Dataa"]
