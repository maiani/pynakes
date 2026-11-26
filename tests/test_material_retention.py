"""Moved originals that cannot be removed are kept and reported, never blocking.

Also covers containment through symlinked roots and the bibliography checks an
adoption makes before any material moves. Invented references only.
"""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import Bibliography
from pynakes.cli import app
from pynakes.filestore import _transaction

BIB = (
    "@comment{pynakes-meta: pinax-files-dir:files;}\n"
    "@article{Key, title={Analytical engines}}\n"
    "@article{Other, title={Jacquard looms}}\n"
)


def write_bib(path: Path) -> Path:
    path.write_text(BIB, encoding="utf-8")
    return path


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable")


def test_unremovable_source_is_kept_and_reported(tmp_path, monkeypatch):
    bib = write_bib(tmp_path / "refs.bib")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 engines")
    unlink = Path.unlink

    def in_use(self, *args, **kwargs):
        if self == source:
            raise PermissionError(13, "in use by another process", str(self))
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", in_use)
    runner = CliRunner()
    result = runner.invoke(app, ["asset", "adopt", str(bib), "Key", str(source), "--json"])
    assert result.exit_code == 0, result.output
    [warning] = json.loads(result.output)["warnings"]
    assert warning["message"].startswith(f"Kept {source}: source could not be removed")
    assert source.read_bytes() == b"%PDF-1.4 engines"
    assert "file =" in bib.read_text(encoding="utf-8")
    # The transaction finished, so the next adoption is not blocked.
    other = tmp_path / "loom.pdf"
    other.write_bytes(b"%PDF-1.4 looms")
    result = runner.invoke(app, ["asset", "adopt", str(bib), "Other", str(other), "--json"])
    assert result.exit_code == 0, result.output
    assert not other.exists()


def test_source_that_is_the_stored_copy_is_never_removed(tmp_path):
    stored = tmp_path / "files" / "object.pdf"
    stored.parent.mkdir()
    stored.write_bytes(b"%PDF-1.4 only copy")
    alias = tmp_path / "alias.pdf"
    try:
        os.link(stored, alias)
    except OSError:
        pytest.skip("hard links are unavailable")
    item = {"path": str(alias), "sha256": _transaction.digest(stored), "target": "files/object.pdf"}
    assert _transaction._retire_source(tmp_path, item) == "source is the stored copy"
    assert stored.read_bytes() == b"%PDF-1.4 only copy"


def test_bibliography_reached_through_a_symlinked_directory(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    symlink_or_skip(link, real)
    write_bib(real / "refs.bib")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 engines")
    coll = Bibliography.open(link / "refs.bib")
    coll.adopt_file("Key", source)
    assert coll.commit().warnings == []
    assert not source.exists()
    assert coll.files is not None
    assert coll.files.material_variants("Key")[0]["intact"]


def test_containment_resolves_the_root_but_refuses_inner_symlinks(tmp_path):
    real = tmp_path / "real"
    (real / "files").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    symlink_or_skip(link, real)
    assert _transaction.contained(real, link / "files" / "x.pdf") == "files/x.pdf"
    assert _transaction.contained(link, real / "files" / "x.pdf") == "files/x.pdf"
    with pytest.raises(ValueError, match="outside the Library root"):
        _transaction.contained(real, outside / "x.pdf")
    symlink_or_skip(real / "escape", outside)
    with pytest.raises(ValueError, match="Symlink in ingestion target"):
        _transaction.contained(real, real / "escape" / "x.pdf")


def test_read_only_bibliography_refuses_adoption_before_moving(tmp_path):
    bib = write_bib(tmp_path / "refs.bib")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 engines")
    os.chmod(bib, 0o444)
    try:
        if os.access(bib, os.W_OK):
            pytest.skip("this account can write read-only files")
        coll = Bibliography.open(bib)
        coll.adopt_file("Key", source)
        with pytest.raises(OSError, match="read-only"):
            coll.commit()
        assert source.exists()
        assert not (tmp_path / "files").exists()
        assert bib.read_text(encoding="utf-8") == BIB
    finally:
        os.chmod(bib, 0o644)
