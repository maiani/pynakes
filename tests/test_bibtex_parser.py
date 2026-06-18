"""Tests for BibTeX parser."""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib


@pytest.fixture
def fixtures_dir() -> Path:
    """Get path to test fixtures."""
    return Path(__file__).parent / "fixtures"


class TestBasicParsing:
    """Test basic BibTeX parsing."""

    def test_parse_simple_entry(self) -> None:
        """Test parsing a simple article."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }
        """
        lib = parse_bib(text)
        assert len(lib.entries) == 1
        entry = lib.entries["Smith2020"]
        assert entry.type == "article"
        assert entry.fields["author"] == "John Smith"
        assert entry.fields["title"] == "A Paper"

    def test_parse_multiple_entries(self) -> None:
        """Test parsing multiple entries."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {Paper 1},
          journal = {Nature},
          year = {2020}
        }

        @book{Jones2021,
          author = {Jane Jones},
          title = {Book 1},
          publisher = {MIT Press},
          year = {2021}
        }
        """
        lib = parse_bib(text)
        assert len(lib.entries) == 2
        assert "Smith2020" in lib.entries
        assert "Jones2021" in lib.entries

    def test_parse_entry_types(self) -> None:
        """Test parsing different entry types."""
        text = """
        @article{Article2020,
          author = {A},
          title = {Title},
          journal = {Journal},
          year = {2020}
        }
        @book{Book2021,
          author = {B},
          title = {Title},
          publisher = {Pub},
          year = {2021}
        }
        @inproceedings{Conf2022,
          author = {C},
          title = {Title},
          booktitle = {Conf},
          year = {2022}
        }
        @misc{Misc2023,
          author = {D},
          title = {Title},
          year = {2023}
        }
        """
        lib = parse_bib(text)
        assert lib.entries["Article2020"].type == "article"
        assert lib.entries["Book2021"].type == "book"
        assert lib.entries["Conf2022"].type == "inproceedings"
        assert lib.entries["Misc2023"].type == "misc"

    def test_parse_multiline_entry(self) -> None:
        """Test parsing entries spanning multiple lines."""
        text = """@article{Smith2020,
          author = {John Smith and Jane Doe},
          title = {A Very Long Title That Spans
                   Multiple Lines},
          journal = {Nature},
          year = {2020},
          volume = {42},
          pages = {123--145}
        }
        """
        lib = parse_bib(text)
        entry = lib.entries["Smith2020"]
        assert entry.fields["author"] == "John Smith and Jane Doe"
        assert entry.fields["volume"] == "42"

    def test_parse_ignores_comments(self) -> None:
        """Test that comments are ignored."""
        text = """
        % This is a comment
        @article{Smith2020,
          % Another comment
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }
        % Final comment
        """
        lib = parse_bib(text)
        assert len(lib.entries) == 1
        assert len(lib.raw_comments) > 0


class TestStringDefinitions:
    """Test parsing @string definitions."""

    def test_parse_string_definition(self) -> None:
        """Test parsing @string."""
        text = """
        @string{IEEE = "IEEE Transactions"}
        @string{LNCS = "Lecture Notes in Computer Science"}
        """
        lib = parse_bib(text)
        assert lib.strings["IEEE"] == "IEEE Transactions"
        assert lib.strings["LNCS"] == "Lecture Notes in Computer Science"

    def test_use_string_in_entry(self) -> None:
        """Test that strings are parsed even if not used."""
        text = """
        @string{IEEE = "IEEE Transactions"}
        @article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = IEEE,
          year = {2020}
        }
        """
        lib = parse_bib(text)
        assert "IEEE" in lib.strings
        assert lib.entries["Smith2020"].fields["journal"] == "IEEE"


class TestPreamble:
    """Test parsing @preamble."""

    def test_parse_preamble(self) -> None:
        """Test parsing @preamble."""
        text = """
        @preamble{Acknowledgments}
        @article{Smith2020,
          author = {John Smith},
          title = {Paper},
          journal = {Journal},
          year = {2020}
        }
        """
        lib = parse_bib(text)
        assert len(lib.preamble) > 0


class TestJabRefCitationKeyMetadata:
    """Test structured parsing of JabRef metadata comments."""

    def test_parse_citation_key_patterns(self) -> None:
        text = """
        @comment{jabref-meta: keypatterndefault:[auth][year];}
        @comment{jabref-meta: keypattern_article:[auth][shortyear][veryshorttitle];}

        @article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Journal},
          year = {2020}
        }
        """
        lib = parse_bib(text)
        assert lib.jabref_metadata["keypatterndefault"] == "[auth][year];"
        assert lib.jabref_metadata["keypattern_article"] == "[auth][shortyear][veryshorttitle];"

    def test_jabref_comment_round_trips_without_extra_braces(self) -> None:
        text = (
            "@comment{jabref-meta: keypatterndefault:[auth][year];}\n\n"
            "@article{Smith2020,\n"
            "  author = {John Smith},\n"
            "  title = {A Paper},\n"
            "  journal = {Journal},\n"
            "  year = {2020}\n"
            "}\n"
        )
        assert write_bib(parse_bib(text)) == text


class TestEncodingAndLineEndings:
    """Test encoding and line ending detection."""

    def test_detect_utf8_encoding(self) -> None:
        """Test UTF-8 encoding detection."""
        text = "@article{Test2020, author = {José García}, title = {Paper}, journal = {Nature}, year = {2020}}"
        lib = parse_bib(text)
        assert lib.encoding == "utf-8"

    def test_detect_unix_line_endings(self) -> None:
        """Test detecting Unix line endings."""
        text = "@article{A,\n  author = {Test},\n  title = {T},\n  year = {2020}\n}\n"
        lib = parse_bib(text)
        assert lib.line_ending == "\n"

    def test_detect_windows_line_endings(self) -> None:
        """Test detecting Windows line endings."""
        text = "@article{A,\r\n  author = {Test},\r\n  title = {T},\r\n  year = {2020}\r\n}\r\n"
        lib = parse_bib(text)
        assert lib.line_ending == "\r\n"


class TestJabRefMetadata:
    """Test JabRef metadata preservation."""

    def test_parse_jabref_groups_comment(self) -> None:
        """Test parsing JabRef groups in comments."""
        text = """
        @comment{jabref-meta: groupsversion:3;}
        @comment{jabref-meta: groups:0 All Papers:;}
        @article{Smith2020,
          author = {John Smith},
          title = {Paper},
          journal = {Journal},
          year = {2020},
          groups = {AI Papers}
        }
        """
        lib = parse_bib(text)
        assert len(lib.raw_comments) > 0


class TestRoundTrip:
    """Test round-trip parsing and reconstruction."""

    def test_roundtrip_simple_entry(self) -> None:
        """Test that parsing preserves raw_content."""
        text = """@article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }"""
        lib = parse_bib(text)
        entry = lib.entries["Smith2020"]
        assert entry.raw_content is not None
        assert "Smith2020" in entry.raw_content

    def test_roundtrip_multiple_entries(self) -> None:
        """Test round-trip with multiple entries."""
        text = """@article{A2020,
          author = {Author A},
          title = {Title A},
          journal = {Journal A},
          year = {2020}
        }

        @article{B2021,
          author = {Author B},
          title = {Title B},
          journal = {Journal B},
          year = {2021}
        }"""
        lib = parse_bib(text)
        assert len(lib.entries) == 2
        assert all(entry.raw_content for entry in lib.entries.values())


class TestFixtures:
    """Test parsing actual fixture files."""

    def test_parse_simple_fixture(self, fixtures_dir: Path) -> None:
        """Test parsing simple.bib fixture."""
        fixture = fixtures_dir / "simple.bib"
        assert fixture.exists(), f"Fixture not found: {fixture}"

        with open(fixture) as f:
            lib = parse_bib(f.read())

        assert len(lib.entries) == 5
        assert "Smith2020" in lib.entries
        assert "Jones2021" in lib.entries

    def test_parse_jabref_fixture(self, fixtures_dir: Path) -> None:
        """Test parsing jabref_groups.bib fixture."""
        fixture = fixtures_dir / "jabref_groups.bib"
        assert fixture.exists(), f"Fixture not found: {fixture}"

        with open(fixture) as f:
            lib = parse_bib(f.read())

        assert len(lib.entries) == 4
        assert all("groups" in entry.fields for entry in lib.entries.values())

    def test_parse_duplicate_fixture(self, fixtures_dir: Path) -> None:
        """Test parsing duplicate_entries.bib fixture preserves duplicates."""
        fixture = fixtures_dir / "duplicate_entries.bib"
        assert fixture.exists(), f"Fixture not found: {fixture}"

        with open(fixture) as f:
            lib = parse_bib(f.read())

        # The fixture intentionally contains repeated citation keys; all are kept.
        dupes = lib.entries.duplicate_keys()
        assert dupes, "expected duplicate keys to be detected"
        assert "Smith2020" in dupes

    def test_parse_linked_files_fixture(self, fixtures_dir: Path) -> None:
        """Test parsing linked_files.bib fixture."""
        fixture = fixtures_dir / "linked_files.bib"
        assert fixture.exists(), f"Fixture not found: {fixture}"

        with open(fixture) as f:
            lib = parse_bib(f.read())

        assert len(lib.entries) == 4
        assert all("file" in entry.fields for entry in lib.entries.values())


class TestErrorHandling:
    """Test error handling."""

    def test_duplicate_keys_preserved(self) -> None:
        """Duplicate keys are preserved (not an error) for later repair."""
        text = """
        @article{Smith2020,
          author = {John},
          title = {Paper},
          journal = {Journal},
          year = {2020}
        }
        @article{Smith2020,
          author = {Jane},
          title = {Paper 2},
          journal = {Journal},
          year = {2020}
        }
        """
        lib = parse_bib(text)

        # Both entries are retained, in order.
        assert len(lib.entries) == 2
        both = lib.entries.get_all("Smith2020")
        assert len(both) == 2
        assert both[0].fields["author"] == "John"
        assert both[1].fields["author"] == "Jane"

        # And the duplicate is reported for the linter to act on.
        assert lib.entries.duplicate_keys() == {"Smith2020": 2}

    def test_unmatched_braces_error(self) -> None:
        """Test that unmatched braces raise ParseError."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {A Paper,
          journal = {Nature},
          year = {2020}
        }
        """
        with pytest.raises(ParseError, match="Unmatched braces"):
            parse_bib(text)
