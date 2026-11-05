"""Public imports and backend isolation survive the package reorganization."""

import importlib
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "modules",
    [
        ["pynakes.metadata.schema", "pynakes.keys", "pynakes.lint"],
        ["pynakes.pdf_import", "pynakes.engine", "pynakes.library", "pynakes.analysis"],
        ["pynakes.filestore", "pynakes.project_selection", "pynakes.zotero"],
        ["pynakes.fetch.progress", "pynakes.fetch", "pynakes.cli._common", "pynakes.cli"],
    ],
)
def test_public_imports_in_fresh_processes(modules):
    code = f"""
import importlib
for name in {modules!r}:
    importlib.import_module(name)
from pynakes import Bibliography
from pynakes.lint import lint
bib = Bibliography.from_text('@misc{{Example, title={{Example}}}}\\n')
assert lint(bib.lib) == []
assert bib.preview() == '@misc{{Example, title={{Example}}}}\\n'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_read_contracts_do_not_import_backend_implementations():
    code = """
import sys
from pynakes.library.backends import base
assert 'pynakes.library.backends.bibtex' not in sys.modules
assert 'pynakes.library.backends.zotero' not in sys.modules
from pynakes.library.backends.zotero import ZoteroLibraryBackend
assert 'pynakes.library.backends.bibtex' not in sys.modules
from pynakes import library_backend, zotero
from pynakes.library.backends.bibtex import BibTeXLibraryBackend
assert library_backend.BibTeXLibraryBackend is BibTeXLibraryBackend
assert zotero.ZoteroLibraryBackend is ZoteroLibraryBackend
for name in library_backend.__all__:
    if name != 'BibTeXLibraryBackend':
        assert getattr(library_backend, name) is getattr(base, name)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_lint_exports_remain_discoverable():
    public = importlib.import_module("pynakes.lint")
    checks = importlib.import_module("pynakes.lint._checks")
    assert public.__all__ == checks.__all__
    assert set(public.__all__) <= set(dir(public))
    for name in public.__all__:
        assert getattr(public, name) is getattr(checks, name)
    with pytest.raises(AttributeError):
        getattr(public, "unknown_lint_operation")


def test_cli_infrastructure_does_not_assemble_the_application():
    code = """
import sys
from pynakes.cli import _errors, _files, _schema
assert 'pynakes.cli._app' not in sys.modules
assert 'pynakes.cli.commands.fetch' not in sys.modules
from pynakes.cli import app
from typer.testing import CliRunner
result = CliRunner().invoke(app, ['--version'])
assert result.exit_code == 0, result.output
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fetch_progress_compatibility_exports():
    from pynakes import fetch_progress
    from pynakes.fetch import progress

    for name in fetch_progress.__all__:
        assert getattr(fetch_progress, name) is getattr(progress, name)


def test_version_lookup_is_shared_and_lazy(monkeypatch):
    from importlib import metadata

    from pynakes import _version
    from pynakes.providers._http import user_agent

    _version.package_version.cache_clear()
    seen = []

    def version(name):
        seen.append(name)
        return "1.2.3"

    monkeypatch.setattr(metadata, "version", version)
    try:
        assert _version.package_version() == "1.2.3"
        assert user_agent().startswith("pynakes/1.2.3 ")
        assert seen == ["pynakes"]
        _version.package_version.cache_clear()

        def missing(name):
            raise metadata.PackageNotFoundError(name)

        monkeypatch.setattr(metadata, "version", missing)
        assert _version.package_version() == "0.0.0+unknown"
    finally:
        _version.package_version.cache_clear()
