"""The shared ``--key`` / ``--where`` entry selector, across the commands that edit entries.

A selector written for one command must work on every other, so a lookup for a
handful of references never has to fall back to running over the whole library
or to editing it by hand.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes._engine_fetch import build_fetch_queue
from pynakes.bibtex_parser import parse_bib
from pynakes.capabilities import get_capabilities
from pynakes.cli import app

runner = CliRunner()

#: Modifying commands without the full selector, and why they cannot take one.
NOT_ENTRY_SELECTABLE = {
    "asset repair": "reconciles the manifest, never an entry",
    "convert": "a dialect belongs to the whole file",
    "corpus batch": "each operation names its own entries",
    "corpus split": "routes entries with its own --route predicates",
    "dedupe merge": "--key picks clusters; a predicate over clusters is not defined",
    "groups add-entry": "names one entry positionally",
    "groups add-group": "edits the group tree, not entries",
    "groups move-group": "edits the group tree, not entries",
    "groups remove-entry": "names one entry positionally",
    "groups remove-group": "edits the group tree, not entries",
    "groups rename-group": "renames one group; --members follows it into every entry",
    "groups update-group": "edits the group tree, not entries",
    "init": "creates a library",
    "keys rename": "names one entry positionally",
    "keys repair": "key uniqueness is a property of the whole file",
    "metadata adopt-jabref": "edits file metadata, not entries",
    "metadata remove": "edits file metadata, not entries",
    "metadata set": "edits file metadata, not entries",
    "ref add": "creates one entry",
    "ref edit": "names one entry positionally",
    "ref import": "--key names the key to assign to the new entry",
    "ref remove": "names its entries positionally",
    "scrub": "produces a public copy of the whole library",
    "tex add": "edits the TeX source list, not entries",
    "tex clear": "edits the TeX source list, not entries",
    "tex remove": "edits the TeX source list, not entries",
    "tex scan": "tags entries from what the TeX sources cite",
}

LIBRARY = (
    "@comment{pynakes-meta: normalize-journal-style: abbreviated}\n"
    "@comment{jabref-meta: saveOrderConfig:specified;year;false;}\n"
    "\n"
    "@article{Einstein1905,\n"
    "  author = {Albert Einstein},\n"
    '  title = {Zur Elektrodynamik bewegter K{\\"o}rper},\n'
    "  journal = {Annalen der Physik},\n"
    "  url = {https://doi.org/10.1000/elektrodynamik},\n"
    "  year = {1905},\n"
    "}\n"
    "\n"
    "@article{Planck1900,\n"
    "  author = {Max Planck},\n"
    "  title = {Zur Theorie des Gesetzes der Energieverteilung},\n"
    "  journal = {Annalen der Physik},\n"
    "  url = {https://doi.org/10.1000/energieverteilung},\n"
    "  year = {1900},\n"
    "}\n"
)


def _library(tmp_path: Path) -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY)
    return bib


def _run(*args: str) -> dict:
    result = runner.invoke(app, [*args, "--json"])
    return {"exit": result.exit_code, **json.loads(result.output)}


def test_every_entry_editing_command_takes_key_and_where() -> None:
    schemas = get_capabilities()["command_schemas"]
    lacking = []
    for name, schema in schemas.items():
        flags = {flag for option in schema["options"] for flag in option["flags"]}
        if "--dry-run" in flags and not {"--key", "--where"} <= flags:
            lacking.append(name)
    assert sorted(lacking) == sorted(NOT_ENTRY_SELECTABLE)


def test_enrich_acts_on_the_selected_entries_only(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    data = _run("enrich", str(bib), "--key", "Planck1900", "--dry-run")
    assert data["exit"] == 0
    assert data["selected"] == 1
    assert {update["key"] for update in data["updates"]} == {"Planck1900"}

    by_year = _run("enrich", str(bib), "--where", "year < 1901", "--dry-run")
    assert {update["key"] for update in by_year["updates"]} == {"Planck1900"}


def test_an_unknown_key_is_an_error_and_an_empty_selection_a_warning(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    missing = _run("enrich", str(bib), "--key", "Newton1687", "--dry-run")
    assert (missing["exit"], missing["error"]) == (1, "KeyNotFound")

    empty = _run("enrich", str(bib), "--where", "year > 2000", "--dry-run")
    assert empty["selected"] == 0
    assert [warning["type"] for warning in empty["warnings"]] == ["no_entries_selected"]
    assert empty["modified"] is False


def test_normalize_one_step_on_one_entry_changes_only_that(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    data = _run(
        "normalize", str(bib), "--key", "Einstein1905", "--only", "journals", "--dry-run", "--diff"
    )
    assert data["exit"] == 0
    changed = [
        line
        for line in data["diff"].splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    assert changed == ["-  journal = {Annalen der Physik},", "+  journal = {Ann. Phys.},"]
    assert data["operations"]["skipped"]["sort"] == "not selected by --only"


def test_a_normalize_selection_never_sorts_the_file(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    data = _run("normalize", str(bib), "--where", "year = 1905", "--dry-run")
    assert data["exit"] == 0
    assert data["operations"]["sorted_entries"] == 0
    assert "whole file" in data["operations"]["skipped"]["sort"]


def test_normalize_refuses_flags_for_steps_that_cannot_run(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    sorting = _run("normalize", str(bib), "--key", "Einstein1905", "--sort-by", "year")
    assert sorting["error"] == "InvalidInput" and "--sort-by" in sorting["message"]

    excluded = _run("normalize", str(bib), "--only", "journals", "--author-style", "biblatex")
    assert excluded["error"] == "InvalidInput" and "--author-style" in excluded["message"]

    unknown = _run("normalize", str(bib), "--only", "spelling")
    assert unknown["error"] == "InvalidInput" and "spelling" in unknown["message"]


def test_keys_generate_regenerates_the_selection(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    data = _run("keys", "generate", str(bib), "--where", "year = 1900", "--dry-run")
    assert data["exit"] == 0
    assert [rename["old"] for rename in data["renames"]] == ["Planck1900"]

    both = _run("keys", "generate", str(bib), "Planck1900", "--key", "Planck1900")
    assert both["error"] == "InvalidInput"


def test_the_fetch_queue_follows_the_selection() -> None:
    lib = parse_bib(LIBRARY)
    assert [entry.key for entry in build_fetch_queue(lib, None, {"Planck1900"})] == ["Planck1900"]
