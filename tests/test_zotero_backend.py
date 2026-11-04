"""Synthetic local-API fixtures; no Zotero installation or private records needed."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from pynakes.bounded import StaleCursorError
from pynakes.cli import app
from pynakes.library_backend import (
    ItemRef,
    SourceChanged,
    SourceMissing,
    SourceUnavailable,
    SourceUnsupported,
    search_page,
)
from pynakes.zotero import ZoteroLibraryBackend
from tests.zotero_fixtures import LocalAPI


@pytest.fixture
def local():
    api = LocalAPI()
    with ZoteroLibraryBackend(transport=httpx.MockTransport(api)) as backend:
        yield api, backend


def test_scan_get_native_and_empty_page(local):
    api, b = local
    assert not api.calls
    description = b.describe()
    assert not description["authorization_required"]
    first = b.scan(limit=1)
    assert dict(first.items[0].fields)["author"] == "Newton, Isaac"
    assert "native" not in first.items[0].to_dict()
    assert "private memo" not in json.dumps(first.to_dict())
    middle = b.scan(limit=1, cursor=first.next_cursor)
    assert middle.items == () and middle.skipped == 1 and middle.next_cursor
    last = b.scan(limit=1, cursor=middle.next_cursor)
    assert len(last.items) == 1 and last.next_cursor is None
    assert last.complete and last.source_total == 3
    ref = first.items[0].ref
    assert b.get(ref, native=True).to_dict()["native"]["extra"] == "private memo"
    with pytest.raises(SourceUnsupported):
        b.get(b.item_ref("BCDEFGHJ"))
    with pytest.raises(SourceMissing):
        b.get(b.item_ref("ZZZZZZZZ"))
    with pytest.raises(SourceChanged):
        b.get(ItemRef("another-source", ref.key))


def test_cursor_and_read_freshness(local):
    api, b = local
    page = b.scan(limit=1)
    with pytest.raises(ValueError):
        b.scan(limit=2, cursor=page.next_cursor)
    api.revision += 1
    with pytest.raises(StaleCursorError):
        b.scan(limit=1, cursor=page.next_cursor)
    with pytest.raises(SourceChanged):
        b.get(page.items[0].ref, expected_revision=page.revision)
    api.change_after_page = True
    with pytest.raises(SourceChanged):
        b.scan()
    api.server = "new-instance"
    with pytest.raises(SourceChanged):
        b.describe()


def test_filtered_cursor_binds_query(local):
    _, b = local
    page = search_page(b, 'title contains "experiment"', limit=1)
    assert not page.items and page.next_cursor
    with pytest.raises(ValueError):
        search_page(b, 'title contains "Principia"', limit=1, cursor=page.next_cursor)
    page = search_page(b, 'title contains "experiment"', limit=1, cursor=page.next_cursor)
    page = search_page(b, 'title contains "experiment"', limit=1, cursor=page.next_cursor)
    assert len(page.items) == 1 and page.next_cursor is None


def test_collections_materials_and_local_path(local, tmp_path):
    api, b = local
    assert b.collections().items[0].name == "History"
    page = b.materials(b.item_ref("ABCDEFGH"))
    material = page.items[0]
    assert material.owner.key == "ABCDEFGH"
    assert "path" not in material.to_dict()
    with pytest.raises(SourceMissing):
        b.material_path(material)
    pdf = tmp_path / "example.pdf"
    pdf.write_bytes(b"test bytes")
    api.location = pdf.as_uri()
    assert b.material_path(material) == pdf
    api.location = "https://example.org/scan.pdf"
    with pytest.raises(SourceUnsupported):
        b.material_path(material)
    assert all(r.url.host == "127.0.0.1" for r in api.calls)
    api.items[1]["data"]["parentItem"] = "ZZZZZZZZ"
    with pytest.raises(SourceChanged):
        b.material_path(material)


@pytest.mark.parametrize(
    "status,error",
    [
        (403, SourceUnavailable),
        (404, SourceMissing),
        (412, SourceChanged),
        (301, SourceUnavailable),
        (500, SourceUnavailable),
    ],
)
def test_transport_status(local, status, error):
    api, b = local
    api.override = lambda r, h: httpx.Response(status, headers=h)
    with pytest.raises(error):
        b.describe()


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "headers",
        "json",
        "oversize",
        "total",
        "progress",
        "key",
        "duplicate",
        "creator",
        "field",
        "timeout",
    ],
)
def test_malformed_and_unsupported_fail_closed(local, fault):
    api, b = local
    if fault == "version":
        api.version = "9.9"
    elif fault == "key":
        api.items[0].pop("key")
    elif fault == "duplicate":
        api.items[1]["key"] = api.items[0]["key"]
    elif fault == "creator":
        api.items[0]["data"]["creators"] = [None]
    elif fault == "field":
        api.items[0]["data"]["date"] = 1687
    else:

        def override(request, headers):
            if fault == "timeout":
                raise httpx.ConnectError("offline")
            if fault == "headers":
                return httpx.Response(200, json=[])
            if "format" in request.url.params:
                return None
            if fault == "json":
                return httpx.Response(200, headers=headers, text="{")
            if fault == "oversize":
                return httpx.Response(200, headers=headers, content=b" " * (4 * 1024 * 1024 + 1))
            if fault == "total":
                return httpx.Response(200, headers=headers, json=[])
            return httpx.Response(200, headers={**headers, "Total-Results": "3"}, json=[])

        api.override = override
    with pytest.raises((SourceUnavailable, SourceUnsupported)):
        b.scan()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": 0},
        {"port": True},
        {"port": 2.5},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"max_response_bytes": 2},
    ],
)
def test_invalid_connection_options(kwargs):
    with pytest.raises(ValueError):
        ZoteroLibraryBackend(**kwargs)


def test_cli_reads_select_and_error_envelopes(local, tmp_path, monkeypatch):
    api, _ = local
    from pynakes.cli_commands import zotero as commands

    monkeypatch.setattr(
        commands,
        "ZoteroLibraryBackend",
        lambda **kw: ZoteroLibraryBackend(transport=httpx.MockTransport(api), **kw),
    )
    runner = CliRunner()
    for args in [
        ["status"],
        ["scan", "--limit", "1"],
        ["show", "ABCDEFGH", "--native"],
        ["collections"],
        ["materials", "ABCDEFGH"],
    ]:
        result = runner.invoke(app, ["zotero", *args, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "success"
    path = tmp_path / "project.bib"
    path.write_text("% Project\n", encoding="utf-8")
    args = ["zotero", "select", str(path), "--item", "ABCDEFGH", "--key", "Newton", "--json"]
    preview = runner.invoke(app, [*args, "--dry-run", "--diff"])
    assert preview.exit_code == 0, preview.output
    payload = json.loads(preview.output)
    assert payload["dry_run"] and payload["modified"] and "diff" in payload
    assert path.read_text(encoding="utf-8") == "% Project\n"
    applied = runner.invoke(app, [*args, "--expect-revision", payload["source_revision_digest"]])
    assert applied.exit_code == 0, applied.output
    assert not json.loads(runner.invoke(app, args).output)["modified"]
    stale = runner.invoke(app, [*args, "--expect-revision", "wrong"])
    assert stale.exit_code == 2 and json.loads(stale.output)["options"]
    api.version = "99"
    error = runner.invoke(app, ["zotero", "scan", "--json"])
    assert error.exit_code == 1 and "Traceback" not in error.output


def test_projection_reports_unsupported_roles_types_and_converts_markup(local):
    api, b = local
    data = api.items[0]["data"]
    data.update(
        itemType="preprint",
        title="An <i>invented</i> paper",
        pages="1–9",
        archiveID="1901.00001",
        repository="arXiv",
        date="Spring 1901",
        unknown="retained",
        relations={"dc:relation": "item"},
        creators=[
            {"creatorType": "author", "name": "Example Society"},
            {"creatorType": "translator", "name": "Example Translator"},
        ],
    )
    r = b.get(b.item_ref("ABCDEFGH"), native=True)
    fields = dict(r.fields)
    assert fields["author"] == "{Example Society}"
    assert "<i>" not in fields["title"]
    assert fields["pages"] == "1--9"
    assert fields["eprint"] == "1901.00001"
    assert "year" not in fields
    assert any("translator" in issue for issue in r.issues)
    assert any("unknown" in issue for issue in r.issues)
    assert "<i>" in r.to_dict()["native"]["title"]
    data["itemType"] = "futureType"
    assert b.get(r.ref).entry_type is None


def test_cli_target_precondition_before_connecting(tmp_path, monkeypatch):
    from pynakes.cli_commands import zotero as commands

    def unexpected(**kwargs):
        raise AssertionError("No source request should be made")

    monkeypatch.setattr(commands, "ZoteroLibraryBackend", unexpected)
    path = tmp_path / "project.bib"
    path.write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "zotero",
            "select",
            "--file",
            str(path),
            "--item",
            "ABCDEFGH",
            "--expect-sha256",
            "0" * 64,
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "ExternalModification"
    assert path.read_bytes() == b""
