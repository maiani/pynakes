"""Cheap material presence, tolerant variant records, holder-named ingestion
locks and an accurate ``modified`` flag. Invented references only.
"""

import json
import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from pynakes import Library
from pynakes.cli import app
from pynakes.filestore import FileStore, _adoption, _manifest, _transaction
from tests.test_native_ingestion import library_manifest as manifest  # noqa: F401
from tests.test_pdf_import import BIB, make_pdf


@pytest.fixture(name="store")
def adopted_store(tmp_path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 analytical engines")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, title={Analytical engines}}\n", encoding="utf-8")
    store = FileStore(tmp_path / "files", bib)
    store.adopt_file("A", source, mode="copy")
    return store


def count_hashes(monkeypatch) -> list:
    calls = []
    real = _manifest._sha256_path

    def counted(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(_manifest, "_sha256_path", counted)
    monkeypatch.setattr(_adoption, "_sha256_path", counted)
    return calls


def test_presence_reads_do_not_hash_and_checks_hash_once(store, monkeypatch):
    calls = count_hashes(monkeypatch)
    [variant] = store.presence_for("A").variants
    assert variant["present"] is True and variant["intact"] is None
    assert store.annotation_for("A")["variants"] == [variant]
    assert calls == []
    assert store.scan(["A"]).drift == []
    assert len(calls) == 1
    # Explicit inspection still verifies the bytes.
    assert store.material_variants("A")[0]["intact"] is True


def test_unknown_variant_role_is_reported_not_raised(store, tmp_path):
    data = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    data["files"]["A"]["variants"][0]["role"] = "dataset"
    store.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    [variant] = store.presence_for("A").variants
    assert variant["present"] is False and "Invalid Pinax variant record" in variant["invalid"]
    [drift] = store.scan(["A"]).drift
    assert drift["kind"] == "variant" and "Invalid Pinax variant record" in drift["reason"]
    bib = store.bib_path
    bib.write_text(
        "@comment{pynakes-meta: pinax-files-dir:files;}\n" + bib.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["asset", "check", str(bib), "--json"])
    assert json.loads(result.output)["status"] != "error", result.output


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_lock_sweeps_exited_holders_and_refuses_live_ones(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    stale = state / f"lock-{dead_pid()}-1"
    stale.touch()
    with _transaction.locked(state):
        assert not stale.exists()
        assert len(list(state.glob("lock-*"))) == 1
    assert list(state.glob("lock-*")) == []
    # Another holder in a live process (here, this one) keeps the lock.
    live = state / f"lock-{os.getpid()}-0"
    live.touch()
    with pytest.raises(ValueError, match="Another ingestion operation is running"):
        with _transaction.locked(state):
            pass
    assert list(state.glob("lock-*")) == [live]


def test_modified_reflects_changes_not_the_ledger_output(manifest, tmp_path):  # noqa: F811
    source = make_pdf(tmp_path / "a.pdf", bib=BIB)
    first = Library.open(manifest).prepare_ingestion([source], mode="copy")
    assert first.modifies
    first.commit()
    repeat = Library.open(manifest).prepare_ingestion([source], mode="copy")
    repeat.commit()
    again = Library.open(manifest).prepare_ingestion([source], mode="copy")
    assert not again.modifies
    result = CliRunner().invoke(
        app, ["library", "ingest", str(manifest), str(source), "--mode", "copy", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["modified"] is False
