"""Error recovery: malformed input, encoding fallback, and atomic-write safety.

Covers the failure paths that the architecture promises to handle gracefully:
parse errors carry a line number, missing files raise ``FileNotFoundError``,
non-UTF-8 bytes fall back to latin-1, and a failed validation on save restores
the original file from its backup.
"""

import pytest

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.io import load_bib, save_text


class TestParseErrors:
    def test_unbalanced_braces_raise_with_line(self) -> None:
        with pytest.raises(ParseError) as exc:
            parse_bib("@article{key,\n  title = {Unterminated\n  year = {2020}\n")
        assert exc.value.line is not None

    def test_garbage_between_entries_is_tolerated(self) -> None:
        # Stray non-entry lines are skipped, not fatal.
        lib = parse_bib("garbage line\n@article{Ok, title = {T}}\nmore garbage\n")
        assert "Ok" in lib.entries

    def test_empty_input_yields_empty_library(self) -> None:
        lib = parse_bib("")
        assert len(lib.entries) == 0


class TestEncodingFallback:
    def test_latin1_bytes_fall_back(self, tmp_path) -> None:
        # 0xE9 ('é' in latin-1) is invalid UTF-8 and must trigger fallback.
        path = tmp_path / "latin1.bib"
        path.write_bytes("@article{k, author = {Caf\xe9}}\n".encode("latin-1"))
        lib = load_bib(str(path))
        assert lib.encoding == "latin-1"
        assert "Caf\xe9" in lib.entries["k"].fields["author"]


class TestIOErrors:
    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            load_bib(str(tmp_path / "nope.bib"))

    def test_failed_validation_restores_backup(self, tmp_path) -> None:
        path = tmp_path / "refs.bib"
        good = "@article{k, title = {Good}, year = {2020}}\n"
        path.write_text(good)

        # Content that the re-parse validation rejects (unbalanced braces).
        result = save_text("@article{broken, title = {oops}\n", str(path))
        assert result.success is False
        assert "Validation failed" in (result.error or "")
        # Original content was restored from the backup.
        assert path.read_text() == good

    def test_successful_save_writes_backup(self, tmp_path) -> None:
        path = tmp_path / "refs.bib"
        path.write_text("@article{k, title = {Old}, year = {2020}}\n")
        new = "@article{k, title = {New}, year = {2021}}\n"

        result = save_text(new, str(path))
        assert result.success is True
        assert path.read_text() == new
        assert result.backup_path is not None
