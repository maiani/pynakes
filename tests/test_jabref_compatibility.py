"""JabRef compatibility tests.

Tests to ensure pynakes can:
1. Parse JabRef-generated BibTeX files correctly
2. Preserve JabRef-specific metadata (groups, file attachments, keywords)
3. Export in formats compatible with JabRef
"""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.io import load_bib, save_bib
from pynakes.model import BibEntry, BibLibrary


@pytest.fixture
def fixtures_dir() -> Path:
    """Get path to test fixtures."""
    return Path(__file__).parent / "fixtures"


class TestJabRefGroupsMetadata:
    """Test preservation of JabRef group metadata."""

    def test_parse_jabref_groups_comments(self) -> None:
        """Test that JabRef group comments are preserved."""
        text = """
        @comment{jabref-meta: groupsversion:3;}
        @comment{jabref-meta: groups:0 All Papers:;}
        @comment{jabref-meta: groups:1 AI\\:Machine Learning:;}
        """
        lib = parse_bib(text)

        assert len(lib.raw_comments) > 0
        assert any("jabref-meta" in c for c in lib.raw_comments)

    def test_parse_jabref_groups_field(self) -> None:
        """Test that entries with groups field are parsed correctly."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {Machine Learning Paper},
          journal = {Nature},
          year = {2020},
          groups = {AI Papers; Machine Learning}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Smith2020"]
        assert "groups" in entry.fields
        assert "AI Papers" in entry.fields["groups"]
        assert "Machine Learning" in entry.fields["groups"]

    def test_preserve_groups_field_on_roundtrip(self) -> None:
        """Test that groups field is preserved through write-parse cycle."""
        original_text = """@article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020},
          groups = {Group1; Group2; Group3}
        }"""

        # Parse
        lib1 = parse_bib(original_text)
        assert lib1.entries["Test2020"].fields["groups"] == "Group1; Group2; Group3"

        # Write
        output = write_bib(lib1)

        # Re-parse
        lib2 = parse_bib(output)
        assert lib2.entries["Test2020"].fields["groups"] == "Group1; Group2; Group3"

    def test_fixture_jabref_groups_file(self, fixtures_dir: Path) -> None:
        """Test parsing the JabRef groups fixture file."""
        fixture = fixtures_dir / "jabref_groups.bib"
        assert fixture.exists()

        with open(fixture) as f:
            lib = parse_bib(f.read())

        # Should have parsed all entries
        assert len(lib.entries) == 4

        # All entries should have groups
        for entry in lib.entries.values():
            assert "groups" in entry.fields
            assert ";" in entry.fields["groups"]  # Multiple groups separated by semicolon


class TestJabRefFileAttachments:
    """Test preservation of JabRef file attachments and metadata."""

    def test_parse_file_field(self) -> None:
        """Test parsing entries with file field."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {Paper},
          journal = {Journal},
          year = {2020},
          file = {/home/user/papers/Smith2020.pdf}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Smith2020"]
        assert "file" in entry.fields
        assert "Smith2020.pdf" in entry.fields["file"]

    def test_parse_jabref_file_descriptor(self) -> None:
        """Test parsing JabRef-style file descriptors with format spec."""
        text = """
        @article{Jones2021,
          author = {Jane Jones},
          title = {Paper},
          journal = {Journal},
          year = {2021},
          file = {Jones2021.pdf:papers/Jones2021.pdf:PDF}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Jones2021"]
        assert "file" in entry.fields
        # JabRef format: name:path:format
        assert ":" in entry.fields["file"]

    def test_preserve_file_field_on_roundtrip(self) -> None:
        """Test that file field is preserved through roundtrip."""
        original_text = """@article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020},
          file = {Test2020.pdf:papers/Test2020.pdf:PDF}
        }"""

        lib1 = parse_bib(original_text)
        output = write_bib(lib1)
        lib2 = parse_bib(output)

        assert lib2.entries["Test2020"].fields["file"] == "Test2020.pdf:papers/Test2020.pdf:PDF"

    def test_fixture_linked_files_file(self, fixtures_dir: Path) -> None:
        """Test parsing the linked files fixture file."""
        fixture = fixtures_dir / "linked_files.bib"
        assert fixture.exists()

        with open(fixture) as f:
            lib = parse_bib(f.read())

        # All entries should have file field
        assert len(lib.entries) == 4
        for entry in lib.entries.values():
            assert "file" in entry.fields


class TestJabRefKeywords:
    """Test preservation of JabRef keywords field."""

    def test_parse_keywords_field(self) -> None:
        """Test parsing entries with keywords field."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {Paper},
          journal = {Journal},
          year = {2020},
          keywords = {machine learning, neural networks, deep learning}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Smith2020"]
        assert "keywords" in entry.fields
        assert "machine learning" in entry.fields["keywords"]

    def test_preserve_keywords_on_roundtrip(self) -> None:
        """Test that keywords are preserved through roundtrip."""
        original_text = """@article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020},
          keywords = {keyword1, keyword2, keyword3}
        }"""

        lib1 = parse_bib(original_text)
        output = write_bib(lib1)
        lib2 = parse_bib(output)

        assert lib2.entries["Test2020"].fields["keywords"] == "keyword1, keyword2, keyword3"


class TestJabRefAbstracts:
    """Test preservation of JabRef abstracts and full entries."""

    def test_parse_abstract_field(self) -> None:
        """Test parsing entries with abstract field."""
        text = """
        @article{Smith2020,
          author = {John Smith},
          title = {Paper},
          journal = {Journal},
          year = {2020},
          abstract = {This is a comprehensive study on the topic.}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Smith2020"]
        assert "abstract" in entry.fields

    def test_preserve_multiline_abstract(self) -> None:
        """Test that multiline abstracts are preserved."""
        original_text = """@article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020},
          abstract = {This is a long abstract that might span
                      multiple lines in the original file.}
        }"""

        lib1 = parse_bib(original_text)
        output = write_bib(lib1)
        lib2 = parse_bib(output)

        # Abstract should still be there (might be reformatted)
        assert "abstract" in lib2.entries["Test2020"].fields


class TestRoundTripFidelity:
    """Test round-trip fidelity with JabRef files."""

    def test_roundtrip_simple_jabref_file(self, fixtures_dir: Path, tmp_path: Path) -> None:
        """Test round-trip with JabRef groups fixture."""
        fixture = fixtures_dir / "jabref_groups.bib"
        output_file = tmp_path / "roundtrip.bib"

        # Load
        lib1 = load_bib(str(fixture))
        original_entry_count = len(lib1.entries)

        # Save
        save_bib(lib1, str(output_file))

        # Load again
        lib2 = load_bib(str(output_file))

        # Should have same number of entries
        assert len(lib2.entries) == original_entry_count

        # All groups should be preserved
        for key in lib1.entries:
            assert lib2.entries[key].fields["groups"] == lib1.entries[key].fields["groups"]

    def test_roundtrip_linked_files(self, fixtures_dir: Path, tmp_path: Path) -> None:
        """Test round-trip with linked files fixture."""
        fixture = fixtures_dir / "linked_files.bib"
        output_file = tmp_path / "linked_roundtrip.bib"

        # Load
        lib1 = load_bib(str(fixture))

        # Save
        save_bib(lib1, str(output_file))

        # Load again
        lib2 = load_bib(str(output_file))

        # All entries should still have file field
        for key in lib1.entries:
            assert "file" in lib2.entries[key].fields
            assert lib2.entries[key].fields["file"] == lib1.entries[key].fields["file"]

    def test_roundtrip_preserves_entry_order(self, tmp_path: Path) -> None:
        """Test that entry order is mostly preserved (within reason)."""
        text = """
        @article{A2020,
          author = {A},
          title = {A},
          journal = {J},
          year = {2020}
        }
        @article{B2021,
          author = {B},
          title = {B},
          journal = {J},
          year = {2021}
        }
        @article{C2022,
          author = {C},
          title = {C},
          journal = {J},
          year = {2022}
        }
        """

        lib1 = parse_bib(text)
        keys1 = list(lib1.entries.keys())

        output = write_bib(lib1)
        lib2 = parse_bib(output)
        keys2 = list(lib2.entries.keys())

        # Entry order should be preserved (keys should be in same order)
        assert keys1 == keys2


class TestJabRefSpecialCharacters:
    """Test handling of special characters in JabRef files."""

    def test_parse_accented_characters(self) -> None:
        """Test parsing entries with accented characters."""
        text = """
        @article{García2020,
          author = {José García and François Müller},
          title = {Étude sur les caractères spéciaux},
          journal = {Revista Científica},
          year = {2020}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["García2020"]
        assert "García" in entry.fields["author"]
        assert "Müller" in entry.fields["author"]

    def test_parse_entries_with_special_chars_in_values(self) -> None:
        """Test entries with special characters in field values."""
        text = """
        @article{Test2020,
          author = {Smith, J. & Jones, A.},
          title = {A Title with {Special} Characters & Symbols},
          journal = {Journal},
          year = {2020}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Test2020"]
        assert "&" in entry.fields["author"]
        assert "{Special}" in entry.fields["title"]


class TestJabRefComments:
    """Test preservation of JabRef comments."""

    def test_parse_jabref_comments(self) -> None:
        """Test that JabRef-style comments are preserved."""
        text = """
        % This is a regular comment
        @comment{jabref-meta: groupsversion:3;}

        @article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020}
        }
        % Another comment
        """
        lib = parse_bib(text)

        # Should have captured comments
        assert len(lib.raw_comments) > 0

    def test_comments_preserved_in_roundtrip(self) -> None:
        """Test that comments are preserved through roundtrip."""
        text = """
        % File header comment
        @article{Test2020,
          author = {Author},
          title = {Title},
          journal = {Journal},
          year = {2020}
        }
        % End comment
        """
        lib1 = parse_bib(text)

        output = write_bib(lib1)
        lib2 = parse_bib(output)

        # Should still have comments
        assert len(lib2.raw_comments) > 0


class TestExportFormatCompatibility:
    """Test that exported format is compatible with JabRef."""

    def test_exported_format_is_valid_bibtex(self) -> None:
        """Test that exported files are valid BibTeX."""
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={
                "author": "John Smith",
                "title": "A Test Paper",
                "journal": "Test Journal",
                "year": "2020",
                "groups": "Test Group",
            },
        )
        lib = BibLibrary(entries={"Test2020": entry})

        output = write_bib(lib)

        # Should be valid BibTeX that can be re-parsed
        lib2 = parse_bib(output)
        assert len(lib2.entries) == 1
        assert lib2.entries["Test2020"].type == "article"

    def test_exported_format_has_proper_structure(self) -> None:
        """Test that exported format has proper BibTeX structure."""
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={
                "author": "Author",
                "title": "Title",
                "journal": "Journal",
                "year": "2020",
            },
        )
        lib = BibLibrary(entries={"Test2020": entry})

        output = write_bib(lib)

        # Should have proper BibTeX syntax
        assert "@article{Test2020," in output
        assert "author = " in output
        assert "}" in output
        assert output.count("{") == output.count("}")

    def test_exported_format_with_metadata(self) -> None:
        """Test that exported format preserves JabRef metadata fields."""
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={
                "author": "Author",
                "title": "Title",
                "journal": "Journal",
                "year": "2020",
                "groups": "Group1; Group2",
                "keywords": "keyword1, keyword2",
                "abstract": "An abstract.",
                "file": "test.pdf:path/test.pdf:PDF",
            },
        )
        lib = BibLibrary(entries={"Test2020": entry})

        output = write_bib(lib)
        lib2 = parse_bib(output)

        # All metadata should be preserved
        for field in ["groups", "keywords", "abstract", "file"]:
            assert field in lib2.entries["Test2020"].fields
            assert (
                lib2.entries["Test2020"].fields[field]
                == entry.fields[field]
            )


class TestJabRefBiblatexConversion:
    """Test BibLaTeX compatibility with JabRef."""

    def test_jabref_file_in_biblatex_format(self, fixtures_dir: Path) -> None:
        """Test parsing BibLaTeX formatted fixture files."""
        fixture = fixtures_dir / "biblatex_sample.bib"
        assert fixture.exists()

        with open(fixture) as f:
            lib = parse_bib(f.read())

        # Should parse all entries
        assert len(lib.entries) > 0

        # BibLaTeX-specific fields should be preserved
        # Just check that all entries parsed correctly
        for entry in lib.entries.values():
            # Verify entry has required fields for its type
            assert entry.key
            assert entry.type
            assert entry.fields


class TestJabRefMultipleGroupsAndFiles:
    """Test complex scenarios with multiple groups and file attachments."""

    def test_entry_with_multiple_groups(self) -> None:
        """Test entries with complex group hierarchies."""
        text = """
        @article{Complex2020,
          author = {Complex Author},
          title = {Title},
          journal = {Journal},
          year = {2020},
          groups = {Group1; Group2\\:Subgroup; Group3},
          keywords = {key1, key2, key3},
          file = {complex1.pdf:path/complex1.pdf:PDF; complex2.pdf:path/complex2.pdf:PDF}
        }
        """
        lib = parse_bib(text)

        entry = lib.entries["Complex2020"]
        assert "groups" in entry.fields
        assert "keywords" in entry.fields
        assert "file" in entry.fields

    def test_preserve_complex_metadata(self) -> None:
        """Test that complex JabRef metadata is preserved."""
        original_text = """@article{Complex2020,
          author = {Author Name},
          title = {Complex Title},
          journal = {Journal Name},
          year = {2020},
          groups = {AI\\:Deep Learning; ML Papers},
          keywords = {neural networks, CNN, image processing},
          abstract = {A detailed abstract about the paper.},
          file = {file1.pdf:path/file1.pdf:PDF; file2.pdf:path/file2.pdf:PDF}
        }"""

        lib1 = parse_bib(original_text)
        output = write_bib(lib1)
        lib2 = parse_bib(output)

        entry1 = lib1.entries["Complex2020"]
        entry2 = lib2.entries["Complex2020"]

        # All fields should match
        for field in ["groups", "keywords", "abstract", "file"]:
            assert entry2.fields[field] == entry1.fields[field]
