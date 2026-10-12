"""The hostile-input matrix: malformed interchange files and provider responses.

Every case must end in a JSON envelope on stdout with no traceback, and a
failure must leave the library and any output path untouched. Library-level
importers may raise only ``ValueError`` for malformed input.
"""

import json

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.interchange import IMPORT_FORMATS, import_library
from pynakes.providers import _http

runner = CliRunner()
MODS_NS = "http://www.loc.gov/mods/v3"


def envelope(result) -> dict:
    assert "Traceback" not in result.output
    data = json.loads(result.stdout)
    assert data["status"] in {"success", "error", "conflict"}
    return data


def imports_cleanly_or_refuses(text: str, fmt: str) -> None:
    """The importer contract: a reparseable library, or a ``ValueError``."""
    try:
        lib = import_library(text, fmt)
    except ValueError:
        return
    assert list(parse_bib(write_bib(lib)).entries.keys()) == list(lib.entries.keys())


# --- Importer properties -----------------------------------------------------

_SETTINGS = settings(max_examples=150, suppress_health_check=list(HealthCheck), deadline=None)
_LEAF = st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12)
_CSL_KEYS = st.sampled_from(
    ["type", "id", "title", "author", "editor", "issued", "container-title", "page",
     "volume", "DOI", "URL", "publisher", "given", "family", "literal", "date-parts",
     "raw", "ISBN", "issue", "note", "citation-key"]
)  # fmt: skip
_CSL_VALUE = st.recursive(
    _LEAF,
    lambda inner: (
        st.lists(inner, max_size=3)
        | st.dictionaries(_CSL_KEYS | st.text(max_size=4), inner, max_size=5)
    ),
    max_leaves=25,
)


@_SETTINGS
@given(_CSL_VALUE)
def test_csl_json_of_any_shape_imports_or_is_refused(value):
    imports_cleanly_or_refuses(json.dumps(value), "csl-json")


def _tagged_lines(tags, render):
    line = st.builds(render, st.sampled_from(tags), st.text(max_size=15))
    return st.lists(line | st.text(max_size=10) | st.just(""), max_size=12).map("\n".join)


@_SETTINGS
@given(
    _tagged_lines(
        ["TY", "TI", "T1", "AU", "A1", "ED", "PY", "DA", "JO", "VL", "IS", "SP", "EP",
         "DO", "UR", "PB", "SN", "KW", "ER", "XX"],
        lambda tag, value: f"{tag}  - {value}",
    )
)  # fmt: skip
def test_ris_of_any_shape_imports_or_is_refused(text):
    imports_cleanly_or_refuses(text, "ris")


@_SETTINGS
@given(_tagged_lines(list("0ATBDJVNPI@RUXK7&Y9"), lambda tag, value: f"%{tag} {value}"))
def test_endnote_of_any_shape_imports_or_is_refused(text):
    imports_cleanly_or_refuses(text, "endnote")


_MODS_NAMES = st.sampled_from(
    ["titleInfo", "title", "name", "namePart", "role", "roleTerm", "originInfo",
     "dateIssued", "publisher", "relatedItem", "part", "detail", "number", "extent",
     "start", "end", "identifier", "genre", "note"]
)  # fmt: skip
_MODS_ATTRS = st.sampled_from(
    ["", ' type="doi"', ' type="family"', ' type="host"', ' unit="page"', ' unit="volume"']
)
_MODS_TEXT = st.text(alphabet=st.characters(blacklist_categories=["Cs", "Cc"]), max_size=10).map(
    lambda text: text.replace("&", "&amp;").replace("<", "&lt;")
)


def _mods_tree(depth):
    if depth == 0:
        return _MODS_TEXT
    return st.builds(
        lambda name, attrs, children: f"<{name}{attrs}>{''.join(children)}</{name}>",
        _MODS_NAMES,
        _MODS_ATTRS,
        st.lists(_mods_tree(depth - 1), max_size=3),
    )


@_SETTINGS
@given(st.lists(_mods_tree(3), max_size=4))
def test_mods_of_any_shape_imports_or_is_refused(children):
    text = f'<modsCollection xmlns="{MODS_NS}"><mods>{"".join(children)}</mods></modsCollection>'
    imports_cleanly_or_refuses(text, "mods")


@pytest.mark.parametrize("fmt", IMPORT_FORMATS)
@given(text=st.text(max_size=200))
@settings(max_examples=60, deadline=None)
def test_arbitrary_text_imports_or_is_refused(fmt, text):
    imports_cleanly_or_refuses(text, fmt)


# --- Specific hostile files through `convert` --------------------------------

ENTITY_BOMB = (
    '<!DOCTYPE mods [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    f'<mods xmlns="{MODS_NS}"><titleInfo><title>&b;</title></titleInfo></mods>'
)

REFUSED = [
    ("csl-json", "null"),
    ("csl-json", "42"),
    ("csl-json", '"a string"'),
    ("csl-json", "[" * 100_000),
    ("csl-json", '[{"title": "bad{"}]'),
    ("mods", ENTITY_BOMB),
    ("mods", "<mods"),
    ("mods", "\x00"),
    ("mods", f'<mods xmlns="{MODS_NS}"><titleInfo><title>&undefined;</title></titleInfo></mods>'),
    ("ris", "TY  - JOUR\nTI  - }{\nER  -\n"),
    ("endnote", "%0 Journal Article\n%T }{\n"),
]

TOLERATED = [
    ("csl-json", '[{"author": [3.5, ["x"], {"family": 7, "given": null}]}]'),
    ("csl-json", "[1, null, {}]"),
    ("ris", "ER  -\nER  -\nnot a tag\nTY  -\n"),
    ("ris", "TY  - XYZ\nAU  - \nPY  - not a year\nSP  - --\nER  -\n"),
    ("endnote", "%\n%%\n%0\n% T dangling\n"),
    ("mods", f'<unrelated xmlns="{MODS_NS}"/>'),
    ("mods", f'<mods xmlns="{MODS_NS}"><name><namePart/></name><part><extent/></part></mods>'),
]


@pytest.mark.parametrize("fmt,text", REFUSED)
def test_refused_interchange_is_a_json_error_without_output(tmp_path, fmt, text):
    source = tmp_path / "source.txt"
    source.write_text(text, encoding="utf-8")
    out = tmp_path / "out.bib"
    result = runner.invoke(
        app, ["convert", str(source), "--from", fmt, "--out", str(out), "--json"]
    )
    assert result.exit_code == 1
    assert envelope(result)["status"] == "error"
    assert not out.exists()


@pytest.mark.parametrize("fmt,text", TOLERATED)
def test_odd_but_parseable_interchange_converts(tmp_path, fmt, text):
    source = tmp_path / "source.txt"
    source.write_text(text, encoding="utf-8")
    out = tmp_path / "out.bib"
    result = runner.invoke(
        app, ["convert", str(source), "--from", fmt, "--out", str(out), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert envelope(result)["status"] == "success"
    parse_bib(out.read_text(encoding="utf-8"))


def test_csv_is_export_only():
    assert "csv" not in IMPORT_FORMATS
    with pytest.raises(ValueError, match="Unsupported import format 'csv'"):
        import_library("title\nPrincipia\n", "csv")


# --- Provider responses through `ref import` ---------------------------------

LIBRARY = "@book{Newton1687,title={Principia}}\n"
BIBTEX = b"@article{x,title={A Test},author={Smith, Jane},journal={J},year={2024}}"


def provider(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        _http.httpx, "Client", lambda **kwargs: original(**{**kwargs, "transport": transport})
    )


def fixed(*args, **kwargs):
    return lambda request: httpx.Response(*args, **kwargs)


FAILED_RESPONSES = [
    ("10.5555/a", fixed(200, content=b"<html>busy</html>")),
    ("10.5555/a", fixed(200, content=b"@article{x,title={bad{}")),
    ("10.5555/a", fixed(200, content=b"")),
    ("10.5555/a", fixed(200, content=b"\xff\xfe@\x00")),
    ("10.5555/a", fixed(404)),
    ("10.5555/a", fixed(429, headers={"Retry-After": "0"})),
    ("10.5555/a", fixed(503)),
    ("10.5555/a", fixed(200, headers={"content-length": str(600 << 20)}, content=BIBTEX)),
    ("10.5555/a", fixed(302, headers={"location": "http://127.0.0.1/private"})),
    ("10.5555/a", fixed(302, headers={"location": "file:///etc/passwd"})),
    ("arXiv:2301.00001", fixed(200, content=b"<feed")),
    ("arXiv:2301.00001", fixed(200, content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>')),
    (
        "arXiv:2301.00001",
        fixed(
            200,
            content=b'<!DOCTYPE f [<!ENTITY a "b">]>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&a;</title></entry></feed>',
        ),
    ),
]


@pytest.mark.parametrize("identifier,handler", FAILED_RESPONSES)
def test_a_failed_provider_response_is_a_json_error_and_writes_nothing(
    tmp_path, monkeypatch, identifier, handler
):
    provider(monkeypatch, handler)
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    result = runner.invoke(app, ["ref", "import", str(bib), identifier, "--json"])
    assert result.exit_code == 1
    data = envelope(result)
    assert data["status"] == "error"
    assert data["message"]
    assert bib.read_text(encoding="utf-8") == LIBRARY


def test_a_throttled_provider_that_recovers_imports(tmp_path, monkeypatch):
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, content=BIBTEX)]
    )
    provider(monkeypatch, lambda request: next(responses))
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/a", "--json"])
    assert result.exit_code == 0, result.output
    assert envelope(result)["modified_entries"] == 1


def test_one_hostile_response_among_several_is_reported_per_identifier(tmp_path, monkeypatch):
    provider(
        monkeypatch,
        lambda request: (
            httpx.Response(200, content=BIBTEX)
            if request.url.path.endswith("/good")
            else httpx.Response(200, content=b"\x00\x01garbage")
        ),
    )
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    result = runner.invoke(
        app, ["ref", "import", str(bib), "10.5555/good", "10.5555/bad", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = envelope(result)
    assert (data["imported"], data["failed"]) == (1, 1)
    failed = next(row for row in data["results"] if row["status"] == "failed")
    assert failed["identifier"] == "10.5555/bad"
