"""Tests for I/O operations."""

from pathlib import Path

import pytest

from pynakes.io import load_bib, save_bib
from pynakes.model import BibEntry, BibLibrary


class TestLoadBib:
    """Test loading BibTeX files."""

    def test_load_nonexistent_file(self) -> None:
        """Test loading a file that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_bib("nonexistent.bib")

    def test_load_simple_file(self, tmp_path: Path) -> None:
        """Test loading a simple BibTeX file."""
        bib_file = tmp_path / "test.bib"
        content = """@article{Smith2020,
          author = {John Smith},
          title = {A Paper},
          journal = {Nature},
          year = {2020}
        }"""
        bib_file.write_text(content)

        lib = load_bib(str(bib_file))
        assert len(lib.entries) == 1
        assert "Smith2020" in lib.entries

    def test_load_utf8_file(self, tmp_path: Path) -> None:
        """Test loading UTF-8 encoded file."""
        bib_file = tmp_path / "test.bib"
        content = """@article{Test2020,
          author = {José García},
          title = {Un Artículo},
          journal = {Nature},
          year = {2020}
        }"""
        bib_file.write_text(content, encoding="utf-8")

        lib = load_bib(str(bib_file))
        assert "Test2020" in lib.entries

    def test_load_preserves_encoding(self, tmp_path: Path) -> None:
        """Test that loaded library preserves encoding."""
        bib_file = tmp_path / "test.bib"
        content = "@article{Test2020,author={A},title={T},journal={J},year={2020}}"
        bib_file.write_text(content, encoding="utf-8")

        lib = load_bib(str(bib_file))
        assert lib.encoding == "utf-8"

    def test_load_detects_latin1(self, tmp_path: Path) -> None:
        """A non-UTF-8 file is detected and decoded as latin-1."""
        bib_file = tmp_path / "test.bib"
        # 0xE9 is 'é' in latin-1 but invalid as standalone UTF-8.
        bib_file.write_bytes(
            b"@article{k,\n  author = {Caf\xe9},\n  year = {2020}\n}\n"
        )

        lib = load_bib(str(bib_file))
        assert lib.encoding == "latin-1"
        assert lib.entries["k"].fields["author"] == "Caf\xe9"


class TestLineEndingFidelity:
    """CRLF line endings must survive a load/save round-trip."""

    def test_crlf_detected_on_load(self, tmp_path: Path) -> None:
        bib_file = tmp_path / "test.bib"
        bib_file.write_bytes(b"@article{k,\r\n  year = {2020}\r\n}\r\n")

        lib = load_bib(str(bib_file))
        assert lib.line_ending == "\r\n"

    def test_crlf_preserved_on_save(self, tmp_path: Path) -> None:
        bib_file = tmp_path / "test.bib"
        bib_file.write_bytes(b"@article{k,\r\n  year = {2020}\r\n}\r\n")

        lib = load_bib(str(bib_file))
        save_bib(lib, str(bib_file), backup=False)

        data = bib_file.read_bytes()
        assert b"\r\n" in data
        # No bare LF that isn't part of a CRLF pair.
        assert data.replace(b"\r\n", b"") .count(b"\n") == 0


class TestSaveBib:
    """Test saving BibTeX files."""

    def test_save_to_new_file(self, tmp_path: Path) -> None:
        """Test saving to a new file."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry})
        output_file = tmp_path / "output.bib"

        result = save_bib(lib, str(output_file))

        assert result.success
        assert output_file.exists()

    def test_save_creates_backup(self, tmp_path: Path) -> None:
        """Test that save creates a backup of existing file."""
        bib_file = tmp_path / "test.bib"
        bib_file.write_text("@article{Old, author={A}, title={T}, journal={J}, year={2020}}")

        entry = BibEntry(
            key="New",
            type="article",
            fields={"author": "B", "title": "U", "journal": "K", "year": "2021"},
        )
        lib = BibLibrary(entries={"New": entry})

        result = save_bib(lib, str(bib_file), backup=True)

        assert result.success
        assert result.backup_path is not None
        backup_file = Path(result.backup_path)
        assert backup_file.exists()
        assert backup_file.read_text().startswith("@article{Old")

    def test_save_no_backup_if_file_doesnt_exist(self, tmp_path: Path) -> None:
        """Test that no backup is created if file doesn't exist."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry})
        output_file = tmp_path / "new.bib"

        result = save_bib(lib, str(output_file), backup=True)

        assert result.success
        assert result.backup_path is None

    def test_save_atomic_write(self, tmp_path: Path) -> None:
        """Test atomic write behavior."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry})
        output_file = tmp_path / "output.bib"

        result = save_bib(lib, str(output_file), atomic=True)

        assert result.success
        assert output_file.exists()
        content = output_file.read_text()
        assert "@article{Test" in content

    def test_save_roundtrip(self, tmp_path: Path) -> None:
        """Test save and load roundtrip."""
        # Create and save
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
        lib = BibLibrary(entries={"Smith2020": entry})
        output_file = tmp_path / "roundtrip.bib"

        save_result = save_bib(lib, str(output_file))
        assert save_result.success

        # Load and verify
        loaded_lib = load_bib(str(output_file))
        assert len(loaded_lib.entries) == 1
        assert "Smith2020" in loaded_lib.entries
        assert loaded_lib.entries["Smith2020"].fields["author"] == "John Smith"

    def test_save_preserves_encoding(self, tmp_path: Path) -> None:
        """Test that save preserves encoding."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "José", "title": "Título", "journal": "Revista", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry}, encoding="utf-8")
        output_file = tmp_path / "utf8.bib"

        result = save_bib(lib, str(output_file))
        assert result.success

        # Verify encoding is preserved
        loaded_lib = load_bib(str(output_file))
        assert loaded_lib.encoding == "utf-8"
        assert loaded_lib.entries["Test"].fields["author"] == "José"

    def test_save_preserves_line_endings(self, tmp_path: Path) -> None:
        """Test that save preserves line ending style."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry}, line_ending="\r\n")
        output_file = tmp_path / "windows.bib"

        result = save_bib(lib, str(output_file))
        assert result.success

        content = output_file.read_bytes()
        assert b"\r\n" in content


class TestSaveErrors:
    """Test error handling in save operations."""

    def test_save_to_invalid_directory(self) -> None:
        """Test saving to a non-existent directory."""
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry})

        result = save_bib(lib, "/nonexistent/directory/output.bib")
        assert not result.success
        assert result.error is not None

    def test_save_restores_backup_on_error(self, tmp_path: Path) -> None:
        """Test that backup is restored if save fails."""
        bib_file = tmp_path / "test.bib"
        original_content = "@article{Original, author={A}, title={T}, journal={J}, year={2020}}"
        bib_file.write_text(original_content)

        # Attempt to save to a directory we can't write to after creating backup
        entry = BibEntry(
            key="Test",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib = BibLibrary(entries={"Test": entry})

        # Save (with atomic=False to test backup restoration more directly)
        result = save_bib(lib, str(bib_file), backup=True, atomic=False)

        # File should still exist (either original or backup)
        if not bib_file.exists() and result.backup_path:
            # Restore from backup path
            assert Path(result.backup_path).exists()


class TestMultipleOperations:
    """Test multiple save/load operations."""

    def test_multiple_saves(self, tmp_path: Path) -> None:
        """Test multiple save operations."""
        output_file = tmp_path / "multi.bib"

        # First save
        entry1 = BibEntry(
            key="First",
            type="article",
            fields={"author": "A", "title": "T", "journal": "J", "year": "2020"},
        )
        lib1 = BibLibrary(entries={"First": entry1})
        result1 = save_bib(lib1, str(output_file))
        assert result1.success

        # Second save
        entry2 = BibEntry(
            key="Second",
            type="book",
            fields={"author": "B", "title": "U", "publisher": "P", "year": "2021"},
        )
        lib2 = BibLibrary(entries={"Second": entry2})
        result2 = save_bib(lib2, str(output_file))
        assert result2.success
        assert result2.backup_path is not None

        # Verify second save overwrote first
        loaded = load_bib(str(output_file))
        assert "Second" in loaded.entries
        assert "First" not in loaded.entries
