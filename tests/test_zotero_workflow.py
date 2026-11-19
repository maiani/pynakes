"""Multi-item project transactions and bounded Zotero searches."""

import json
from copy import deepcopy

import httpx
import pytest
from typer.testing import CliRunner

from pynakes import Bibliography
from pynakes.bounded import StaleCursorError
from pynakes.cli import app
from pynakes.cli.commands import zotero as commands
from pynakes.editing import set_entry_field
from pynakes.library.backends.base import ItemRef, SourceChanged, SourceUnavailable
from pynakes.project_selection import (
    SelectionBatchConflict,
    prepare_selections,
    project_bindings,
)
from pynakes.zotero import ZoteroLibraryBackend
from tests.zotero_fixtures import LocalAPI


@pytest.fixture
def local(monkeypatch):
    api = LocalAPI()
    monkeypatch.setattr(
        commands,
        "ZoteroLibraryBackend",
        lambda **kw: ZoteroLibraryBackend(transport=httpx.MockTransport(api), **kw),
    )
    with ZoteroLibraryBackend(transport=httpx.MockTransport(api)) as backend:
        yield api, backend


def invoke(*args, exit_code=0):
    result = CliRunner().invoke(app, ["zotero", *map(str, args), "--json"])
    assert result.exit_code == exit_code, result.output or result.exception
    return json.loads(result.output)


def test_batch_preview_apply_repeat_and_refresh(local, tmp_path):
    api, backend = local
    path = tmp_path / "paper.bib"
    path.write_text("% Preserve me\n", encoding="utf-8")
    args = ("select", path, "--item", "ABCDEFGH", "--item", "CDEFGHJK", "--item", "ABCDEFGH")
    preview = invoke(*args, "--dry-run", "--diff")
    assert len(preview["selections"]) == 2 and preview["diff"]
    assert path.read_text() == "% Preserve me\n"
    applied = invoke(
        *args,
        "--expect-revision",
        preview["source_revision_digest"],
        "--expect-sha256",
        preview["source_sha256"],
    )
    assert applied["modified"]
    before = path.read_bytes()
    assert not invoke(*args)["modified"] and path.read_bytes() == before
    api.items[0]["data"]["title"] = "Revised Principia"
    api.items[2]["data"]["title"] = "Revised experiment"
    api.revision += 1
    report = invoke("refresh", path)
    assert len(report["selections"]) == 2
    assert {e.fields["title"] for e in Bibliography.open(path).entries.values()} == {
        "Revised Principia",
        "Revised experiment",
    }
    assert not invoke("refresh", path)["modified"]
    assert len(project_bindings(Bibliography.open(path))) == 2
    # Every source request, including commit guards, remains a GET.
    assert all(r.method == "GET" for r in api.calls)


def test_all_conflicts_are_reported_and_scoped_decisions_are_atomic(local, tmp_path):
    api, _ = local
    path = tmp_path / "paper.bib"
    path.write_text("")
    initial = invoke("select", path, "--item", "ABCDEFGH", "--item", "CDEFGHJK")
    bib = Bibliography.open(path)
    for entry in bib.entries.values():
        set_entry_field(entry, "title", "Project " + entry.key)
    bib.commit()
    for row in (api.items[0], api.items[2]):
        row["data"]["title"] = "Source " + row["key"]
    api.revision += 1
    before = path.read_bytes()
    report = invoke("refresh", path, exit_code=2)
    assert len(report["findings"]) == 2
    assert all(f["conflicts"][0]["field"] == "title" for f in report["findings"])
    guards = (
        "--expect-revision",
        report["source_revision_digest"],
        "--expect-sha256",
        report["source_sha256"],
    )
    invoke("refresh", path, *guards, "--resolve", "ABCDEFGH:title=source", exit_code=2)
    assert path.read_bytes() == before
    invoke("refresh", path, *guards, "--resolve", "title=source", exit_code=1)
    invoke("refresh", path, *guards, "--resolve", "ZZZZZZZZ:title=source", exit_code=1)
    invoke(
        "refresh",
        path,
        *guards,
        "--resolve",
        "ABCDEFGH:title=source",
        "--resolve",
        "CDEFGHJK:title=project",
    )
    bib = Bibliography.open(path)
    assert bib.entries[initial["selections"][0]["key"]].fields["title"] == "Source ABCDEFGH"
    assert bib.entries[initial["selections"][1]["key"]].fields["title"].startswith("Project ")
    assert not invoke("refresh", path)["modified"]


def test_collection_scope_budgets_and_missing_file(local, tmp_path):
    api, _ = local
    path = tmp_path / "paper.bib"
    missing = invoke("select", path, "--collection", "DEFGHJKL", exit_code=1)
    assert missing["error"] == "FileNotFound" and "init" in missing["message"]
    assert not api.calls
    path.write_text("")
    report = invoke("select", path, "--collection", "DEFGHJKL", "--dry-run")
    assert len(report["selections"]) == 1
    assert "Books" in str(report["warnings"])
    invoke("select", path, "--collection", "DEFGHJKL", "--max-items", "1", exit_code=1)
    invoke(
        "select", path, "--item", "ABCDEFGH", "--item", "CDEFGHJK", "--max-items", "1", exit_code=1
    )
    invoke("select", path, "--collection", "DEFGHJKL", "--key", "X", exit_code=1)
    invoke("select", path, exit_code=1)
    assert path.read_bytes() == b""
    empty = invoke("select", path, "--collection", "EFGHJKLM")
    assert not empty["modified"] and empty["selections"] == []


def test_foreign_bindings_are_reported_and_not_refreshed(local, tmp_path):
    api, _ = local
    path = tmp_path / "paper.bib"
    path.write_text("")
    invoke("select", path, "--item", "ABCDEFGH")
    before = path.read_bytes()
    api.server = "another-instance"
    report = invoke("refresh", path)
    assert len(report["foreign_bindings"]) == 1 and report["warnings"]
    assert not report["modified"] and path.read_bytes() == before


def test_batch_reconciliation_and_read_failure_leave_no_staged_edits(local):
    api, backend = local
    copy = deepcopy(api.items[2])
    copy["key"] = "EFGHJKLM"
    api.items.append(copy)
    refs = [backend.item_ref(k) for k in ("ABCDEFGH", "CDEFGHJK", "EFGHJKLM", "ZZZZZZZZ")]
    bib = Bibliography.from_text("% Untouched\n")
    with pytest.raises(SelectionBatchConflict) as error:
        prepare_selections(backend, refs, bib)
    assert len(error.value.findings) == 2
    assert {f.ref.key for f in error.value.findings} == {"EFGHJKLM", "ZZZZZZZZ"}
    assert bib.preview() == bib.pristine_text and not bib._commit_guards


def test_batch_api_guards_and_bindings(local, tmp_path):
    api, backend = local
    path = tmp_path / "paper.bib"
    path.write_text("")
    bib = Bibliography.open(path)
    refs = [backend.item_ref(k) for k in ("ABCDEFGH", "CDEFGHJK")]
    with pytest.raises(ValueError, match="selected"):
        prepare_selections(backend, refs, bib, keys={ItemRef("other", "missing"): "X"})
    with pytest.raises(ValueError, match="reviewed"):
        prepare_selections(backend, refs, bib, resolutions={refs[0]: {"title": "source"}})
    plan = prepare_selections(backend, refs, bib)
    assert len(plan.selections) == 2 and plan.revision
    api.revision += 1
    with pytest.raises(SourceChanged):
        bib.commit()
    assert path.read_bytes() == b""


def test_batch_connection_failure_is_an_error_and_leaves_target_untouched(local, tmp_path):
    api, backend = local
    refs = [backend.item_ref(k) for k in ("ABCDEFGH", "CDEFGHJK")]

    def unavailable(request, headers):
        if request.url.path.endswith("/CDEFGHJK"):
            return httpx.Response(503, headers=headers)
        return None

    api.override = unavailable
    bib = Bibliography.from_text("% Preserve me\n")
    with pytest.raises(SourceUnavailable):
        prepare_selections(backend, refs, bib)
    assert bib.preview() == bib.pristine_text and not bib._commit_guards
    path = tmp_path / "paper.bib"
    path.write_text(bib.pristine_text, encoding="utf-8")
    before = path.read_bytes()
    report = invoke("select", path, "--item", "ABCDEFGH", "--item", "CDEFGHJK", exit_code=1)
    assert report["error"] == "SourceError"
    assert path.read_bytes() == before


def test_search_budget_continuation_native_scope_and_empty_pages(local):
    api, backend = local
    result = backend.search(where="year > 1900", max_items=1)
    assert result.items == () and not result.complete
    assert result.to_dict()["stop_reason"] == "budget" and result.next_cursor
    middle = backend.search(where="year > 1900", max_items=1, cursor=result.next_cursor)
    assert not middle.items and middle.next_cursor and not middle.complete
    last = backend.search(where="year > 1900", max_items=1, cursor=middle.next_cursor)
    assert [r.ref.key for r in last.items] == ["CDEFGHJK"] and last.complete
    assert backend.search("Newton", where="year < 1700").items[0].ref.key == "ABCDEFGH"
    assert backend.search("absent").complete and not backend.search("absent").items
    assert backend.search(where="year > 1900", collection="DEFGHJKL").items == ()
    with pytest.raises(ValueError):
        backend.search(where="year > 1901", max_items=1, cursor=result.next_cursor)
    with pytest.raises(ValueError):
        backend.search(where="year > 1900", max_items=2, cursor=result.next_cursor)
    with pytest.raises(ValueError):
        backend.search(
            where="year > 1900", collection="DEFGHJKL", max_items=1, cursor=result.next_cursor
        )
    api.revision += 1
    with pytest.raises(StaleCursorError):
        backend.search(where="year > 1900", max_items=1, cursor=result.next_cursor)
    for kwargs in ({}, {"text": " "}, {"where": "year > 1", "max_items": 0}):
        with pytest.raises(ValueError):
            backend.search(**kwargs)


def test_search_spans_pages_and_partial_final_budget(local):
    api, backend = local
    api.items = [
        {
            "key": f"X{i:07d}",
            "data": {
                "itemType": "book",
                "title": f"Book {i}",
                "date": "1800" if i < 103 else "1900",
            },
        }
        for i in range(207)
    ]
    first = backend.search(where="year = 1900", max_items=103)
    assert first.scanned == 103 and not first.items and not first.complete
    second = backend.search(where="year = 1900", max_items=103, cursor=first.next_cursor)
    third = backend.search(where="year = 1900", max_items=103, cursor=second.next_cursor)
    assert len(second.items) == 103 and len(third.items) == 1 and third.complete
    assert len({r.ref.key for r in (*second.items, *third.items)}) == 104
    api.change_after_page = True
    with pytest.raises(SourceChanged):
        backend.search("Book")


def test_search_cli_json_and_human(local):
    report = invoke("search", "--where", "year > 1900", "--max-items", "1")
    assert not report["complete"] and report["next_cursor"]
    result = CliRunner().invoke(app, ["zotero", "search", "Newton"])
    assert result.exit_code == 0 and "Principia" in result.output
    result = CliRunner().invoke(
        app, ["zotero", "search", "--where", "year > 1900", "--max-items", "1"]
    )
    assert result.exit_code == 0 and "Next cursor:" in result.output


def test_native_library_uses_same_atomic_batch_planner(tmp_path):
    from pynakes import Library
    from pynakes.library_backend import BibTeXLibraryBackend

    source_path = tmp_path / "source.bib"
    source_path.write_text(
        "@book{First,title={Principia},year={1687}}\n@book{Second,title={Opticks},year={1704}}\n"
    )
    backend = BibTeXLibraryBackend(Library.from_files([source_path]))
    refs = [record.ref for record in backend.scan().items]
    target = tmp_path / "project.bib"
    target.write_text("")
    bib = Bibliography.open(target)
    prepare_selections(backend, refs, bib, keys={refs[0]: "LocalFirst", refs[1]: "LocalSecond"})
    bib.commit()
    assert set(bib.entries) == {"LocalFirst", "LocalSecond"}
    before = target.read_bytes()
    plan = prepare_selections(backend, refs, Bibliography.open(target))
    plan.bibliography.commit()
    assert target.read_bytes() == before


def test_changed_source_between_batch_reads_is_atomic(local):
    api, backend = local
    refs = [backend.item_ref(k) for k in ("ABCDEFGH", "CDEFGHJK")]
    versions = 0

    def change(request, headers):
        nonlocal versions
        if request.url.params.get("format") == "versions":
            versions += 1
            if versions == 3:
                api.revision += 1
                return httpx.Response(
                    200, headers={**headers, "Last-Modified-Version": str(api.revision)}, json={}
                )
        return None

    api.override = change
    bib = Bibliography.from_text("")
    with pytest.raises(SelectionBatchConflict):
        prepare_selections(backend, refs, bib)
    assert not bib.is_modified and not bib._commit_guards


def test_collection_selection_spans_pages_and_reports_every_item(local, tmp_path):
    api, _ = local
    api.items = [
        {
            "key": f"X{i:07d}",
            "data": {
                "itemType": "book",
                "title": f"Book {i}",
                "date": str(1700 + i),
                "collections": ["DEFGHJKL"],
            },
        }
        for i in range(102)
    ]
    path = tmp_path / "paper.bib"
    path.write_text("")
    report = invoke("select", path, "--collection", "DEFGHJKL", "--max-items", "102")
    assert len(report["selections"]) == len(Bibliography.open(path).entries) == 102
