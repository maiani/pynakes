"""Operations that touch the ``.bib`` and other files cannot half-apply.

A key rename rewrites the bibliography, its TeX sources, and its Pinax
materials; a removal deletes an entry and its materials. The ``.bib`` commits
first and the other files follow it, every TeX source is checked before
anything is written, and a rewritten source keeps its bytes apart from the key.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

_needs_posix_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for this user",
)


def _library(tmp_path: Path, metadata: str = "tex-sources:paper.tex;") -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Euler1748,\n  title = {Introductio}\n}\n"
        f"@comment{{pynakes-meta: {metadata}}}\n"
    )
    return bib


def _rename(bib: Path, *extra: str):
    return runner.invoke(
        app, ["keys", "rename", str(bib), "Euler1748", "Euler1748a", *extra, "--json"]
    )


def test_a_material_conflict_stops_the_rename_before_any_tex_is_written(tmp_path: Path) -> None:
    bib = _library(tmp_path, "tex-sources:paper.tex;\npinax-files-dir:\n")
    tex = tmp_path / "paper.tex"
    tex.write_text("See \\cite{Euler1748}.\n")
    files = tmp_path / "refs.files"
    files.mkdir()
    (files / "Euler1748.preprint.pdf").write_bytes(b"old")
    (files / "Euler1748a.preprint.pdf").write_bytes(b"already here")
    before = bib.read_text()

    result = _rename(bib)

    assert result.exit_code != 0, result.output
    assert "Traceback" not in result.output
    assert bib.read_text() == before
    assert tex.read_text() == "See \\cite{Euler1748}.\n"


@_needs_posix_permissions
def test_an_unwritable_tex_source_stops_the_rename_before_anything_is_written(
    tmp_path: Path,
) -> None:
    bib = _library(tmp_path, "tex-sources:paper.tex,chapter.tex;")
    (tmp_path / "paper.tex").write_text("\\cite{Euler1748}\n")
    locked = tmp_path / "chapter.tex"
    locked.write_text("\\cite{Euler1748}\n")
    locked.chmod(0o444)
    before = bib.read_text()

    result = _rename(bib)

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "IOError"
    assert bib.read_text() == before
    assert (tmp_path / "paper.tex").read_text() == "\\cite{Euler1748}\n"


def test_a_rewritten_tex_source_keeps_its_encoding_line_endings_and_mode(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    tex = tmp_path / "paper.tex"
    original = "Die L\u00f6sung \u00fcber \\cite{Euler1748}.\r\nZweite Zeile.\r\n".encode("latin-1")
    tex.write_bytes(original)
    if sys.platform != "win32":
        tex.chmod(0o640)

    result = _rename(bib)

    assert result.exit_code == 0, result.output
    assert tex.read_bytes() == original.replace(b"Euler1748", b"Euler1748a")
    if sys.platform != "win32":
        assert tex.stat().st_mode & 0o777 == 0o640
    assert "Euler1748a" in bib.read_text()


def test_metadata_sources_outside_the_project_are_refused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere.tex"
    outside.write_text("\\cite{Euler1748}\n")
    bib = _library(project, f"tex-sources:{outside};")
    before = bib.read_text()

    result = _rename(bib)

    assert result.exit_code == 1, result.output
    assert "outside the project" in json.loads(result.output)["message"]
    assert bib.read_text() == before
    assert outside.read_text() == "\\cite{Euler1748}\n"


def test_sources_named_on_the_command_line_may_lie_anywhere(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere.tex"
    outside.write_text("\\cite{Euler1748}\n")
    bib = _library(project, "pinax-files-dir:\n")

    result = _rename(bib, str(outside))

    assert result.exit_code == 0, result.output
    assert outside.read_text() == "\\cite{Euler1748a}\n"


def test_a_git_work_tree_is_the_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "bibliography").mkdir()
    (tmp_path / "manuscript").mkdir()
    tex = tmp_path / "manuscript" / "paper.tex"
    tex.write_text("\\cite{Euler1748}\n")
    bib = _library(tmp_path / "bibliography", "tex-sources:../manuscript/paper.tex;")

    result = _rename(bib)

    assert result.exit_code == 0, result.output
    assert tex.read_text() == "\\cite{Euler1748a}\n"


@_needs_posix_permissions
def test_a_failed_removal_commit_keeps_the_materials(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    library.mkdir()
    bib = _library(library, "pinax-files-dir:\n")
    files = library / "refs.files"
    files.mkdir()
    material = files / "Euler1748.preprint.pdf"
    material.write_bytes(b"%PDF")
    bib.chmod(0o444)

    result = runner.invoke(app, ["ref", "remove", str(bib), "Euler1748", "--json"])

    assert result.exit_code == 1, result.output
    assert material.read_bytes() == b"%PDF"
    assert "Euler1748" in bib.read_text()
