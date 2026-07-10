"""Tests for field operations and query filters."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.fields import (
    append_field,
    clear_field,
    move_field,
    parse_query,
    protect_title_capitalization,
    rename_field,
)

_LIB = (
    "@article{A,\n  journal = {Nature},\n  year = {2020},\n  keywords = {ml}\n}\n\n"
    "@book{B,\n  title = {The {DNA} Helix},\n  year = {2021}\n}\n"
)


class TestRename:
    def test_rename_field_preserves_value_and_position(self) -> None:
        lib = parse_bib(_LIB)
        count = rename_field(lib, "journal", "journaltitle")
        assert count == 1
        e = lib.entries["A"]
        assert e.fields["journaltitle"] == "Nature"
        assert "journal" not in e.fields
        out = write_bib(lib)
        assert "journaltitle = {Nature}" in out
        # Capitalization braces in the untouched entry survive.
        assert "The {DNA} Helix" in out

    def test_rename_only_where_filter_matches(self) -> None:
        lib = parse_bib(_LIB)
        count = rename_field(lib, "year", "date", where=parse_query("type = book"))
        assert count == 1
        assert "date" in lib.entries["B"].fields
        assert "year" in lib.entries["A"].fields

    def test_rename_matches_old_name_case_insensitively(self) -> None:
        # A field name typed with different casing than the stored key (e.g.
        # copied verbatim from a lint warning) must still be found.
        lib = parse_bib(_LIB)
        count = rename_field(lib, "Journal", "eprint")
        assert count == 1
        assert lib.entries["A"].fields["eprint"] == "Nature"
        assert "journal" not in lib.entries["A"].fields


class TestMove:
    def test_move_skips_entries_with_existing_target(self) -> None:
        lib = parse_bib(
            "@article{A,\n  journal = {N},\n  journaltitle = {Existing}\n}\n\n"
            "@article{B,\n  journal = {M}\n}\n"
        )
        count = move_field(lib, "journal", "journaltitle")
        assert count == 1  # only B moved; A already has journaltitle
        assert lib.entries["A"].fields["journal"] == "N"
        assert lib.entries["B"].fields["journaltitle"] == "M"

    def test_move_matches_names_case_insensitively(self) -> None:
        lib = parse_bib(
            "@article{A,\n  journal = {N},\n  journaltitle = {Existing}\n}\n\n"
            "@article{B,\n  journal = {M}\n}\n"
        )
        count = move_field(lib, "Journal", "JournalTitle")
        assert count == 1  # only B moved; A's existing journaltitle is respected
        assert lib.entries["A"].fields["journal"] == "N"
        assert lib.entries["B"].fields["JournalTitle"] == "M"


class TestAppend:
    def test_append_dedupes(self) -> None:
        lib = parse_bib(_LIB)
        only_a = parse_query("type = article")
        assert append_field(lib, "keywords", "ml", where=only_a) == 0  # A already has it
        assert append_field(lib, "keywords", "ai", where=only_a) == 1
        assert lib.entries["A"].fields["keywords"] == "ml, ai"

    def test_append_creates_field(self) -> None:
        lib = parse_bib(_LIB)
        append_field(lib, "keywords", "physics", where=parse_query("title contains DNA"))
        assert lib.entries["B"].fields["keywords"] == "physics"

    def test_append_matches_existing_field_case_insensitively(self) -> None:
        lib = parse_bib(_LIB)
        only_a = parse_query("type = article")
        count = append_field(lib, "Keywords", "ai", where=only_a)
        assert count == 1
        assert lib.entries["A"].fields["keywords"] == "ml, ai"


class TestClear:
    def test_clear_removes_field(self) -> None:
        lib = parse_bib(_LIB)
        count = clear_field(lib, "keywords")
        assert count == 1
        assert "keywords" not in lib.entries["A"].fields
        assert "keywords = {ml}" not in write_bib(lib)

    def test_clear_matches_field_name_case_insensitively(self) -> None:
        lib = parse_bib(_LIB)
        count = clear_field(lib, "Keywords")
        assert count == 1
        assert "keywords" not in lib.entries["A"].fields


class TestTitleCapitalizationProtection:
    def test_protects_acronyms_and_mixed_case_terms(self) -> None:
        lib = parse_bib(
            "@article{A,\n"
            "  title = {DNA repair with GPT-4, LaTeX, eBay and Machine Learning},\n"
            "  year = {2024}\n"
            "}\n"
        )

        count = protect_title_capitalization(lib)

        assert count == 1
        assert (
            lib.entries["A"].fields["title"]
            == "{DNA} repair with {GPT-4}, {LaTeX}, {eBay} and Machine Learning"
        )
        out = write_bib(lib)
        assert "title = {{DNA} repair with {GPT-4}, {LaTeX}, {eBay} and Machine Learning}" in out

    def test_hyphenated_title_case_words_are_not_false_positive_mixed_case(self) -> None:
        lib = parse_bib("@article{A,\n  title = {Post-Processing Methods}\n}\n")

        assert protect_title_capitalization(lib) == 0
        assert lib.entries["A"].fields["title"] == "Post-Processing Methods"

    def test_preserves_existing_braces_and_is_idempotent(self) -> None:
        lib = parse_bib(
            "@article{A,\n  title = {The {NASA} study of mRNA and DNA},\n  year = {2024}\n}\n"
        )

        assert protect_title_capitalization(lib) == 1
        assert lib.entries["A"].fields["title"] == "The {NASA} study of {mRNA} and {DNA}"
        assert protect_title_capitalization(lib) == 0
        assert lib.entries["A"].fields["title"] == "The {NASA} study of {mRNA} and {DNA}"

    def test_can_protect_explicit_terms_and_other_title_fields(self) -> None:
        lib = parse_bib(
            "@inproceedings{A,\n"
            "  title = {A paper},\n"
            "  booktitle = {Proceedings of JabRefConf},\n"
            "  year = {2024}\n"
            "}\n"
        )

        count = protect_title_capitalization(lib, field="booktitle", terms=["Proceedings"])

        assert count == 1
        assert lib.entries["A"].fields["title"] == "A paper"
        assert lib.entries["A"].fields["booktitle"] == "{Proceedings} of {JabRefConf}"

    def test_where_filter_limits_protection(self) -> None:
        lib = parse_bib(
            "@article{A,\n  title = {DNA repair},\n  year = {2024}\n}\n\n"
            "@book{B,\n  title = {DNA repair},\n  year = {2024}\n}\n"
        )

        count = protect_title_capitalization(lib, where=parse_query("type = article"))

        assert count == 1
        assert lib.entries["A"].fields["title"] == "{DNA} repair"
        assert lib.entries["B"].fields["title"] == "DNA repair"


class TestQueryFilter:
    def test_contains(self) -> None:
        f = parse_query('title contains "digital currency"')
        from pynakes.model import BibEntry

        assert f(BibEntry("k", "article", {"title": "On Digital Currency Today"}))
        assert not f(BibEntry("k", "article", {"title": "On Cash"}))

    def test_equals_and_type(self) -> None:
        from pynakes.model import BibEntry

        assert parse_query("type = book")(BibEntry("k", "book", {}))
        assert not parse_query("year = 2020")(BibEntry("k", "article", {"year": "2021"}))

    def test_exists(self) -> None:
        from pynakes.model import BibEntry

        f = parse_query("doi exists")
        assert f(BibEntry("k", "article", {"doi": "x"}))
        assert not f(BibEntry("k", "article", {}))

    def test_key_is_queryable(self) -> None:
        # `key` targets the citation key, so an agent can edit one entry by key
        # (the resolution the dedupe-merge conflict's `manual_edit` option needs).
        from pynakes.model import BibEntry

        eq = parse_query('key == "Smith2020"')
        assert eq(BibEntry("Smith2020", "article", {}))
        assert not eq(BibEntry("Jones2021", "article", {}))
        assert parse_query("key exists")(BibEntry("Smith2020", "article", {}))

    def test_key_filter_selects_single_entry(self) -> None:
        lib = parse_bib("@article{A,\n  year = {2020}\n}\n\n@article{B,\n  year = {2021}\n}\n")
        count = append_field(lib, "keywords", "x", where=parse_query('key == "B"'))
        assert count == 1
        assert "keywords" not in lib.entries["A"].fields
        assert lib.entries["B"].fields["keywords"] == "x"

    def test_invalid_query_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_query("this is not valid >< syntax")
