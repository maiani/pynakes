"""Source encodings: byte-order marks round-trip, and mixed bytes are refused.

A file with a byte-order mark is decoded in the encoding the mark names, and is
written back in that encoding with the same mark. A file without one is UTF-8,
or Latin-1 when it holds no UTF-8 multi-byte character at all. A file that is
UTF-8 except for a few stray bytes is refused rather than silently re-read as
Latin-1, which would turn every one of its accented characters into mojibake.
"""

import codecs
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import ParseError
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.io import load_bib, save_bib

runner = CliRunner()

SOURCE = "@book{Newton1687,\n  title = {Philosophiæ Naturalis Principia Mathematica}\n}\n"

BOMS = {
    "utf-8-sig": codecs.BOM_UTF8,
    "utf-16-le": codecs.BOM_UTF16_LE,
    "utf-16-be": codecs.BOM_UTF16_BE,
    "utf-32-le": codecs.BOM_UTF32_LE,
    "utf-32-be": codecs.BOM_UTF32_BE,
}


def _encoded(encoding: str, text: str = SOURCE) -> bytes:
    if encoding == "utf-8-sig":
        return text.encode(encoding)
    return BOMS[encoding] + text.encode(encoding)


@pytest.mark.parametrize("encoding", BOMS)
def test_a_bom_names_the_encoding(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(_encoded(encoding))
    lib = load_bib(str(path))
    assert lib.encoding == encoding
    assert lib.entries["Newton1687"].fields["title"].startswith("Philosophiæ")


@pytest.mark.parametrize("encoding", BOMS)
def test_an_unmodified_bom_file_round_trips(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "refs.bib"
    original = _encoded(encoding)
    path.write_bytes(original)
    assert save_bib(load_bib(str(path)), str(path), backup=False).success
    assert path.read_bytes() == original


@pytest.mark.parametrize("encoding", BOMS)
def test_an_edit_keeps_the_bom_and_encoding(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(_encoded(encoding))
    bib = Bibliography.open(path)
    bib.add_entry("book", "Euler1748", {"title": "Introductio"})
    bib.commit()
    expected = SOURCE + "\n@book{Euler1748,\n  title = {Introductio}\n}\n"
    assert path.read_bytes() == _encoded(encoding, expected)


def test_inspect_reports_a_utf16_encoding(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(_encoded("utf-16-le"))
    result = runner.invoke(app, ["inspect", str(path), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["encoding"] == "utf-16-le"
    assert data["entry_count"] == 1


def test_a_plain_latin1_file_still_loads_as_latin1(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    original = "@book{Descartes1637,\n  title = {Discours de la méthode}\n}\n".encode("latin-1")
    path.write_bytes(original)
    lib = load_bib(str(path))
    assert lib.encoding == "latin-1"
    assert lib.entries["Descartes1637"].fields["title"].endswith("méthode")
    assert save_bib(lib, str(path), backup=False).success
    assert path.read_bytes() == original


MIXED = (
    "@book{Newton1687,\n  title = {Philosophiæ Naturalis}\n}\n".encode()
    + b"@book{Descartes1637,\n  title = {Discours de la m\xe9thode}\n}\n"
)


def test_utf8_with_a_stray_byte_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(MIXED)
    with pytest.raises(ParseError) as caught:
        load_bib(str(path))
    assert caught.value.line == 5
    assert "UTF-8" in caught.value.message


def test_cli_reports_a_mixed_file_as_a_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(MIXED)
    result = runner.invoke(app, ["inspect", str(path), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["error"] == "ParseError"
    assert data["line"] == 5
    assert path.read_bytes() == MIXED


def test_utf16_without_a_bom_is_refused_not_read_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(SOURCE.encode("utf-16-le"))
    with pytest.raises(ParseError) as caught:
        load_bib(str(path))
    assert "NUL" in caught.value.message


def test_a_utf16_file_with_odd_bytes_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(_encoded("utf-16-le") + b"\x00")
    with pytest.raises(ParseError):
        load_bib(str(path))


def test_a_new_character_outside_latin1_fails_the_save_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_bytes(b"@book{Descartes1637,\n  title = {M\xe9thode}\n}\n")
    bib = Bibliography.open(path)
    bib.add_entry("book", "Euler1748", {"title": "Ἀρχιμήδης"})
    with pytest.raises(OSError):
        bib.commit()
    assert path.read_bytes() == b"@book{Descartes1637,\n  title = {M\xe9thode}\n}\n"
