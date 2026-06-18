"""Tests for the Volume engine facade."""

from pathlib import Path

import pytest

from pynakes.bibtex_writer import write_bib
from pynakes.engine import ExternalModificationError, Volume
from pynakes.normalize import NormalizeOptions

FIXTURES = Path(__file__).parent / "fixtures"


def test_volume_open_exposes_read_only_views(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text((FIXTURES / "duplicate_entries.bib").read_text())

    vol = Volume.open(bib)

    assert vol.path == bib
    assert len(vol.entries) == 7
    assert vol.duplicate_keys() == {"Smith2020": 2, "Jones2021": 2, "Brown2019": 3}
    assert any(issue.type == "duplicate_key" for issue in vol.lint())
    assert vol.is_dirty is False


def test_volume_group_and_field_operations_mutate_in_memory_only(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (FIXTURES / "simple.bib").read_text()
    bib.write_text(original)
    vol = Volume.open(bib)

    assert vol.add_to_group("Smith2020", "Read") == 1
    assert vol.rename_field("journal", "journaltitle", where="type = article") == 1

    assert vol.is_dirty is True
    assert "Read" in vol.entries["Smith2020"].fields["groups"]
    assert "journaltitle" in vol.entries["Smith2020"].fields
    assert bib.read_text() == original


def test_volume_preview_diff_commit_and_reset(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (FIXTURES / "simple.bib").read_text()
    bib.write_text(original)
    vol = Volume.open(bib)

    vol.add_to_group("Smith2020", "Read")

    assert vol.is_dirty is True
    assert vol.is_modified is True
    assert bib.read_text() == original
    assert "+  groups = {Read}" in vol.diff()

    vol.reset()
    assert vol.is_dirty is False
    assert vol.preview() == original

    vol.add_to_group("Smith2020", "Read")
    result = vol.commit()

    assert result.modified is True
    assert result.changed_entries == 1
    assert "groups = {Read}" in bib.read_text()
    assert vol.is_dirty is False
    assert vol.diff() == ""


def test_volume_reload_discards_disk_changes_when_forced(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {Old}\n}\n")
    vol = Volume.open(bib)

    bib.write_text("@article{A,\n  title = {New}\n}\n")
    vol.reload(force=True)

    assert vol.entries["A"].fields["title"] == "New"


def test_volume_commit_detects_external_modification(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text((FIXTURES / "simple.bib").read_text())
    vol = Volume.open(bib)
    vol.add_to_group("Smith2020", "Read")

    bib.write_text(bib.read_text() + "\n@comment{external}\n")

    assert vol.externally_changed() is True
    with pytest.raises(ExternalModificationError):
        vol.commit()


def test_volume_key_repair_and_write_bib_preview() -> None:
    vol = Volume.from_text((FIXTURES / "duplicate_entries.bib").read_text())

    renames = vol.repair_keys()
    text = write_bib(vol.lib)

    assert renames
    assert vol.duplicate_keys() == {}
    assert "@article{Smith2020_2," in text


def test_volume_normalize_and_convert() -> None:
    vol = Volume.from_text(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {An AI Paper},\n"
        "  journal = {Physical Review Letters},\n"
        "  doi = {https://doi.org/10.5555/ABC},\n"
        "  year = {2020}\n"
        "}\n"
    )

    norm = vol.normalize(NormalizeOptions(author_style="none"))
    conv = vol.convert("biblatex")

    entry = vol.entries["A"]
    assert norm.dois == 1
    assert conv.fields_renamed >= 1
    assert entry.fields["doi"] == "10.5555/ABC"
    assert entry.fields["journaltitle"] == "Phys. Rev. Lett."


def test_volume_files_check_uses_bound_path(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_text("pdf")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T},\n  file = {paper.pdf}\n}\n")

    vol = Volume.open(bib)
    report = vol.files_check()

    assert report.checked == 1
    assert report.ok == 1
    assert report.files[0].resolved_path == tmp_path / "paper.pdf"


def test_volume_journal_operations() -> None:
    vol = Volume.from_text(
        "@article{A,\n  title = {T},\n  journal = {Physical Review Letters},\n  year = {2020}\n}\n"
    )

    check = vol.journals_check()
    report = vol.abbreviate_journals()

    assert check == [{"journal": "Physical Review Letters", "status": "builtin_exact"}]
    assert report.changed == 1
    assert vol.entries["A"].fields["journal"] == "Phys. Rev. Lett."


def test_volume_import_doi_adds_entry_in_memory(monkeypatch) -> None:
    vol = Volume.from_text("")
    provider_bibtex = """@article{provider,
  author = {Jane Smith},
  title = {A DOI Paper},
  journal = {Journal},
  year = {2024},
  doi = {10.5555/example}
}
"""
    monkeypatch.setattr("pynakes.doi.fetch_bibtex_for_doi", lambda doi: provider_bibtex)

    entry = vol.import_doi("10.5555/example")

    assert entry.key == "Smith2024DOI"
    assert vol.entries["Smith2024DOI"] is entry
    assert vol.is_dirty is True
