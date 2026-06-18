"""Tests for field operations and query filters."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.fields import (
    append_field,
    clear_field,
    move_field,
    parse_query,
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
        count = rename_field(lib, "year", "date", where=parse_query('type = book'))
        assert count == 1
        assert "date" in lib.entries["B"].fields
        assert "year" in lib.entries["A"].fields


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


class TestClear:
    def test_clear_removes_field(self) -> None:
        lib = parse_bib(_LIB)
        count = clear_field(lib, "keywords")
        assert count == 1
        assert "keywords" not in lib.entries["A"].fields
        assert "keywords = {ml}" not in write_bib(lib)


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

    def test_invalid_query_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_query("this is not valid >< syntax")
