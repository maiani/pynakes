"""A duplicate-key conflict carries what the caller is choosing between."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

LIBRARY = (
    "@book{Hooke1665, title = {Micrographia}, year = {1665}}\n\n"
    "@book{Newton1687, title = {Principia}, year = {1687}}\n\n"
    "@book{Hooke1665, title = {Micrographia, second issue}, year = {1667}}\n"
)


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.output)


def test_conflict_lists_each_candidate_with_a_selector_for_it(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")

    code, conflict = _json("ref", "edit", str(bib), "Hooke1665", "--field", "note=x")

    assert code == 2 and conflict["error"] == "DuplicateCitationKey"
    assert conflict["options"][0]["id"] == "ask_which"
    first, second = conflict["candidates"]
    assert (first["index"], second["index"]) == (0, 2)
    assert first["differs"] == ["title", "year"] and second["fields"]["year"] == "1667"
    # Each selector reaches its own entry and nothing else.
    _code, chosen = _json("fields", "set", str(bib), "note", "x", "--where", second["where"])
    assert chosen["modified_entries"] == 1
    text = bib.read_text(encoding="utf-8")
    assert text.count("note = {x}") == 1 and text.index("note") > text.index("second issue")


def test_multi_key_reads_report_candidates_per_key(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")

    code, conflict = _json("ref", "show", str(bib), "--key", "Hooke1665,Newton1687")

    assert code == 2 and list(conflict["candidates"]) == ["Hooke1665"]
    assert len(conflict["candidates"]["Hooke1665"]) == 2


def test_entries_differing_only_in_type_get_no_invented_selector(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@book{Euler1748, title = {I}}\n\n@misc{Euler1748, title = {I}}\n", encoding="utf-8"
    )

    _code, conflict = _json("ref", "show", str(bib), "Euler1748")

    assert [candidate["where"] for candidate in conflict["candidates"]] == [None, None]
    assert [candidate["type"] for candidate in conflict["candidates"]] == ["book", "misc"]
