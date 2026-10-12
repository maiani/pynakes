"""Adversarial inputs and filesystem safety, entirely offline."""

import codecs
import json

import httpx
import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.editing import set_entry_field
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore
from pynakes.interchange import import_library
from pynakes.keys import rename_key
from pynakes.providers import _http, _network
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories import arxiv
from pynakes.scrub import ScrubOptions

runner = CliRunner()


def envelope(result):
    assert "Traceback" not in result.output
    data = json.loads(result.stdout)
    assert data["status"] in {"success", "error", "conflict"}
    return data


@pytest.mark.parametrize(
    "text",
    [
        "@misc{Newton1687,title={" + "{" * 3000 + "x" + "}" * 3000 + "}}",
        "@string{a=b}\n@string{b=a}\n@misc{Newton1687,title=a}",
        "@misc{Newton1687,crossref={Hooke1665}}\n@misc{Hooke1665,crossref={Newton1687}}",
        "@misc{Newton1687,title={unclosed}",
    ],
)
@pytest.mark.parametrize(
    "command", [["inspect"], ["lint"], ["format", "--check"], ["normalize", "--dry-run"]]
)
def test_hostile_structure_is_always_a_json_envelope(tmp_path, text, command):
    path = tmp_path / "refs.bib"
    path.write_text(text, encoding="utf-8")
    envelope(runner.invoke(app, [*command[:1], str(path), *command[1:], "--json"]))
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "data", [b"\x00\xffbinary", b"@misc{x,title={caf\xc3\xa9\xff}}", codecs.BOM_UTF16_LE + b"\x00"]
)
def test_hostile_bytes_are_errors_without_writes(tmp_path, data):
    path = tmp_path / "refs.bib"
    path.write_bytes(data)
    result = runner.invoke(app, ["inspect", str(path), "--json"])
    assert result.exit_code == 1
    assert envelope(result)["error"] == "ParseError"
    assert path.read_bytes() == data


@pytest.mark.parametrize(
    "key",
    [
        "C:relative",
        "nul",
        "CON.txt",
        "LPT1",
        "COM9",
        "a\x00b",
        "bad?name",
        "x" * 201,
        "trailing.",
        "../outside",
    ],
)
def test_pinax_rejects_nonportable_keys(tmp_path, key):
    with pytest.raises(ValueError, match="cannot address"):
        FileStore(tmp_path, tmp_path / "refs.bib").paths_for(key)
    assert not list(tmp_path.iterdir())


def test_pinax_rejects_case_collisions(tmp_path):
    with pytest.raises(ValueError, match="differ only in case"):
        FileStore(tmp_path, tmp_path / "refs.bib").scan(["Newton1687", "newton1687"])


@pytest.mark.parametrize("nested", [False, True])
def test_material_copy_refuses_symlinks_before_copying(tmp_path, nested):
    source = FileStore(tmp_path / "source", tmp_path / "source.bib")
    target = FileStore(tmp_path / "target", tmp_path / "target.bib")
    source.root.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"private")
    link = source.paths_for("Newton1687").preprint_pdf
    if nested:
        tree = source.paths_for("Newton1687").preprint_source
        tree.mkdir()
        link = tree / "private.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="Symlink"):
        target.copy_materials_from(source, "Newton1687")
    assert not target.root.exists()


def test_braced_references_follow_a_rename():
    lib = parse_bib("@book{Newton1687,title={Principia}}\n@misc{Hooke1665,related={{Newton1687}}}")
    rename_key(lib, "Newton1687", "Newton1713")
    assert lib.entries["Hooke1665"].fields["related"] == "{Newton1713}"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ReferenceMetadata("invented", "misc", {"title": "bad{"}),
        lambda: set_entry_field(
            parse_bib("@misc{Newton1687,title={Principia}}").entries["Newton1687"], "file", "bad}"
        ),
    ],
)
def test_external_values_are_brace_checked(factory):
    with pytest.raises(ValueError, match="brace"):
        factory()


@pytest.mark.parametrize(
    "identifier", ["../private", "1234", "2401.12345/../../bad", "x?url=http://localhost"]
)
@pytest.mark.parametrize("url", [arxiv.abs_url, arxiv.pdf_url, arxiv.source_url, arxiv.atom_url])
def test_arxiv_url_helpers_reject_malformed_ids(identifier, url):
    with pytest.raises(ValueError, match="Malformed"):
        url(identifier)


@pytest.mark.parametrize(
    "fmt,text",
    [
        ("ris", "TY  - BOOK\nTI  - bad{\nER  -\n"),
        ("endnote", "%0 Book\n%T bad{\n"),
        (
            "mods",
            '<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>bad{</title></titleInfo></mods>',
        ),
    ],
)
def test_interchange_cannot_create_unbalanced_fields(fmt, text):
    with pytest.raises(ValueError, match="brace"):
        import_library(text, fmt)


def test_scrub_completeness_and_literal_percent(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text(
        'private prose\n@string{local={/home/reader/private}}\n@preamble{"file:///private"}\n@misc{Newton1687,\n% internal note\n title={100% complete},\ncomment-reader={private},date-added={today},read={yes},rating={5},mendeley-tags={private},localfile={secret},attachments={secret},url={file:///private},note={see /home/reader/private}\n}\nprivate trailer',
        encoding="utf-8",
    )
    coll = Bibliography.open(path)
    report = coll.scrub()
    assert not report.clean
    output = coll.preview()
    assert "private" not in output
    assert parse_bib(output).entries["Newton1687"].fields == {"title": "100% complete"}
    coll.commit(backup=False)
    assert Bibliography.open(path).scrub().clean


def test_scrub_keep_everything_preserves_bytes(tmp_path):
    text = "private prose\n@misc{Newton1687,\n% private\ntitle={Principia},note={/home/reader/private}}"
    path = tmp_path / "refs.bib"
    path.write_text(text, encoding="utf-8")
    coll = Bibliography.open(path)
    assert coll.scrub(ScrubOptions(fields=False, comments=False, metadata=False)).clean
    assert coll.preview() == text


def mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        _http.httpx, "Client", lambda **kwargs: original(**{**kwargs, "transport": transport})
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://[::1]",
        "http://169.254.169.254",
        "http://10.0.0.1",
        "http://localhost",
        "https://user:pass@example.test",
    ],
)
def test_private_or_non_http_urls_never_reach_transport(monkeypatch, url):
    mock_http(monkeypatch, lambda _: pytest.fail("unsafe request was sent"))
    with pytest.raises(_http.ProviderFetchError):
        _http.fetch_bytes(url)


def test_private_dns_and_redirect_are_refused(monkeypatch):
    monkeypatch.setattr(_network, "_getaddrinfo", lambda host, port: ["93.184.216.34", "10.0.0.1"])
    with pytest.raises(_http.ProviderFetchError, match="non-public"):
        _network.validate_url("https://example.test", _http.ProviderFetchError)
    monkeypatch.setattr(_network, "_getaddrinfo", lambda host, port: ["93.184.216.34"])
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    mock_http(monkeypatch, handler)
    with pytest.raises(_http.ProviderFetchError, match="non-public"):
        _http.fetch_bytes("https://example.test")
    assert len(calls) == 1


def test_https_downgrade_warns(monkeypatch):
    mock_http(
        monkeypatch,
        lambda request: (
            httpx.Response(302, headers={"location": "http://example.test/final"})
            if request.url.scheme == "https"
            else httpx.Response(200, content=b"ok")
        ),
    )
    with pytest.warns(RuntimeWarning, match="redirected to HTTP"):
        assert _http.fetch_bytes("https://example.test") == b"ok"


def test_metadata_stream_is_capped(monkeypatch):
    monkeypatch.setattr(_http, "MAX_METADATA_BYTES", 8)
    mock_http(monkeypatch, lambda _: httpx.Response(200, content=b'{"large": "value"}'))
    with pytest.raises(_http.ProviderFetchError, match="size limit"):
        _http.fetch_json(
            "https://example.test", namespace="test", identifier="Newton1687", provider="invented"
        )


def test_deadline_stops_a_slow_stream(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_http.time, "monotonic", lambda: now[0])

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            now[0] = 2.0
            yield b"late"

    mock_http(monkeypatch, lambda _: httpx.Response(200, stream=Slow()))
    with pytest.raises(_http.ProviderFetchError, match="deadline"):
        _http.fetch_bytes("https://example.test", deadline_seconds=1.0)


def test_public_transport_pins_dns_and_keeps_host_and_tls_name(monkeypatch):
    sent = []
    monkeypatch.setattr(_network, "_getaddrinfo", lambda host, port: ["93.184.216.34"])

    def send(self, request):
        sent.append(request)
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", send)
    with _network.PublicTransport() as transport:
        original = httpx.Request("GET", "https://example.test/paper")
        transport.handle_request(original)
    request = sent[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["Host"] == "example.test"
    assert request.extensions["sni_hostname"] == "example.test"
    assert original.url.host == "example.test"


def test_public_transport_refuses_dns_rebinding(monkeypatch):
    monkeypatch.setattr(_network, "_getaddrinfo", lambda host, port: ["127.0.0.1"])
    with _network.PublicTransport() as transport:
        with pytest.raises(ValueError, match="non-public"):
            transport.handle_request(httpx.Request("GET", "https://example.test"))


@pytest.mark.parametrize(
    "fmt,text", [("mods", "<mods"), ("csl-json", "[{"), ("csv", "title\nprivate")]
)
def test_malformed_or_unsupported_interchange_is_json_error(tmp_path, fmt, text):
    source = tmp_path / f"source.{fmt}"
    source.write_text(text, encoding="utf-8")
    out = tmp_path / "out.bib"
    result = runner.invoke(
        app, ["convert", str(source), "--from", fmt, "--out", str(out), "--json"]
    )
    assert result.exit_code == 1
    assert envelope(result)["status"] == "error"
    assert not out.exists()


def test_percent_lines_in_parenthesized_entries_are_scrubbed(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text("@book(Newton1687,\n% private\ntitle={Principia}\n)", encoding="utf-8")
    coll = Bibliography.open(path)
    assert not coll.scrub().clean
    assert "private" not in coll.preview()
    assert parse_bib(coll.preview()).entries["Newton1687"].fields["title"] == "Principia"
