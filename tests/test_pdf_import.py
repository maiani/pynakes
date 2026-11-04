"""PDF ingestion with generated documents and offline provider fixtures."""

import hashlib
import json
import subprocess

import pymupdf
import pytest

from pynakes import _pdf_evidence, importer
from pynakes.cli import app
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.model import BibEntry
from pynakes.pdf_import import PDFDependencyError, inspect_pdf

TITLE = "A Theory of Imaginary Engines"
BIB = f"@article{{Provider1900, title={{{TITLE}}}, author={{Example, Alice}}, year={{1900}}, doi={{10.5555/engines}}, journal={{Journal of Examples}}}}"


def make_pdf(
    path,
    *,
    bib=None,
    text=TITLE,
    title=TITLE,
    xmp=None,
    attachment=None,
    encrypted=False,
    annotate=False,
):
    with pymupdf.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
        doc.set_metadata({"title": title})
        if bib is not None:
            xref = int(doc.xref_get_key(-1, "Info")[1].split()[0])
            doc.xref_set_key(xref, "BibTeX", pymupdf.get_pdf_str(bib))
        if xmp is not None:
            doc.set_xml_metadata(xmp)
        if attachment is not None:
            doc.embfile_add("citation.bib", attachment.encode())
        if annotate:
            annotation = page.add_text_annot((40, 80), "Private reading note")
            annotation.update()
        options = (
            {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": "secret", "owner_pw": "owner"}
            if encrypted
            else {}
        )
        doc.save(path, **options)
    return path


@pytest.fixture
def coll(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text("% Keep this exact comment.\n", encoding="utf-8")
    return Bibliography.open(path)


def test_offline_import_preserves_source_and_is_repeatable(tmp_path, coll, monkeypatch):
    monkeypatch.setattr(
        importer,
        "prepare_imported_reference",
        lambda *a, **k: pytest.fail("offline import went online"),
    )
    pdf = make_pdf(tmp_path / "original.pdf", bib=BIB, annotate=True)
    original = pdf.read_bytes()
    report = coll.import_pdfs([pdf]).to_dict()
    assert report["summary"]["imported"] == 1
    assert report["results"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert coll.path.read_text().startswith("% Keep this exact comment.")
    assert "@article" not in coll.path.read_text()
    assert coll.files_check().ok == 1
    coll.commit()
    assert coll.path.read_text().startswith("% Keep this exact comment.\n")
    assert pdf.read_bytes() == original
    duplicate = tmp_path / "another-name.pdf"
    duplicate.write_bytes(original)
    assert coll.import_pdfs([duplicate]).to_dict()["summary"]["existing"] == 1
    assert not coll.is_dirty
    assert len(coll.entries) == 1


def test_multiple_versions_attach_without_overwriting_fields(tmp_path, coll):
    first = make_pdf(tmp_path / "one.pdf", bib=BIB)
    second = make_pdf(tmp_path / "two.pdf", bib=BIB.replace(TITLE, TITLE + " Revised"))
    assert coll.import_pdfs([first, second]).to_dict()["summary"]["linked"] == 1
    assert len(coll.entries) == 1
    assert next(iter(coll.entries.values())).fields["title"] == TITLE
    assert coll.files_check().ok == 2


def test_existing_bytes_do_not_ignore_explicit_choices(tmp_path, coll):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    coll.import_pdfs([pdf], key="Chosen")
    coll.commit()
    assert coll.import_pdfs([pdf], key="Other").results[0]["status"] == "ambiguous"
    assert coll.import_pdfs([pdf], identifier="10.5555/other").results[0]["status"] == "ambiguous"
    assert coll.import_pdfs([pdf], identifier="10.5555/engines").results[0]["status"] == "existing"
    assert not coll.is_dirty


def test_source_change_blocks_commit_and_reset_clears_guard(tmp_path, coll):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    coll.import_pdfs([pdf])
    before = coll.path.read_bytes()
    pdf.write_bytes(pdf.read_bytes() + b"\n% changed\n")
    with pytest.raises(ExternalModificationError):
        coll.commit()
    assert coll.path.read_bytes() == before
    coll.reset()
    coll.commit()
    assert not coll.is_dirty


def test_source_deleted_blocks_commit(tmp_path, coll):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    coll.import_pdfs([pdf])
    pdf.unlink()
    with pytest.raises(ExternalModificationError):
        coll.commit()


def test_mixed_batch_keeps_every_outcome(tmp_path, coll):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    make_pdf(folder / "a.pdf", bib=BIB)
    (folder / "b.pdf").write_bytes(b"not a pdf")
    make_pdf(folder / "c.pdf", text="", title="")
    make_pdf(folder / "d.pdf", text="doi:10.5555/unknown")
    (folder / "ignored.txt").write_text("not a PDF")
    report = coll.import_pdfs([folder]).to_dict()
    assert [r["status"] for r in report["results"]] == [
        "imported",
        "failed",
        "unresolved",
        "needs_online",
    ]
    assert not report["complete"]
    coll.commit()
    assert len(Bibliography.open(coll.path).entries) == 1


def test_embedded_private_fields_are_not_imported(tmp_path, coll):
    bib = BIB[:-1] + ", note={Private note}, file={/private/path.pdf}, groups={Private group}}"
    pdf = make_pdf(tmp_path / "one.pdf", bib=bib)
    coll.import_pdfs([pdf])
    entry = next(iter(coll.entries.values()))
    assert "note" not in entry.fields and "groups" not in entry.fields
    assert "/private/path" not in entry.fields["file"]


@pytest.mark.parametrize(
    "setting,override,expected",
    [
        ("provider", None, "Provider1900"),
        ("provider", "generated", "Example1900Theory"),
        ("generated", "provider", "Provider1900"),
    ],
)
def test_key_source_setting_and_override(tmp_path, coll, setting, override, expected):
    coll.set_metadata("import-key-source", setting)
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    coll.import_pdfs([pdf], key_source=override)
    assert list(coll.entries.keys()) == [expected]


def test_explicit_key_and_collision(tmp_path, coll):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    coll.add_entry("misc", "Taken", {"title": "Another Work"})
    report = coll.import_pdfs([pdf], key="Taken").to_dict()
    assert report["summary"]["ambiguous"] == 1
    assert len(coll.entries) == 1
    assert coll.import_pdfs([pdf], key="Chosen").results[0]["key"] == "Chosen"


def test_title_corroboration_and_explicit_selection(tmp_path, coll, monkeypatch):
    pdf = make_pdf(tmp_path / "one.pdf", text=TITLE + "\nAbstract\nCites doi:10.5555/unrelated")
    calls = []

    def resolve(lib, value, **kwargs):
        calls.append(value)
        return "doi", BibEntry(
            "Remote",
            "article",
            {
                "title": "An Entirely Unrelated Paper",
                "author": "Other, Beatrice",
                "year": "1901",
                "doi": value,
            },
        )

    monkeypatch.setattr(importer, "prepare_imported_reference", resolve)
    assert coll.import_pdfs([pdf]).results[0]["status"] == "needs_online"
    assert not calls
    assert coll.import_pdfs([pdf], online=True).results[0]["status"] == "unresolved"
    assert not coll.is_dirty
    assert (
        coll.import_pdfs([pdf], online=True, identifier="10.5555/unrelated").results[0]["status"]
        == "imported"
    )


def test_online_matching_title_and_multiple_candidates(tmp_path, coll, monkeypatch):
    pdf = make_pdf(tmp_path / "one.pdf", text=TITLE + "\ndoi:10.5555/one\ndoi:10.5555/two")

    def resolve(lib, value, **kwargs):
        return "doi", BibEntry(
            "Remote",
            "article",
            {"title": TITLE, "author": "Example, Alice", "year": "1900", "doi": value},
        )

    monkeypatch.setattr(importer, "prepare_imported_reference", resolve)
    assert coll.import_pdfs([pdf], online=True).results[0]["status"] == "ambiguous"
    assert not coll.is_dirty
    assert (
        coll.import_pdfs([pdf], online=True, identifier="10.5555/one").results[0]["status"]
        == "imported"
    )


def test_online_single_corroborated_candidate(tmp_path, coll, monkeypatch):
    pdf = make_pdf(tmp_path / "one.pdf", text=TITLE + "\ndoi:10.5555/one", title="")
    monkeypatch.setattr(
        importer,
        "prepare_imported_reference",
        lambda *a, **k: (
            "doi",
            BibEntry(
                "Remote",
                "article",
                {"title": TITLE, "author": "Example, Alice", "year": "1900", "doi": "10.5555/one"},
            ),
        ),
    )
    row = coll.import_pdfs([pdf], online=True).results[0]
    assert row["status"] == "imported"
    assert row["selected_from"] == "identifier_and_title"


def test_provider_failure_does_not_stage(tmp_path, coll, monkeypatch):
    pdf = make_pdf(tmp_path / "one.pdf", text="doi:10.5555/one")

    def fail(*args, **kwargs):
        raise importer.ReferenceImportError("Unavailable")

    monkeypatch.setattr(importer, "prepare_imported_reference", fail)
    row = coll.import_pdfs([pdf], online=True).results[0]
    assert row["status"] == "unresolved"
    assert row["resolution"][0]["error"] == "Unavailable"
    assert not coll.is_dirty


def test_arxiv_evidence_and_reference_section_exclusion(tmp_path):
    pdf = make_pdf(
        tmp_path / "one.pdf", text=TITLE + "\narXiv:2301.00001v2\nReferences\ndoi:10.5555/cited"
    )
    evidence = inspect_pdf(pdf)
    assert evidence.identifiers == [
        {"kind": "arxiv", "value": "2301.00001", "source": "page-text", "page": 1}
    ]


def test_embedded_bibtex_attachment_needs_document_title(tmp_path, coll):
    pdf = make_pdf(
        tmp_path / "one.pdf", attachment=BIB, title="Another Document", text="Another Document"
    )
    assert coll.import_pdfs([pdf]).results[0]["status"] == "unresolved"
    pdf2 = make_pdf(tmp_path / "two.pdf", attachment=BIB)
    assert coll.import_pdfs([pdf2]).results[0]["status"] == "imported"


def test_xmp_metadata_and_dialect(tmp_path, coll):
    xmp = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><rdf:RDF><rdf:Description><dc:title><rdf:Alt><rdf:li xml:lang="x-default">{TITLE}</rdf:li></rdf:Alt></dc:title><dc:creator><rdf:Seq><rdf:li>Example, Alice</rdf:li><rdf:li>Other, Beatrice</rdf:li></rdf:Seq></dc:creator><prism:publicationDate>1900-01-01</prism:publicationDate><prism:doi>10.5555/engines</prism:doi></rdf:Description></rdf:RDF></x:xmpmeta>"""
    pdf = make_pdf(tmp_path / "one.pdf", xmp=xmp)
    coll.set_metadata("dialect", "biblatex")
    assert coll.import_pdfs([pdf]).results[0]["status"] == "imported"
    entry = next(iter(coll.entries.values()))
    assert entry.fields["author"] == "Example, Alice and Other, Beatrice"
    assert entry.fields["date"] == "1900-01-01"


def test_invalid_xmp_is_reported(tmp_path):
    pdf = make_pdf(tmp_path / "one.pdf", xmp="<broken>")
    assert any("Invalid XMP" in w for w in inspect_pdf(pdf).warnings)


def test_malformed_embedded_bibtex_does_not_abort_batch(tmp_path, coll):
    bad = make_pdf(tmp_path / "bad.pdf", bib="@article{bad,title={unterminated")
    good = make_pdf(tmp_path / "good.pdf", bib=BIB)
    rows = coll.import_pdfs([bad, good]).results
    assert rows[0]["status"] == "unresolved"
    assert any("Invalid embedded BibTeX" in w for w in rows[0]["warnings"])
    assert rows[1]["status"] == "imported"


def test_worker_extracts_metadata_and_limits_pages_without_rewriting(tmp_path):
    from pynakes._pdf_extract import extract

    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB, attachment=BIB, xmp="<metadata />", annotate=True)
    before = pdf.read_bytes()
    data = extract(pdf)
    assert data["info"]["BibTeX"] == BIB
    assert data["bibtex"][0]["text"] == BIB
    assert data["xmp"] == "<metadata />"
    assert TITLE in data["pages"][0]["text"]
    assert pdf.read_bytes() == before


def test_invalid_metadata_stream_does_not_hide_usable_text(tmp_path):
    pdf = tmp_path / "broken-xmp.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), TITLE + "\ndoi:10.5555/engines")
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Type /Metadata /Subtype /XML >>")
        doc.xref_set_key(doc.pdf_catalog(), "Metadata", f"{xref} 0 R")
        doc.save(pdf)
    evidence = inspect_pdf(pdf)
    assert any("Could not read XMP" in w for w in evidence.warnings)
    assert evidence.identifiers[0]["value"] == "10.5555/engines"


def test_preprint_and_published_record_need_review(tmp_path, coll):
    coll.add_entry(
        "article",
        "Published",
        {
            "title": TITLE,
            "author": "Example, Alice",
            "year": "1900",
            "doi": "10.5555/engines",
            "journal": "Journal of Examples",
        },
    )
    preprint = f"@misc{{Preprint, title={{{TITLE}}}, author={{Example, Alice}}, year={{1900}}, doi={{10.5555/engines}}, eprint={{2301.00001}}, archiveprefix={{arXiv}}}}"
    pdf = make_pdf(tmp_path / "preprint.pdf", bib=preprint)
    row = coll.import_pdfs([pdf]).results[0]
    assert row["status"] == "ambiguous"
    assert "file" not in coll.entries["Published"].fields


def test_bibtex_string_resolution_and_undefined_macro(tmp_path, coll):
    pdf = make_pdf(
        tmp_path / "one.pdf",
        bib='@string{T="A Theory of Imaginary Engines"}\n' + BIB.replace("{" + TITLE + "}", "T"),
    )
    assert coll.import_pdfs([pdf]).results[0]["status"] == "imported"
    other = make_pdf(tmp_path / "other.pdf", bib=BIB.replace("{" + TITLE + "}", "UNKNOWN"))
    assert any("resolution" in w for w in inspect_pdf(other).warnings)


def test_encrypted_missing_and_empty_directory(tmp_path, coll):
    pdf = make_pdf(tmp_path / "encrypted.pdf", encrypted=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    rows = coll.import_pdfs([pdf, tmp_path / "missing.pdf", empty]).results
    assert all(row["status"] == "failed" for row in rows)
    assert "Encrypted" in rows[0]["message"]


def test_dependency_error(monkeypatch):
    monkeypatch.setattr(_pdf_evidence.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(PDFDependencyError, match="pynakes\\[pdf\\]"):
        inspect_pdf("anything.pdf")


def test_timeout_and_changing_source(tmp_path, coll, monkeypatch):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)

    def timeout(path):
        raise subprocess.TimeoutExpired("pdf reader", 30)

    monkeypatch.setattr(_pdf_evidence, "_read_pdf", timeout)
    assert coll.import_pdfs([pdf]).results[0]["status"] == "failed"

    def changed(path):
        path.write_bytes(path.read_bytes() + b"%changed")
        return {}

    monkeypatch.setattr(_pdf_evidence, "_read_pdf", changed)
    with pytest.raises(ValueError, match="changed during"):
        inspect_pdf(pdf)


def test_path_delimiters_and_duplicate_keys(tmp_path, coll):
    pdf = make_pdf(tmp_path / "semi;colon.pdf", bib=BIB)
    assert coll.import_pdfs([pdf]).results[0]["status"] == "imported"
    assert coll.files_check().ok == 1
    duplicate = Bibliography.from_text(BIB + "\n" + BIB, path=tmp_path / "dup.bib")
    assert duplicate.import_pdfs([pdf]).results[0]["status"] == "ambiguous"


def test_cli_preview_apply_and_repeat(tmp_path, coll, cli_runner):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    before = coll.path.read_bytes()
    args = ["ref", "from-pdf", str(coll.path), str(pdf), "--json"]
    preview = cli_runner.invoke(app, [*args, "--dry-run", "--diff"])
    assert preview.exit_code == 0, preview.output
    data = json.loads(preview.output)
    assert data["action"] == "ref_from_pdf"
    assert data["modified"] and data["dry_run"]
    assert data["summary"]["imported"] == 1
    assert coll.path.read_bytes() == before
    applied = cli_runner.invoke(app, [*args, "--expect-sha256", data["source_sha256"]])
    assert applied.exit_code == 0, applied.output
    again = cli_runner.invoke(app, args)
    assert again.exit_code == 0, again.output
    assert not json.loads(again.output)["modified"]


def test_cli_conflict_error_partial_and_autodetect(tmp_path, coll, cli_runner, monkeypatch):
    pdf = make_pdf(
        tmp_path / "one.pdf",
        bib=BIB
        + "\n"
        + BIB.replace("10.5555/engines", "10.5555/other").replace(
            TITLE, "Another Imaginary Engine"
        ),
    )
    conflict = cli_runner.invoke(app, ["ref", "from-pdf", str(coll.path), str(pdf), "--json"])
    assert conflict.exit_code == 2, conflict.output
    assert json.loads(conflict.output)["options"]
    invalid = tmp_path / "bad.pdf"
    invalid.write_text("not a PDF")
    error = cli_runner.invoke(app, ["ref", "from-pdf", str(coll.path), str(invalid), "--json"])
    assert error.exit_code == 1, error.output
    assert json.loads(error.output)["status"] == "error"
    good = make_pdf(tmp_path / "good.pdf", bib=BIB)
    monkeypatch.chdir(tmp_path)
    partial = cli_runner.invoke(app, ["ref", "from-pdf", str(good), str(invalid), "--json"])
    assert partial.exit_code == 0, partial.output
    assert not json.loads(partial.output)["complete"]


def test_invalid_single_file_options_and_unbound_api(tmp_path, coll):
    pdf = make_pdf(tmp_path / "one.pdf", bib=BIB)
    with pytest.raises(ValueError, match="exactly one"):
        coll.import_pdfs([pdf, tmp_path / "two.pdf"], identifier="10.5555/one")
    with pytest.raises(ValueError, match="at least one"):
        coll.import_pdfs([])
    with pytest.raises(ValueError, match="bound"):
        Bibliography.from_text("").import_pdfs([pdf])
    with pytest.raises(ValueError, match="citation key"):
        coll.import_pdfs([pdf], key="bad,key")


def test_cli_precondition_checked_before_inspection(tmp_path, coll, cli_runner, monkeypatch):
    monkeypatch.setattr(
        Bibliography, "import_pdfs", lambda *a, **k: pytest.fail("inspected stale input")
    )
    result = cli_runner.invoke(
        app,
        ["ref", "from-pdf", str(coll.path), "anything.pdf", "--expect-sha256", "0" * 64, "--json"],
    )
    assert result.exit_code == 2
