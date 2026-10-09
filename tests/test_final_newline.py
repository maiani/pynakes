"""A write keeps the file's own line endings, final newline, and blank content.

Only what an edit changed may differ: the writer must not add a final newline
the file did not have, append a CRLF to a file whose last line ends in LF, or
drop a file's whitespace-only content.
"""

from pathlib import Path

import pytest

from pynakes._engine_helpers import append_entry_text
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.editing import set_entry_field
from pynakes.engine import Bibliography
from pynakes.io import load_bib, save_bib
from pynakes.model import BibEntry, BibFile

SOURCES = {
    "mixed, LF at end": "@article{Newton1687,\r\n  title = {Principia}\r\n}\n",
    "CRLF, no final newline": "@article{Newton1687,\r\n  title = {Principia}\r\n}",
    "LF, no final newline": "@article{Newton1687,\n  title = {Principia}\n}",
    "whitespace only": "  \n\n ",
    "CRLF blank lines only": "\r\n\r\n",
    "empty": "",
}


@pytest.mark.parametrize("text", SOURCES.values(), ids=SOURCES.keys())
def test_an_unmodified_parse_writes_back_unchanged(text: str) -> None:
    assert write_bib(parse_bib(text)) == text


@pytest.mark.parametrize("text", SOURCES.values(), ids=SOURCES.keys())
def test_save_bib_round_trips_the_bytes(tmp_path: Path, text: str) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(text.encode("utf-8"))
    result = save_bib(load_bib(str(path)), str(path), backup=False)
    assert result.success
    assert path.read_bytes() == text.encode("utf-8")


def test_a_field_edit_keeps_the_missing_final_newline() -> None:
    lib = parse_bib(SOURCES["CRLF, no final newline"])
    entry = lib.entries["Newton1687"]
    set_entry_field(entry, "year", "1687")
    out = write_bib(lib)
    assert out.endswith("}")
    assert "year = {1687}" in out


def test_a_field_edit_keeps_a_final_lf_in_a_crlf_file() -> None:
    lib = parse_bib(SOURCES["mixed, LF at end"])
    set_entry_field(lib.entries["Newton1687"], "year", "1687")
    out = write_bib(lib)
    assert out.endswith("}\n")
    assert not out.endswith("\r\n")


def test_an_in_memory_library_still_ends_with_a_newline() -> None:
    entry = BibEntry(key="Euler1748", type="book", fields={"title": "Introductio"})
    assert write_bib(BibFile(entries={"Euler1748": entry})).endswith("}\n")


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("", "@book{E}\n"),
        ("@article{N}\n", "@article{N}\n\n@book{E}\n"),
        ("@article{N}\n\n", "@article{N}\n\n@book{E}\n"),
        # The file's own LF counts as a line end even though it writes CRLF.
        ("@article{N}\r\n}\n", "@article{N}\r\n}\n\r\n@book{E}\r\n"),
        # No final newline before the append: none after it either.
        ("@article{N}", "@article{N}\n\n@book{E}"),
    ],
)
def test_append_entry_text_respects_the_existing_ending(original: str, expected: str) -> None:
    le = "\r\n" if "\r\n" in original else "\n"
    assert append_entry_text(original, "@book{E}", le, []) == expected


def test_adding_an_entry_to_a_file_without_final_newline_adds_none(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(SOURCES["LF, no final newline"].encode())
    bib = Bibliography.open(path)
    bib.add_entry("book", "Euler1748", {"title": "Introductio"})
    bib.commit()
    assert path.read_bytes() == (
        b"@article{Newton1687,\n  title = {Principia}\n}\n\n"
        b"@book{Euler1748,\n  title = {Introductio}\n}"
    )
