"""``--backup`` never overwrites an earlier backup.

The first backup of ``refs.bib`` is ``refs.bib.bak``; while that exists, the
next is ``refs.bib.bak.1``, then ``refs.bib.bak.2``, and so on: the lowest free
number, so the names depend only on what is already on disk.
"""

from pathlib import Path

from typer.testing import CliRunner

from pynakes._atomic import next_backup_path
from pynakes.cli import app
from pynakes.filestore import FileStore
from pynakes.io import save_text

runner = CliRunner()


def test_next_backup_path_takes_the_lowest_free_name(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    assert next_backup_path(path) == tmp_path / "refs.bib.bak"
    (tmp_path / "refs.bib.bak").write_text("")
    assert next_backup_path(path) == tmp_path / "refs.bib.bak.1"
    (tmp_path / "refs.bib.bak.1").write_text("")
    (tmp_path / "refs.bib.bak.3").write_text("")
    assert next_backup_path(path) == tmp_path / "refs.bib.bak.2"


def test_repeated_saves_keep_every_backup(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("first\n")
    for text in ("second\n", "third\n", "fourth\n"):
        assert save_text(text, str(path), backup=True).success
    assert path.read_text() == "fourth\n"
    assert (tmp_path / "refs.bib.bak").read_text() == "first\n"
    assert (tmp_path / "refs.bib.bak.1").read_text() == "second\n"
    assert (tmp_path / "refs.bib.bak.2").read_text() == "third\n"


def test_non_atomic_save_keeps_the_earlier_backup(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("first\n")
    assert save_text("second\n", str(path), backup=True, atomic=False).success
    result = save_text("third\n", str(path), backup=True, atomic=False)
    assert result.backup_path == str(tmp_path / "refs.bib.bak.1")
    assert (tmp_path / "refs.bib.bak").read_text() == "first\n"


def test_cli_backup_twice_keeps_the_original(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = "@book{Newton1687,\n  title = {Principia}\n}\n"
    bib.write_text(original)
    for year in ("1687", "1713"):
        result = runner.invoke(
            app, ["fields", "set", str(bib), "year", year, "--key", "Newton1687", "--backup"]
        )
        assert result.exit_code == 0, result.output
    assert (tmp_path / "refs.bib.bak").read_text() == original
    assert "1687" in (tmp_path / "refs.bib.bak.1").read_text()
    assert "1713" in bib.read_text()


def test_manifest_backup_never_overwrites(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@comment{pynakes-meta:\npinax-files-dir:\n}\n")
    store = FileStore(root=tmp_path / "files", bib_path=bib)
    store.write_manifest({"version": 1, "files": {}})
    store.write_manifest({"version": 1, "files": {}}, backup=True)
    store.write_manifest({"version": 1, "files": {}}, backup=True)
    pinax = store.manifest_path.parent
    assert (pinax / "manifest.json.bak").exists()
    assert (pinax / "manifest.json.bak.1").exists()
