"""Shared fixtures for the pynakes test suite."""

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a ``CliRunner`` for CLI integration tests."""
    return CliRunner()


@pytest.fixture
def copy_fixture(fixtures_dir: Path) -> Callable[[str, Path], Path]:
    """Return a helper that copies a named fixture to *tmp_path*."""

    def _copy(name: str, dest_dir: Path) -> Path:
        src = fixtures_dir / name
        dest = dest_dir / name
        dest.write_bytes(src.read_bytes())
        return dest

    return _copy
