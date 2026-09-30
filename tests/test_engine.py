"""Tests for the Bibliography engine facade."""

from pathlib import Path

import pytest

from pynakes import metadata as metadata_ops
from pynakes._engine_helpers import SourceSnapshot, SourceSpan
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.editing import set_entry_field
from pynakes.engine import Bibliography, ExternalModificationError
from pynakes.normalize import NormalizeOptions

FIXTURES = Path(__file__).parent / "fixtures"


def test_change_plan_reports_field_changes() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {t},\n  doi = {10.1/x}\n}\n")
    from pynakes import fields as field_ops

    field_ops.append_delimited_field(coll.lib.entries["A"], "keywords", "ml", ",", ", ")
    coll.mark_dirty(1)
    plan = coll.change_plan()
    assert plan["summary"]["modified"] == 1
    item = plan["entries"][0]
    assert item == {
        "change": "modified",
        "key": "A",
        "fields": {"keywords": {"old": None, "new": "ml"}},
    }


def test_change_plan_reports_modified_duplicate_key_entry() -> None:
    coll = Bibliography.from_text(
        "@article{A,\n"
        "  title = {First},\n"
        "  doi = {https://doi.org/10.5555/example}\n"
        "}\n\n"
        "@article{A,\n"
        "  title = {Second},\n"
        "  doi = {10.5555/example}\n"
        "}\n"
    )

    coll.normalize(NormalizeOptions(protect_titles=False, author_style="none"))
    plan = coll.change_plan()

    assert plan["summary"]["modified"] == 1
    assert plan["entries"] == [
        {
            "change": "modified",
            "key": "A",
            "entry_index": 0,
            "fields": {
                "doi": {
                    "old": "https://doi.org/10.5555/example",
                    "new": "10.5555/example",
                }
            },
        }
    ]


def test_identical_duplicate_edit_uses_source_identity() -> None:
    original_entry = "@article{A,\n  title = {Same}\n}"
    text = f"{original_entry}\n\n@comment{{separator}}\n\n{original_entry}\n"
    coll = Bibliography.from_text(text)
    second = coll.entries.get_all("A")[1]

    set_entry_field(second, "title", "Changed")
    coll.mark_dirty()

    preview = coll.preview()
    before_separator, after_separator = preview.split("@comment{separator}")
    assert "title = {Same}" in before_separator
    assert "title = {Changed}" not in before_separator
    assert "title = {Changed}" in after_separator
    assert coll.change_plan()["entries"] == [
        {
            "change": "modified",
            "key": "A",
            "entry_index": 1,
            "fields": {"title": {"old": "Same", "new": "Changed"}},
        }
    ]


def test_invalid_surgical_span_fails_instead_of_falling_back_to_full_render() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {Old}\n}\n")
    entry = coll.entries["A"]
    set_entry_field(entry, "title", "New")
    snapshot = coll._source_snapshot
    valid = snapshot.entries[id(entry)]
    invalid = SourceSpan(valid.start, valid.end, "not the pristine entry")
    coll._source_snapshot = SourceSnapshot(
        {id(entry): invalid}, snapshot.raw_comments, snapshot.comments, True
    )

    with pytest.raises(RuntimeError, match="could not apply surgical source edits"):
        coll.preview()


def test_change_plan_detects_rename_not_remove_add() -> None:
    coll = Bibliography.from_text("@article{Old,\n  title = {t}\n}\n")
    from pynakes import keys as key_ops

    key_ops.rename_key(coll.lib, "Old", "New")
    coll.mark_dirty(1)
    plan = coll.change_plan()
    assert plan["summary"] == {
        "added": 0,
        "removed": 0,
        "renamed": 1,
        "modified": 0,
        "metadata_changed": 0,
    }
    assert plan["entries"] == [{"change": "renamed", "from": "Old", "to": "New"}]


def test_change_plan_reports_metadata_changes() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {t}\n}\n")
    coll.set_metadata("normalize-dois", "on")
    plan = coll.change_plan()
    assert plan["summary"]["metadata_changed"] == 1
    assert plan["metadata"] == [{"key": "normalize-dois", "old": None, "new": "on"}]


def test_semantic_metadata_change_implies_modified_output() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {t}\n}\n")

    # Metadata helpers mutate the model without knowing about engine rendering.
    # The engine must still derive the serialized change from that model state.
    metadata_ops.set_metadata(coll.lib, "normalize-dois", "on")
    coll.mark_dirty()

    assert coll.change_plan()["summary"]["metadata_changed"] == 1
    assert coll.is_modified is True
    assert "normalize-dois: on" in coll.preview()


def test_layout_only_change_can_be_modified_with_empty_semantic_plan() -> None:
    coll = Bibliography.from_text("@article{A,title={t}}\n")

    coll.format()

    assert coll.is_modified is True
    assert not any(coll.change_plan()["summary"].values())


def test_change_plan_empty_when_unmodified() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {t}\n}\n")
    plan = coll.change_plan()
    assert plan["entries"] == []
    assert plan["summary"]["modified"] == 0


def test_volume_open_exposes_read_only_views(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text((FIXTURES / "duplicate_entries.bib").read_text())

    coll = Bibliography.open(bib)

    assert coll.path == bib
    assert len(coll.entries) == 7
    assert coll.duplicate_keys() == {"Smith2020": 2, "Jones2021": 2, "Brown2019": 3}
    assert any(issue.type == "duplicate_key" for issue in coll.lint())
    assert coll.is_dirty is False


def test_volume_group_and_field_operations_mutate_in_memory_only(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (FIXTURES / "simple.bib").read_text()
    bib.write_text(original)
    coll = Bibliography.open(bib)

    assert coll.add_to_group("Smith2020", "Read") == 1
    assert coll.rename_field("journal", "journaltitle", where="type = article") == 1

    assert coll.is_dirty is True
    assert "Read" in coll.entries["Smith2020"].fields["groups"]
    assert "journaltitle" in coll.entries["Smith2020"].fields
    assert bib.read_text() == original


def test_volume_preview_diff_commit_and_reset(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (FIXTURES / "simple.bib").read_text()
    bib.write_text(original)
    coll = Bibliography.open(bib)

    coll.add_to_group("Smith2020", "Read")

    assert coll.is_dirty is True
    assert coll.is_modified is True
    assert bib.read_text() == original
    assert "+  groups = {Read}" in coll.diff()

    coll.reset()
    assert coll.is_dirty is False
    assert coll.preview() == original

    coll.add_to_group("Smith2020", "Read")
    result = coll.commit()

    assert result.modified is True
    assert result.changed_entries == 1
    assert "groups = {Read}" in bib.read_text()
    assert coll.is_dirty is False
    assert coll.diff() == ""


def test_metadata_only_group_change_is_rendered_and_committed(tmp_path: Path) -> None:
    # Root-cause regression: metadata mutations written straight to the model
    # (group-tree CRUD) were not staged for the surgical renderer, so preview()
    # equalled the pristine text and commit() wrote nothing despite a real change.
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Shockley1949,\n  title = {The Theory of p-n Junctions}\n}\n")
    coll = Bibliography.open(bib)

    assert coll.add_group_node("Semiconductors") is True
    assert coll.is_modified is True
    assert "group-tree" in coll.preview()

    result = coll.commit()

    assert result.modified is True
    assert "Semiconductors" in bib.read_text()
    # The node survives a reopen (it was actually persisted).
    reopened = Bibliography.open(bib)
    assert [n.name for n in reopened.list_tree() or []] == ["Semiconductors"]


def test_metadata_add_then_remove_collapses_to_no_output_change() -> None:
    original = "@article{A,\n  title = {t}\n}\n"
    coll = Bibliography.from_text(original)

    coll.set_metadata("normalize-dois", "on")
    coll.remove_metadata("normalize-dois")

    assert coll.preview() == original
    assert coll.is_modified is False
    assert not any(coll.change_plan()["summary"].values())


def test_setting_existing_metadata_value_does_not_make_buffer_dirty(tmp_path: Path) -> None:
    original = "@comment{pynakes-meta:\nnormalize-dois: on\n}\n"
    bib = tmp_path / "refs.bib"
    bib.write_text(original)
    coll = Bibliography.open(bib)

    coll.set_metadata("normalize-dois", "on")

    assert coll.is_modified is False
    assert coll.is_dirty is False
    assert not any(coll.change_plan()["summary"].values())
    coll.reload()


def test_reload_refreshes_source_snapshot(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {t}\n}\n")
    coll = Bibliography.open(bib)
    replacement = "@comment{pynakes-meta:\nnormalize-dois: on\n}\n\n@article{A,\n  title = {t}\n}\n"

    bib.write_text(replacement)
    coll.reload(force=True)

    assert coll.preview() == replacement
    assert coll.is_modified is False


def test_volume_reload_discards_disk_changes_when_forced(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {Old}\n}\n")
    coll = Bibliography.open(bib)

    bib.write_text("@article{A,\n  title = {New}\n}\n")
    coll.reload(force=True)

    assert coll.entries["A"].fields["title"] == "New"


def test_volume_commit_detects_external_modification(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text((FIXTURES / "simple.bib").read_text())
    coll = Bibliography.open(bib)
    coll.add_to_group("Smith2020", "Read")

    bib.write_text(bib.read_text() + "\n@comment{external}\n")

    assert coll.externally_changed() is True
    with pytest.raises(ExternalModificationError):
        coll.commit()


def test_volume_key_repair_and_write_bib_preview() -> None:
    coll = Bibliography.from_text((FIXTURES / "duplicate_entries.bib").read_text())

    renames = coll.repair_keys()
    text = write_bib(coll.lib)

    assert renames
    assert coll.duplicate_keys() == {}
    assert "@article{Smith2020_2," in text


def test_volume_normalize_and_convert() -> None:
    coll = Bibliography.from_text(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {An AI Paper},\n"
        "  journal = {Physical Review Letters},\n"
        "  doi = {https://doi.org/10.5555/ABC},\n"
        "  year = {2020}\n"
        "}\n"
    )

    norm = coll.normalize(NormalizeOptions(author_style="none", journal_style="abbreviated"))
    conv = coll.convert("biblatex")

    entry = coll.entries["A"]
    assert norm.dois == 1
    assert conv.fields_renamed >= 1
    assert entry.fields["doi"] == "10.5555/ABC"
    assert entry.fields["journaltitle"] == "Phys. Rev. Lett."


def test_volume_files_check_uses_bound_path(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_text("pdf")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T},\n  file = {paper.pdf}\n}\n")

    coll = Bibliography.open(bib)
    report = coll.files_check()

    assert report.checked == 1
    assert report.ok == 1
    assert report.files[0].resolved_path == tmp_path / "paper.pdf"


def test_volume_journal_operations() -> None:
    coll = Bibliography.from_text(
        "@article{A,\n  title = {T},\n  journal = {Physical Review Letters},\n  year = {2020}\n}\n"
    )

    check = coll.journals_check()
    report = coll.abbreviate_journals()

    assert len(check) == 1
    assert check[0]["journal"] == "Physical Review Letters"
    assert check[0]["status"].startswith("jabref:")
    assert report.changed == 1
    assert coll.entries["A"].fields["journal"] == "Phys. Rev. Lett."


def test_volume_import_doi_adds_entry_in_memory(monkeypatch) -> None:
    coll = Bibliography.from_text("")
    provider_bibtex = """@article{provider,
  author = {Jane Smith},
  title = {A DOI Paper},
  journal = {Journal},
  year = {2024},
  doi = {10.5555/example}
}
"""
    monkeypatch.setattr("pynakes.importer.fetch_bibtex_for_doi", lambda doi: provider_bibtex)

    entry = coll.import_doi("10.5555/example")

    assert entry.key == "Smith2024DOI"
    assert coll.entries["Smith2024DOI"] is entry
    assert coll.is_dirty is True


def test_entry_edits_survives_unsnapshotted_entry_with_raw_content() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {T},\n  year = {2020}\n}\n")
    extra = parse_bib("@article{B,\n  title = {Extra},\n  year = {2021}\n}\n").entries["B"]
    coll.lib.entries.add(extra)
    coll.rename_field("title", "mytitle")
    assert "mytitle" in coll.diff()


def test_unsnapshotted_raw_entry_counts_as_changed_for_full_rewrite() -> None:
    coll = Bibliography.from_text("@article{A,\n  title = {T}\n}\n")
    extra = parse_bib("@article{B,\n  title = {Extra}\n}\n").entries["B"]
    coll.lib.entries.add(extra)

    assert coll.changed_entries_count() == 1
    assert "@article{B," in coll.preview()


def test_rename_citekey_updates_bib_and_tex(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
        "@article{OldKey,\n"
        "  author = {Alan Turing},\n"
        "  title = {Computing Machinery and Intelligence},\n"
        "  year = {1950}\n"
        "}\n"
    )
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{OldKey} and \citet{OldKey} and \cite{Other}" "\n")

    coll = Bibliography.open(bib)
    result = coll.rename_citekey("OldKey", "Turing1950Computing")

    assert result["entry_renamed"] is True
    assert result["tex_occurrences"] == 2
    coll.commit()
    assert "@article{Turing1950Computing," in bib.read_text()
    assert "@article{OldKey," not in bib.read_text()
    assert r"\cite{Turing1950Computing}" in tex.read_text()
    assert r"\citet{Turing1950Computing}" in tex.read_text()
    assert r"\cite{Other}" in tex.read_text()


def test_rename_citekey_skips_tex_when_not_requested(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{pynakes-meta: tex-sources:paper.tex;}\n"
        "@article{OldKey,\n"
        "  author = {Alan Turing},\n"
        "  title = {Computing Machinery and Intelligence},\n"
        "  year = {1950}\n"
        "}\n"
    )
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{OldKey}" "\n")

    coll = Bibliography.open(bib)
    result = coll.rename_citekey("OldKey", "Turing1950Computing", rewrite_tex=False)

    assert result["entry_renamed"] is True
    assert result["tex_occurrences"] == 0
    assert r"\cite{OldKey}" in tex.read_text()


# --- regressions: line endings and commit validation -----------------------

CRLF_LIBRARY = (
    b"@article{Euler1748,\r\n  title = {Introductio},\r\n}\r\n"
    b"\r\n% a note between entries\r\n\r\n"
    b"@book{Gauss1801,\r\n  title = {Disquisitiones},\r\n}\r\n"
)


def _only_crlf(data: bytes) -> bool:
    return data.count(b"\n") == data.count(b"\r\n")


def test_open_keeps_crlf_so_an_unmodified_library_previews_byte_for_byte(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_bytes(CRLF_LIBRARY)

    coll = Bibliography.open(bib)

    assert coll.preview().encode() == CRLF_LIBRARY
    assert coll.diff() == ""


def test_edit_and_append_keep_crlf_line_endings(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_bytes(CRLF_LIBRARY)

    coll = Bibliography.open(bib)
    set_entry_field(coll.lib.entries["Euler1748"], "year", "1748")
    coll.mark_dirty(1)
    coll.add_entry("book", "Newton1687", {"title": "Principia"})
    coll.commit()

    data = bib.read_bytes()
    assert _only_crlf(data)
    assert b"% a note between entries" in data
    assert data.index(b"Euler1748") < data.index(b"Gauss1801") < data.index(b"Newton1687")


def test_append_to_crlf_library_keeps_every_existing_byte(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_bytes(CRLF_LIBRARY)

    coll = Bibliography.open(bib)
    coll.add_entry("book", "Newton1687", {"title": "Principia"})
    coll.commit()

    data = bib.read_bytes()
    assert data.startswith(CRLF_LIBRARY)
    assert _only_crlf(data)


def test_remove_entry_from_crlf_library_touches_only_that_entry(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_bytes(CRLF_LIBRARY)

    coll = Bibliography.open(bib)
    coll.remove_entry("Gauss1801")
    coll.commit()

    data = bib.read_bytes()
    assert _only_crlf(data)
    assert data.startswith(b"@article{Euler1748,\r\n  title = {Introductio},\r\n}\r\n")
    assert b"% a note between entries" in data
    assert b"Gauss1801" not in data


def test_commit_refuses_unparseable_text_and_leaves_the_file_alone(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = b"@article{Euler1748,\n  title = {Introductio}\n}\n"
    bib.write_bytes(original)

    coll = Bibliography.open(bib)
    entry = coll.lib.entries["Euler1748"]
    entry.raw_content = "@article{Euler1748,\n  title = {Introductio\n}\n"
    coll.mark_dirty(1)

    with pytest.raises(OSError, match="Validation failed"):
        coll.commit()
    assert bib.read_bytes() == original
    assert list(tmp_path.iterdir()) == [bib]
