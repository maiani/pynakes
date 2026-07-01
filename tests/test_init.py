"""Tests for ``pynakes init`` and the underlying scaffolding operations."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.initialize import apply_overrides, collect_profile, render_library
from pynakes.io import load_bib
from pynakes.model import BibFile

runner = CliRunner()

TEMPLATE = (
    "@comment{jabref-meta: databaseType:biblatex;}\n\n"
    "@comment{jabref-meta: keypatterndefault:[auth][year];}\n\n"
    "@comment{jabref-meta: groupstree:0 AllEntriesGroup:;}\n\n"
    "@comment{pynakes-meta:\n"
    "normalize-author-style: jabref\n"
    "tex-sources: paper.tex\n"
    "}\n"
)


# --- operation-level unit tests --------------------------------------------


def test_render_library_canonical_layout() -> None:
    entries = apply_overrides(
        [],
        [("keypatterndefault", "[auth][year]", "jabref"), ("databaseType", "biblatex", "jabref")],
    )
    text = render_library(entries)
    # jabref-meta comments, sorted by key (databaseType before keypatterndefault).
    assert text.index("databaseType") < text.index("keypatterndefault")
    lib = load_bib_from_text(text)
    assert lib.metadata["databaseType"].rstrip(";") == "biblatex"
    assert lib.metadata["keypatterndefault"].rstrip(";") == "[auth][year]"


def test_render_library_empty_when_no_profile() -> None:
    assert render_library([]) == ""


def test_apply_overrides_replaces_existing_key() -> None:
    base = apply_overrides([], [("databaseType", "bibtex", "jabref")])
    overridden = apply_overrides(base, [("databaseType", "biblatex", "jabref")])
    assert len(overridden) == 1
    assert overridden[0].value == "biblatex"


def test_collect_profile_keeps_conventions_drops_content(tmp_path: Path) -> None:
    template = tmp_path / "template.bib"
    template.write_text(TEMPLATE)
    profile = collect_profile(load_bib(str(template)))
    keys = {entry.key.lower() for entry in profile}
    assert "databasetype" in keys
    assert "keypatterndefault" in keys
    assert "normalize-author-style" in keys
    # Library-specific content is not part of a reusable profile.
    assert "groupstree" not in keys
    assert "tex-sources" not in keys


# --- CLI tests -------------------------------------------------------------


def test_init_creates_typed_library(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--type", "biblatex", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "init"
    assert data["created"] is True
    assert data["type"] == "biblatex"
    assert out.exists()
    lib = load_bib(str(out))
    # A fresh library is pynakes-native: the dialect lands in the native key,
    # not JabRef's databaseType.
    assert lib.metadata["dialect"] == "biblatex"
    assert "databaseType" not in lib.metadata
    # --type composes with the rest of the default profile.
    assert "key-pattern" in lib.metadata


def test_init_type_overrides_default(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--type", "bibtex", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["type"] == "bibtex"
    assert load_bib(str(out)).metadata["dialect"] == "bibtex"


def test_init_bare_seeds_default_profile(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["type"] == "biblatex"
    # A bare init is useful, not empty: it carries the pynakes-native profile
    # and no jabref-meta.
    keys = {key.lower() for key in data["keys"]}
    assert {"dialect", "key-pattern"} == keys
    lib = load_bib(str(out))
    assert len(lib.entries) == 0
    assert lib.jabref_metadata_blocks == []
    assert lib.metadata["dialect"] == "biblatex"
    assert lib.metadata["key-pattern"] == "[auth][year][veryshorttitle]"


def test_init_jabref_projects_native_keys(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--jabref", "--json"])
    assert result.exit_code == 0, result.output
    lib = load_bib(str(out))
    # Native keys remain authoritative...
    assert lib.metadata["dialect"] == "biblatex"
    assert lib.metadata["key-pattern"] == "[auth][year][veryshorttitle]"
    # ...and the JabRef projection is emitted so the file opens JabRef-tracked.
    assert lib.jabref_metadata_blocks != []
    assert lib.metadata["databaseType"].rstrip(";") == "biblatex"
    assert lib.metadata["keypatterndefault"].rstrip(";") == "[auth][year][veryshorttitle]"


def test_init_refuses_existing_without_force(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    out.write_text("@article{Keep2020,\n  title = {Keep}\n}\n")
    result = runner.invoke(app, ["init", str(out), "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "FileExists"
    # The existing file is untouched.
    assert "Keep2020" in out.read_text()


def test_init_force_overwrites_and_backs_up_when_requested(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    out.write_text("@article{Old2020,\n  title = {Old}\n}\n")
    result = runner.invoke(app, ["init", str(out), "--type", "bibtex", "--force", "--backup"])
    assert result.exit_code == 0, result.output
    assert "Old2020" not in out.read_text()
    assert (tmp_path / "refs.bib.bak").read_text().strip().startswith("@article{Old2020")


def test_init_from_copies_profile_not_content(tmp_path: Path) -> None:
    template = tmp_path / "template.bib"
    template.write_text(TEMPLATE)
    out = tmp_path / "new.bib"
    result = runner.invoke(app, ["init", str(out), "--from", str(template), "--json"])
    assert result.exit_code == 0, result.output
    keys = {key.lower() for key in json.loads(result.output)["keys"]}
    assert {"databasetype", "keypatterndefault", "normalize-author-style"} <= keys
    assert "groupstree" not in keys and "tex-sources" not in keys
    meta = load_bib(str(out)).metadata
    assert meta["databaseType"].rstrip(";") == "biblatex"
    assert "groupstree" not in meta


def test_init_dry_run_diff_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(
        app, ["init", str(out), "--type", "biblatex", "--dry-run", "--diff", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["created"] is False
    assert "dialect" in data["diff"]
    assert not out.exists()


def test_init_rejects_bad_type(tmp_path: Path) -> None:
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--type", "endnote", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "InvalidInput"
    assert not out.exists()


def test_init_pinax_creates_files_dir_beside_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    out = project / "refs.bib"
    result = runner.invoke(app, ["init", str(out), "--pinax", "--json"])
    assert result.exit_code == 0, result.output
    assert (project / "refs.files").is_dir()
    assert not (tmp_path / "refs.files").exists()
    assert load_bib(str(out)).metadata["files-dir"].strip() == "refs.files"


# --- helpers ---------------------------------------------------------------


def load_bib_from_text(text: str) -> BibFile:
    from pynakes.bibtex_parser import parse_bib

    return parse_bib(text)
