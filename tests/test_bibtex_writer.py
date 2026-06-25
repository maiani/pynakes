"""Tests for BibTeX writer."""

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.model import BibEntry, BibFile


class TestBasicWriting:
    """Test basic BibTeX writing."""

    def test_write_single_entry(self) -> None:
        """Test writing a single entry."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={
                "author": "John Smith",
                "title": "A Paper",
                "journal": "Nature",
                "year": "2020",
            },
        )
        lib = BibFile(entries={"Smith2020": entry})
        output = write_bib(lib)

        assert "@article{Smith2020" in output
        assert "John Smith" in output
        assert "A Paper" in output
        assert "Nature" in output

    def test_write_multiple_entries(self) -> None:
        """Test writing multiple entries."""
        entries = {
            "Smith2020": BibEntry(
                key="Smith2020",
                type="article",
                fields={"author": "John", "title": "P1", "journal": "J", "year": "2020"},
            ),
            "Jones2021": BibEntry(
                key="Jones2021",
                type="book",
                fields={"author": "Jane", "title": "Book", "publisher": "Pub", "year": "2021"},
            ),
        }
        lib = BibFile(entries=entries)
        output = write_bib(lib)

        assert "@article{Smith2020" in output
        assert "@book{Jones2021" in output

    def test_write_strings(self) -> None:
        """Test writing @string definitions."""
        lib = BibFile(
            entries={},
            strings={"IEEE": "IEEE Transactions", "ACM": "ACM Review"},
        )
        output = write_bib(lib)

        assert "@string{IEEE" in output
        assert "@string{ACM" in output

    def test_write_preamble(self) -> None:
        """Test writing @preamble."""
        lib = BibFile(entries={}, preamble=["@preamble{Acknowledgments}"])
        output = write_bib(lib)

        assert "@preamble{Acknowledgments}" in output

    def test_write_comments(self) -> None:
        """Test writing comments."""
        lib = BibFile(
            entries={},
            raw_comments=["% BibTeX file", "% Created by pynakes"],
        )
        output = write_bib(lib)

        assert "% BibTeX file" in output
        assert "% Created by pynakes" in output


class TestRoundTrip:
    """Test round-trip parsing and writing."""

    def test_roundtrip_preserves_unmodified(self) -> None:
        """Test that unmodified entries use raw_content."""
        original = """@article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }"""

        lib = parse_bib(original)
        output = write_bib(lib)

        # Raw content should be preserved
        assert "@article{Smith2020" in output
        assert "John Smith" in output

    def test_roundtrip_modifies_when_changed(self) -> None:
        """Test that modified entries are reconstructed."""
        original = """@article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }"""

        lib = parse_bib(original)
        lib.entries["Smith2020"].fields["doi"] = "10.1234/example"
        lib.entries["Smith2020"].modified = True

        output = write_bib(lib)

        assert "Smith2020" in output
        assert "10.1234/example" in output


class TestModifiedEntryFidelity:
    """Reconstruction of modified entries must not corrupt data."""

    def test_capitalization_braces_preserved(self) -> None:
        """Inner braces (capitalization protection) must round-trip intact."""
        original = "@article{k,\n  title = {The {DNA} Helix},\n  year = {1953}\n}\n"
        lib = parse_bib(original)
        # Touch the entry so it takes the reconstruction path.
        lib.entries["k"].modified = True

        reparsed = parse_bib(write_bib(lib))
        assert reparsed.entries["k"].fields["title"] == "The {DNA} Helix"

    def test_field_order_preserved(self) -> None:
        """Reconstructed entries keep their original field order."""
        original = "@article{k,\n  title = {T},\n  author = {A},\n  year = {2020}\n}\n"
        lib = parse_bib(original)
        lib.entries["k"].modified = True

        reparsed = parse_bib(write_bib(lib))
        assert list(reparsed.entries["k"].fields.keys()) == ["title", "author", "year"]

    def test_empty_field_value_preserved(self) -> None:
        """A field with an empty value is not silently dropped."""
        lib = parse_bib("@article{k,\n  note = {},\n  year = {2020}\n}\n")
        assert "note" in lib.entries["k"].fields
        assert lib.entries["k"].fields["note"] == ""

    def test_roundtrip_multiple_entries(self) -> None:
        """Test round-trip with multiple entries."""
        original = """@article{A2020,
          author = {A},
          title = {Title A},
          journal = {Journal},
          year = {2020}
        }

        @article{B2021,
          author = {B},
          title = {Title B},
          journal = {Journal},
          year = {2021}
        }"""

        lib = parse_bib(original)
        output = write_bib(lib)

        assert "@article{A2020" in output
        assert "@article{B2021" in output
        assert "Title A" in output
        assert "Title B" in output


class TestWholeFileLayoutFidelity:
    """An unmodified file must write back byte-for-byte, preserving the exact
    top-level ordering and the whitespace between blocks."""

    def test_blank_lines_between_entries_preserved(self) -> None:
        src = "@article{a,\n  title = {A},\n}\n\n\n@book{b,\n  title = {B},\n}\n"
        assert write_bib(parse_bib(src)) == src

    def test_trailing_metadata_not_relocated_to_top(self) -> None:
        # JabRef writes metadata comments at the end; they must stay there.
        src = (
            "@article{a,\n  title = {A},\n  year = {2020},\n}\n\n"
            "@comment{jabref-meta: databaseType:bibtex;}\n"
        )
        assert write_bib(parse_bib(src)) == src

    def test_interleaved_comment_string_entry_order_preserved(self) -> None:
        src = (
            "% a leading line comment\n\n"
            "@string{j = {Jrnl}}\n\n"
            "@article{a,\n  journal = j,\n  title = {A},\n}\n\n"
            "@comment{jabref-meta: databaseType:bibtex;}\n"
        )
        assert write_bib(parse_bib(src)) == src

    def test_crlf_whole_file_round_trip(self) -> None:
        src = "@article{a,\r\n  title = {A},\r\n}\r\n\r\n@book{b,\r\n  title = {B},\r\n}\r\n"
        assert write_bib(parse_bib(src)) == src

    def test_in_place_edit_changes_only_edited_entry(self) -> None:
        src = "@article{a,\n  title = {A},\n  year = {2020}\n}\n\n@book{b,\n  title = {B}\n}\n"
        lib = parse_bib(src)
        lib.entries["b"].fields["title"] = "B revised"
        lib.entries["b"].modified = True

        output = write_bib(lib)
        # Entry a and the blank-line spacing are untouched; only b changes.
        assert "@article{a,\n  title = {A},\n  year = {2020}\n}\n\n@book{b," in output
        assert "B revised" in output

    def test_added_entry_falls_back_to_canonical_layout(self) -> None:
        # A structural change invalidates the recorded positions; the writer
        # must still emit every block (here via the derived canonical layout).
        src = "@article{a,\n  title = {A},\n}\n"
        lib = parse_bib(src)
        lib.entries.add(BibEntry(key="b", type="book", fields={"title": "B"}))

        output = write_bib(lib)
        assert "@article{a" in output
        assert "@book{b" in output
        assert "B" in output


class TestLineEndings:
    """Test line ending preservation."""

    def test_preserve_unix_line_endings(self) -> None:
        """Test preserving Unix line endings."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibFile(entries={"Test": entry}, line_ending="\n")
        output = write_bib(lib)

        assert "\r\n" not in output
        assert "\n" in output

    def test_preserve_windows_line_endings(self) -> None:
        """Test preserving Windows line endings."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibFile(entries={"Test": entry}, line_ending="\r\n")
        output = write_bib(lib)

        assert "\r\n" in output


class TestFieldFormatting:
    """Test field formatting."""

    def test_quote_field_values(self) -> None:
        """Test that field values are properly quoted."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={
                "author": "John Smith",
                "title": "A Paper",
                "journal": "Nature",
                "year": "2020",
            },
        )
        lib = BibFile(entries={"Test": entry})
        output = write_bib(lib)

        # Values should be in braces or quotes
        assert "{" in output
        assert "}" in output

    def test_escape_special_characters(self) -> None:
        """Test escaping of special characters."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={
                "author": "John Smith",
                "title": "Testing {braces} in title",
                "journal": "Nature",
                "year": "2020",
            },
        )
        lib = BibFile(entries={"Test": entry})
        output = write_bib(lib)

        # Should escape braces
        assert "{{" in output or "{braces}" in output


class TestSpecialCases:
    """Test special cases and edge cases."""

    def test_empty_library(self) -> None:
        """Test writing empty library."""
        lib = BibFile(entries={})
        output = write_bib(lib)

        # Should not crash
        assert isinstance(output, str)

    def test_entry_without_modified_flag(self) -> None:
        """Test entries without modified flag set."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
            raw_content="@article{Test, author={A}, ...}",
        )
        lib = BibFile(entries={"Test": entry})
        output = write_bib(lib)

        # Should use raw_content
        assert "@article{Test" in output

    def test_entry_without_raw_content(self) -> None:
        """Test entries created without raw_content."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
            raw_content=None,
        )
        lib = BibFile(entries={"Test": entry})
        output = write_bib(lib)

        # Should reconstruct from fields
        assert "@article{Test" in output
        assert "author" in output.lower()

    def test_newline_at_eof(self) -> None:
        """Test that output ends with newline."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibFile(entries={"Test": entry})
        output = write_bib(lib)

        assert output.endswith("\n")
