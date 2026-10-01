"""Tests for the shared replace-by-rename helpers in ``pynakes._atomic``."""

import os
from pathlib import Path

import pytest

from pynakes import _atomic
from pynakes.io import save_text


def _flaky_replace(failures: int):
    """Return an ``os.replace`` stand-in that is refused ``failures`` times."""
    calls = {"n": 0}
    real = os.replace

    def replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise PermissionError(13, "The process cannot access the file", str(dst))
        real(src, dst)

    return replace, calls


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Pretend to run on Windows and record the pauses instead of sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(_atomic.sys, "platform", "win32")
    monkeypatch.setattr(_atomic.time, "sleep", slept.append)
    return slept


def test_replace_file_retries_while_windows_holds_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: list[float]
) -> None:
    source, target = tmp_path / "new.bib", tmp_path / "library.bib"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    replace, calls = _flaky_replace(failures=2)
    monkeypatch.setattr(_atomic.os, "replace", replace)

    _atomic.replace_file(source, target)

    assert target.read_bytes() == b"new"
    assert not source.exists()
    assert calls["n"] == 3
    assert windows == list(_atomic._REPLACE_RETRY_DELAYS[:2])


def test_replace_file_gives_up_after_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: list[float]
) -> None:
    source, target = tmp_path / "new.bib", tmp_path / "library.bib"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    replace, calls = _flaky_replace(failures=100)
    monkeypatch.setattr(_atomic.os, "replace", replace)

    with pytest.raises(PermissionError):
        _atomic.replace_file(source, target)

    assert target.read_bytes() == b"old"
    assert calls["n"] == len(_atomic._REPLACE_RETRY_DELAYS) + 1
    assert windows == list(_atomic._REPLACE_RETRY_DELAYS)


def test_replace_file_does_not_retry_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "new.bib", tmp_path / "library.bib"
    source.write_bytes(b"new")
    replace, calls = _flaky_replace(failures=1)
    monkeypatch.setattr(_atomic.sys, "platform", "linux")
    monkeypatch.setattr(_atomic.os, "replace", replace)
    monkeypatch.setattr(_atomic.time, "sleep", lambda _: pytest.fail("slept off Windows"))

    with pytest.raises(PermissionError):
        _atomic.replace_file(source, target)

    assert calls["n"] == 1


def test_save_text_survives_a_briefly_locked_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: list[float]
) -> None:
    target = tmp_path / "library.bib"
    target.write_bytes(b"@misc{Old,}\n")
    replace, _ = _flaky_replace(failures=1)
    monkeypatch.setattr(_atomic.os, "replace", replace)

    result = save_text("@misc{New,}\n", str(target), backup=False)

    assert result.success, result.error
    assert target.read_bytes() == b"@misc{New,}\n"
    assert list(tmp_path.iterdir()) == [target]
