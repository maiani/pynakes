"""Tests for BibTeX → BibLaTeX conversion."""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.convert import convert, convert_to_biblatex, convert_to_bibtex
from pynakes.model import BibEntry, BibFile

FIXTURES = Path(__file__).parent / "fixtures"


def _load() -> BibFile:
    return parse_bib((FIXTURES / "bibtex_classic.bib").read_text())


def _load_biblatex() -> BibFile:
    return parse_bib((FIXTURES / "biblatex_sample.bib").read_text())


class TestFieldMappings:
    def test_journal_becomes_journaltitle(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Smith2020"]
        assert "journal" not in entry.fields
        assert entry.fields["journaltitle"] == "Nature Machine Intelligence"

    def test_address_becomes_location(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Jones2021"]
        assert "address" not in entry.fields
        assert entry.fields["location"] == "Cambridge, MA"

    def test_school_becomes_institution(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Green2023"]
        assert "school" not in entry.fields
        assert entry.fields["institution"] == "Stanford University"

    def test_existing_target_is_not_clobbered(self) -> None:
        lib = _load()
        result = convert_to_biblatex(lib)
        entry = lib.entries["Conflict2018"]
        # Both journal and journaltitle were present; leave both as-is.
        assert entry.fields["journal"] == "Old Journal"
        assert entry.fields["journaltitle"] == "New Journal"
        assert any(w["type"] == "field_conflict" for w in result.warnings)

    def test_rename_preserves_field_position(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        keys = list(lib.entries["Smith2020"].fields)
        # journaltitle should sit where journal was (3rd field).
        assert keys[2] == "journaltitle"


class TestTypeMappings:
    def test_phdthesis_to_thesis(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Green2023"]
        assert entry.type == "thesis"
        assert entry.fields["type"] == "phdthesis"

    def test_mastersthesis_to_thesis(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Lee2019"]
        assert entry.type == "thesis"
        assert entry.fields["type"] == "mathesis"

    def test_type_change_reflected_in_output(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        text = write_bib(lib)
        assert "@thesis{Green2023," in text
        assert "@phdthesis{Green2023," not in text


class TestDateCombination:
    def test_year_and_month_name_combine(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Smith2020"]
        assert entry.fields["date"] == "2020-03"
        assert "year" not in entry.fields
        assert "month" not in entry.fields

    def test_numeric_month_combine(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Lee2019"]
        assert entry.fields["date"] == "2019-06"

    def test_existing_date_is_preserved(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["HasDate2022"]
        assert entry.fields["date"] == "2022-07-15"
        assert entry.fields["year"] == "2022"

    def test_year_alone_becomes_date(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        entry = lib.entries["Jones2021"]
        assert entry.fields["date"] == "2021"
        assert "year" not in entry.fields

    def test_unparseable_month_left_untouched(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(
                    key="Weird2020",
                    type="article",
                    fields={"year": "2020", "month": "spring"},
                )
            ]
        )
        result = convert_to_biblatex(lib)
        entry = lib.entries["Weird2020"]
        assert entry.fields["year"] == "2020"
        assert entry.fields["month"] == "spring"
        assert "date" not in entry.fields
        assert any(w["type"] == "unparsed_month" for w in result.warnings)


class TestPreservation:
    def test_unknown_fields_preserved(self) -> None:
        lib = _load()
        convert_to_biblatex(lib)
        assert lib.entries["Smith2020"].fields["customfield"] == "keep me"

    def test_unmodified_entry_round_trips_byte_for_byte(self) -> None:
        lib = _load()
        original = lib.entries["HasDate2022"].raw_content
        convert_to_biblatex(lib)
        # HasDate2022 only had year+date+booktitle: no journal/address/school,
        # date already present, type already biblatex → nothing should change.
        assert lib.entries["HasDate2022"].raw_content == original

    def test_report_counts(self) -> None:
        lib = _load()
        result = convert_to_biblatex(lib)
        # Smith, Jones, Green, Lee, Conflict change; HasDate2022 does not.
        assert result.target == "biblatex"
        assert result.entries == 5
        assert result.types_changed == 2  # Green, Lee
        assert result.dates_changed == 5  # every entry with year and no date
        assert result.fields_renamed == 4  # Smith journal, Jones address, Green+Lee school


class TestToBibtex:
    def test_journaltitle_becomes_journal(self) -> None:
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        entry = lib.entries["FormattedArticle2020"]
        assert "journaltitle" not in entry.fields
        assert entry.fields["journal"] == "Journal of Artificial Intelligence"

    def test_location_becomes_address(self) -> None:
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        entry = lib.entries["FormattedBook2021"]
        assert "location" not in entry.fields
        assert entry.fields["address"] == "New York, NY"

    def test_thesis_reverts_to_phdthesis(self) -> None:
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        entry = lib.entries["FormattedThesis2023"]
        assert entry.type == "phdthesis"
        assert "type" not in entry.fields
        # institution -> school for theses.
        assert entry.fields["school"] == "MIT"
        assert "institution" not in entry.fields

    def test_date_splits_into_year_and_month(self) -> None:
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        entry = lib.entries["FormattedConf2022"]
        assert entry.fields["year"] == "2022"
        assert entry.fields["month"] == "jul"
        assert "date" not in entry.fields

    def test_date_with_day_preserves_day(self) -> None:
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        entry = lib.entries["WebSource2024"]
        assert entry.fields["year"] == "2024"
        assert entry.fields["month"] == "jan"
        assert entry.fields["day"] == "15"

    def test_existing_year_is_preserved(self) -> None:
        # FormattedArticle2020 has year=2020 and no date → year stays untouched.
        lib = _load_biblatex()
        convert_to_bibtex(lib)
        assert lib.entries["FormattedArticle2020"].fields["year"] == "2020"

    def test_unmapped_thesis_left_with_warning(self) -> None:
        lib = BibFile(entries=[BibEntry(key="T", type="thesis", fields={"title": "X"})])
        result = convert_to_bibtex(lib)
        assert lib.entries["T"].type == "thesis"
        assert any(w["type"] == "unmapped_thesis" for w in result.warnings)

    def test_report_target(self) -> None:
        lib = _load_biblatex()
        result = convert_to_bibtex(lib)
        assert result.target == "bibtex"


class TestDispatch:
    def test_convert_dispatches_by_target(self) -> None:
        lib = _load()
        assert convert(lib, "biblatex").target == "biblatex"

    def test_unknown_target_raises(self) -> None:
        lib = _load()
        with pytest.raises(ValueError):
            convert(lib, "endnote")


class TestRoundTrip:
    def test_bibtex_to_biblatex_and_back(self) -> None:
        lib = _load()
        convert(lib, "biblatex")
        convert(lib, "bibtex")

        article = lib.entries["Smith2020"]
        assert article.fields["journal"] == "Nature Machine Intelligence"
        assert article.fields["year"] == "2020"
        assert article.fields["month"] == "mar"
        assert "journaltitle" not in article.fields
        assert "date" not in article.fields

        thesis = lib.entries["Green2023"]
        assert thesis.type == "phdthesis"
        assert thesis.fields["school"] == "Stanford University"
        assert "institution" not in thesis.fields
        assert "type" not in thesis.fields
