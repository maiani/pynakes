"""Native ingestion acceptance using generated, invented references only."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import Bibliography, Library
from pynakes.cli import app
from pynakes.filestore import _transaction
from pynakes.library._ingest import state_path
from tests.test_library_routing import RULE
from tests.test_pdf_import import BIB, TITLE, make_pdf


@pytest.fixture(name="manifest")
def library_manifest(tmp_path):
    for name in ("books", "engines", "inbox"):
        (tmp_path / f"{name}.bib").write_bytes(b"% Untouched header.\r\n")
    path = tmp_path / "test.library.toml"
    path.write_text(
        'pynakes-library = 1\nmembers = ["books.bib", "engines.bib", "inbox.bib"]\n' + RULE,
        encoding="utf-8",
    )
    return path


def test_default_move_is_staged_and_portable(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{pynakes-meta: pinax-files-dir:files;}\n")
    source = make_pdf(tmp_path / "original.pdf", bib=BIB, annotate=True)
    original = source.read_bytes()
    coll = Bibliography.open(bib)
    result = coll.import_pdfs([source]).results[0]
    assert result["status"] == "imported"
    assert source.exists() and not (tmp_path / "files").exists()
    coll.commit()
    assert not source.exists()
    variant = coll.files.material_variants(result["key"])[0]
    assert Path(variant["absolute_path"]).read_bytes() == original
    assert coll.files_check().missing == 0
    assert coll.files_check().ok == 1
    coll.rename_key(result["key"], "Renamed")
    coll.commit()
    assert coll.files.material_variants("Renamed")[0]["intact"]
    assert coll.files_check().ok == 1


def test_copy_and_role_settings_with_overrides(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Key,title={Historical engines}}\n")
    source = tmp_path / "original.pdf"
    source.write_bytes(b"annotated bytes")
    coll = Bibliography.open(bib)
    coll.ensure_files_dir()
    coll.set_metadata("pinax-adopt-mode", "copy")
    coll.set_metadata("pinax-adopt-role", "preprint")
    coll.commit()
    coll.adopt_file("Key", source)
    coll.commit()
    assert source.exists()
    assert coll.files.material_variants("Key")[0]["role"] == "preprint"
    coll.adopt_file("Key", source, mode="move", role="unclassified")
    coll.commit()
    assert not source.exists()
    assert len(coll.files.material_variants("Key")) == 2
    assert coll.files_check().ok == 1


def test_mixed_batch_repeats_and_restores(manifest, tmp_path):
    source = make_pdf(tmp_path / "article.pdf", bib=BIB)
    book = make_pdf(
        tmp_path / "book.pdf",
        text="On Historical Machines",
        title="On Historical Machines",
        bib=BIB.replace("@article", "@book")
        .replace("10.5555/engines", "10.5555/books")
        .replace(TITLE, "On Historical Machines")
        .replace("journal=", "publisher="),
    )
    unknown = make_pdf(tmp_path / "unknown.pdf", text="", title="")
    other = tmp_path / "data.txt"
    other.write_text("not executable")
    lib = Library.open(manifest)
    plan = lib.prepare_ingestion([source, book, unknown, other])
    assert plan.report["accepted_records"] == 2, plan.report
    assert plan.report["pending"] == 2
    assert not (tmp_path / ".pynakes-ingest").exists()
    plan.commit(expect_sha256=plan.sha256)
    assert not source.exists() and not book.exists() and unknown.exists()
    assert len(Bibliography.open(tmp_path / "books.bib").entries) == 1
    assert len(Bibliography.open(tmp_path / "inbox.bib").entries) == 1
    repeat = Library.open(manifest).prepare_ingestion([source, book, unknown, other])
    assert [r["status"] for r in repeat.report["results"]][:2] == ["already_present"] * 2
    repeat.commit()
    restored = tmp_path / "restored"
    shutil.copytree(tmp_path, restored, ignore=shutil.ignore_patterns("restored", "*.pdf"))
    # Copy managed stores with PDF bytes, then remove dependence on the originals.
    for name in ("books.files", "inbox.files"):
        shutil.rmtree(restored / name)
        shutil.copytree(tmp_path / name, restored / name)
    for name in ("books", "inbox"):
        coll = Bibliography.open(restored / f"{name}.bib")
        assert coll.files_check().ok == 1
        assert coll.files.material_variants(next(iter(coll.entries)))[0]["intact"]


@pytest.mark.parametrize("boundary", range(1, 8))
def test_interruption_recovery_at_each_write(manifest, tmp_path, monkeypatch, boundary):
    source = make_pdf(tmp_path / "article.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion([source])
    original_write = _transaction._atomic_write_bytes
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == boundary:
            raise OSError("injected interruption")
        return original_write(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(_transaction, "_atomic_write_bytes", interrupted)
        try:
            plan.commit()
        except OSError:
            assert source.exists()
    lib = Library.open(manifest)
    state = state_path(lib)
    if (state / "journal.json").exists():
        assert lib.recover_ingestion()["recovered"]
    elif source.exists():
        lib.prepare_ingestion([source]).commit()
    assert not source.exists()
    coll = Bibliography.open(tmp_path / "inbox.bib")
    assert len(coll.entries) == 1 and coll.files_check().ok == 1
    assert not Library.open(manifest).recover_ingestion()["recovered"]


def test_stale_source_and_rules_refuse_without_moves(manifest, tmp_path):
    source = make_pdf(tmp_path / "article.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion([source])
    source.write_bytes(source.read_bytes() + b"% changed")
    with pytest.raises(ValueError, match="changed"):
        plan.commit()
    assert source.exists()
    plan = Library.open(manifest).prepare_ingestion([source])
    manifest.write_text(manifest.read_text() + "\n# new rules\n")
    with pytest.raises(Exception, match="changed"):
        plan.commit()
    assert not (tmp_path / "inbox.files").exists()


def test_cli_preview_apply_and_review(manifest, tmp_path):
    source = make_pdf(tmp_path / "article.pdf", bib=BIB)
    runner = CliRunner()
    args = ["library", "ingest", str(manifest), str(source), "--json"]
    preview = runner.invoke(app, [*args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    digest = json.loads(preview.output)["plan_sha256"]
    applied = runner.invoke(app, [*args, "--expect-plan", digest])
    assert applied.exit_code == 0, applied.output
    assert not source.exists()
    review = runner.invoke(app, ["library", "review", str(manifest), "--json"])
    assert review.exit_code == 0 and len(json.loads(review.output)["sources"]) == 1


def test_review_decision_resolves_pending_without_fake_records(manifest, tmp_path):
    source = make_pdf(tmp_path / "scan.pdf", text="", title="")
    lib = Library.open(manifest)
    plan = lib.prepare_ingestion([source])
    assert plan.report["pending"] == 1
    plan.commit()
    from pynakes.filestore._transaction import digest

    decision = {
        str(source): {
            "sha256": digest(source),
            "record": {
                "entry_type": "book",
                "fields": {
                    "title": "On Historical Machines",
                    "author": "Example, Alice",
                    "year": "1900",
                    "publisher": "Example Press",
                },
            },
        }
    }
    plan = Library.open(manifest).prepare_ingestion([source], decisions=decision, mode="copy")
    assert plan.report["accepted_records"] == 1, plan.report
    plan.commit()
    assert source.exists()
    assert len(Bibliography.open(tmp_path / "books.bib").entries) == 1
    receipt = next(iter(Library.open(manifest).ingestion_ledger()["sources"].values()))
    assert receipt["history"][0]["status"] == "pending"
    assert receipt["selected_from"] == "reviewed_metadata"


def test_unknown_decision_and_stale_metadata_remain_pending(manifest, tmp_path):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion(
        [source], decisions={str(source): {"sha256": "stale", "exclude": "not selected"}}
    )
    assert plan.report["pending"] == 1
    plan.commit()
    assert source.exists()
    assert not Bibliography.open(tmp_path / "inbox.bib").entries


def test_multiple_variants_duplicate_bytes_and_key_rename(manifest, tmp_path):
    one = make_pdf(tmp_path / "one.pdf", bib=BIB)
    two = make_pdf(tmp_path / "two.pdf", bib=BIB, annotate=True)
    duplicate = tmp_path / "duplicate.pdf"
    duplicate.write_bytes(one.read_bytes())
    plan = Library.open(manifest).prepare_ingestion([one, two, duplicate], mode="copy")
    assert plan.report["accepted_records"] == 1, plan.report
    plan.commit()
    coll = Bibliography.open(tmp_path / "inbox.bib")
    key = next(iter(coll.entries))
    assert len(coll.files.material_variants(key)) == 2
    assert coll.files_check().ok == 2
    assert len(coll.files.material_variants(key)[0]["sources"]) == 2
    coll.rename_key(key, "Historical")
    coll.commit()
    repeat = Library.open(manifest).prepare_ingestion([one], mode="copy")
    assert repeat.report["results"][0]["key"] == "Historical"


def test_recovery_refuses_external_changes(manifest, tmp_path, monkeypatch):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion([source])
    write = _transaction._atomic_write_bytes

    def fail_bib(path, *args):
        if path.suffix == ".bib":
            raise OSError("interrupt before bibliography")
        return write(path, *args)

    with monkeypatch.context() as patch:
        patch.setattr(_transaction, "_atomic_write_bytes", fail_bib)
        with pytest.raises(OSError):
            plan.commit()
    bib = tmp_path / "inbox.bib"
    bib.write_bytes(bib.read_bytes() + b"% External edit\n")
    with pytest.raises(ValueError, match="external changes"):
        Library.open(manifest).recover_ingestion()
    assert source.exists()
    assert bib.read_bytes().endswith(b"% External edit\n")


def test_recovery_after_source_removal_before_journal_cleanup(manifest, tmp_path, monkeypatch):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion([source])
    unlink = Path.unlink

    def interrupt(path, *args, **kwargs):
        if path.name == "journal.json":
            raise OSError("interrupt at final cleanup")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupt)
        with pytest.raises(OSError):
            plan.commit()
    assert not source.exists()
    assert Library.open(manifest).recover_ingestion()["recovered"]


def test_failed_adoption_does_not_stage_an_entry(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{pynakes-meta: pinax-files-dir:files;}\n", encoding="utf-8")
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    coll = Bibliography.open(bib)
    row = coll.import_pdfs([source], role="invalid").results[0]
    assert row["status"] == "failed"
    assert not coll.is_dirty and not coll.entries


def test_variants_copy_remove_and_missing_diagnostics(tmp_path):
    from pynakes.filestore import FileStore

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"example")
    store = FileStore(tmp_path / "files", tmp_path / "one.bib")
    store.adopt_file("A", source, mode="copy")
    store.adopt_file("B", source, mode="copy")
    destination = FileStore(tmp_path / "other", tmp_path / "two.bib")
    assert destination.plan_material_copy(store, "A")[0]["kind"] == "variant"
    destination.copy_materials_from(store, "A")
    assert destination.material_variants("A")[0]["intact"]
    store.remove_materials("A")
    assert store.material_variants("B")[0]["intact"]
    record = destination.material_variants("A")[0]
    Path(record["absolute_path"]).unlink()
    assert destination.scan(["A"]).drift[0]["kind"] == "variant"
    store.remove_materials("B")
    assert not list((store.root / ".pinax" / "objects").iterdir())


def test_misleading_embedded_title_stays_pending(manifest, tmp_path):
    source = make_pdf(
        tmp_path / "misleading.pdf", bib=BIB, text="A completely different document", title=TITLE
    )
    row = Library.open(manifest).prepare_ingestion([source]).report["results"][0]
    assert row["status"] == "pending" and row["reason"] == "document_title_needs_review"


def test_explicit_lookup_is_opt_in_and_remains_reviewable(manifest, tmp_path, monkeypatch):
    from pynakes import lookup
    from pynakes.filestore._transaction import digest

    source = make_pdf(tmp_path / "unknown.pdf", text="", title="")
    calls = []
    monkeypatch.setattr(
        lookup,
        "find_reference",
        lambda query, **kw: calls.append(query) or lookup.LookupReport(query, "fixture", []),
    )
    decision = {str(source): {"sha256": digest(source), "query": "Historical engines"}}
    lib = Library.open(manifest)
    assert lib.prepare_ingestion([source], decisions=decision).report["pending"] == 1
    assert not calls
    row = lib.prepare_ingestion([source], decisions=decision, online=True).report["results"][0]
    assert calls == ["Historical engines"] and row["reason"] == "review_lookup_candidates"


def test_math_title_and_front_matter_isbn(tmp_path):
    import pymupdf

    from pynakes._pdf_evidence import inspect_pdf, normalized_title

    assert normalized_title(r"A theory of $\alpha^2$ oscillations") == normalized_title(
        "A theory of α² oscillations"
    )
    source = tmp_path / "book.pdf"
    with pymupdf.open() as doc:
        for text in [
            "On Historical Machines",
            "Example Press",
            "Copyright 1900",
            "ISBN: 978-0-306-40615-7",
            "References\nISBN: 978-0-201-03801-9",
        ]:
            page = doc.new_page()
            page.insert_text((50, 50), text)
        doc.save(source)
    evidence = inspect_pdf(source)
    assert any(c["kind"] == "isbn" and c["page"] == 4 for c in evidence.identifiers)
    assert any(c["kind"] == "isbn" and c["reason"] == "reference_list" for c in evidence.rejected)
    assert len(evidence.locations) == 5


def test_receipts_pin_plan_and_bytes_without_growing_retry_history(manifest, tmp_path):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    first = Library.open(manifest).prepare_ingestion([source], mode="copy")
    report = first.commit(expect_sha256=first.sha256)
    assert report["results"][0]["plan_sha256"] == report["plan_sha256"]
    bib = manifest.parent / report["results"][0]["bibliography"]
    assert report["results"][0]["bibliography_sha256"] == _transaction.digest(bib)
    assert report["results"][0]["material_sha256"] == _transaction.digest(source)
    for _ in range(3):
        repeat = Library.open(manifest).prepare_ingestion([source], mode="copy")
        assert repeat.report["modified_entries"] == 0
        repeat.commit()
    ledger = Library.open(manifest).ingestion_ledger()
    assert len(next(iter(ledger["sources"].values()))["history"]) == 1


def test_move_refuses_shared_attachment_and_owning_bibliography(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Original notes")
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{pynakes-meta: pinax-files-dir:files;}\n"
        "@misc{A, title={History}, file={:notes.txt:TXT}}\n"
        "@misc{B, title={Machines}}\n"
    )
    coll = Bibliography.open(bib)
    with pytest.raises(ValueError, match="another entry"):
        coll.adopt_file("B", source)
    with pytest.raises(ValueError, match="owning bibliography"):
        coll.adopt_file("B", bib)
    coll.adopt_file("B", source, mode="copy")
    coll.commit()
    assert source.read_text() == "Original notes"
    assert ":TXT" in Bibliography.open(bib).entries["B"].fields["file"]


def test_destination_collision_and_source_edit_retain_original(manifest, tmp_path, monkeypatch):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    plan = Library.open(manifest).prepare_ingestion([source])
    target = manifest.parent / plan.report["results"][0]["material"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"External data")
    with pytest.raises(ValueError, match="destination changed"):
        plan.commit()
    assert source.exists() and target.read_bytes() == b"External data"
    target.unlink()
    write = _transaction._atomic_write_bytes

    def edit_source(path, data, directory):
        write(path, data, directory)
        if path.name == "ledger.json":
            source.write_bytes(b"Changed after staging")

    with monkeypatch.context() as patch:
        patch.setattr(_transaction, "_atomic_write_bytes", edit_source)
        with pytest.raises(ValueError, match="source changed"):
            plan.commit()
    assert source.read_bytes() == b"Changed after staging"
    assert target.exists()
    with pytest.raises(ValueError, match="source changed"):
        Library.open(manifest).recover_ingestion()


def test_embedded_metadata_is_compared_online(manifest, tmp_path, monkeypatch):
    from pynakes import importer
    from pynakes.model import BibEntry

    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    calls = []

    def resolve(lib, identifier, **kwargs):
        calls.append(identifier)
        return None, BibEntry(
            "Provider",
            "article",
            {
                "title": TITLE,
                "author": "Lovelace, Ada",
                "year": "1901",
                "doi": "10.5555/engines",
                "journal": "Historical Engines",
            },
        )

    monkeypatch.setattr(importer, "prepare_imported_reference", resolve)
    plan = Library.open(manifest).prepare_ingestion([source], online=True)
    assert calls == ["10.5555/engines"]
    row = plan.report["results"][0]
    assert row["status"] == "pending" and row["reason"] == "metadata_disagreement"
    assert "year" in row["field_choices"]
    assert source.exists()


@pytest.mark.parametrize("competing", [False, True])
def test_late_book_title_and_conflicting_isbns(manifest, tmp_path, monkeypatch, competing):
    import pymupdf

    from pynakes import importer
    from pynakes.model import BibEntry

    source = tmp_path / "book.pdf"
    with pymupdf.open() as document:
        for text in [
            "Example Press",
            "Copyright 1900",
            "On Historical Machines",
            "ISBN: 978-0-306-40615-7" + ("\nISBN: 978-0-201-03801-9" if competing else ""),
        ]:
            document.new_page().insert_text((50, 50), text)
        document.save(source)

    def resolve(lib, identifier, **kwargs):
        return None, BibEntry(
            "Book",
            "book",
            {
                "title": "On Historical Machines",
                "author": "Lovelace, Ada",
                "year": "1900",
                "publisher": "Example Press",
                "isbn": identifier.removeprefix("ISBN:"),
            },
        )

    monkeypatch.setattr(importer, "prepare_imported_reference", resolve)
    row = Library.open(manifest).prepare_ingestion([source], online=True).report["results"][0]
    if competing:
        assert row["status"] == "pending" and row["reason"] == "multiple_supported_records"
    else:
        assert row["status"] == "committed" and row["bibliography"] == "books.bib"
        assert row["title_evidence"][0]["page"] == 3


def test_repeat_requires_intact_provenance_and_guards_it(manifest, tmp_path):
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    result = Library.open(manifest).prepare_ingestion([source], mode="copy").commit()
    owner = Bibliography.open(manifest.parent / result["results"][0]["bibliography"])
    assert owner.files is not None
    preview = Library.open(manifest).prepare_ingestion([source], mode="copy")
    owner.files.manifest_path.unlink()
    with pytest.raises(ValueError, match="input changed"):
        preview.commit()
    row = Library.open(manifest).prepare_ingestion([source], mode="copy").report["results"][0]
    assert row["status"] == "pending" and "manifest_missing" in row["reason"]
    assert source.exists()
