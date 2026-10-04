"""The ``--expect-sha256`` write precondition and the ``source_sha256`` it pairs with.

A client previews a change, shows it, waits for approval, then applies it. The
preview reports the digest of the file it read; passing that digest back on the
write makes the engine refuse — exit 2, nothing written — when the file moved in
between, instead of applying the change over an edit made while the approval
was pending.
"""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.capabilities import _ERROR_CODES, get_capabilities
from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()

LIBRARY = (
    "@book{Newton1687,\n"
    "  author = {Isaac Newton},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687},\n"
    "  groups = {Mechanics}\n"
    "}\n"
    "\n"
    "@book{Euler1748,\n"
    "  author = {Leonhard Euler},\n"
    "  title = {Introductio in analysin infinitorum},\n"
    "  year = {1748}\n"
    "}\n"
    "\n"
    "@book{Euler1748b,\n"
    "  author = {Leonhard Euler},\n"
    "  title = {Introductio in analysin infinitorum},\n"
    "  year = {1748}\n"
    "}\n"
)

STALE = "0" * 64

# One invocation per command that accepts the precondition; ``{bib}`` is the library.
WRITES = {
    "ref edit": ["ref", "edit", "Newton1687", "{bib}", "--field", "note=first edition"],
    "ref add": ["ref", "add", "Galileo1638", "{bib}", "--type", "book", "--field", "year=1638"],
    "ref remove": ["ref", "remove", "{bib}", "Euler1748b", "--keep-files"],
    "groups add-entry": ["groups", "add-entry", "{bib}", "Euler1748", "Analysis"],
    "groups remove-entry": ["groups", "remove-entry", "{bib}", "Newton1687", "Mechanics"],
    "dedupe merge": ["dedupe", "merge", "{bib}", "--key", "Euler1748"],
    "corpus batch": [
        "corpus",
        "batch",
        "{bib}",
        "--ops",
        '[{"op": "ref.edit", "key": "Newton1687", "fields": {"note": "first edition"}}]',
    ],
}


def _library(tmp_path: Path) -> Path:
    bib = tmp_path / "lib.bib"
    bib.write_bytes(LIBRARY.encode("utf-8"))
    return bib


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _invoke(args: list[str], bib: Path, *extra: str):
    argv = [part.replace("{bib}", str(bib)) for part in args]
    return runner.invoke(app, [*argv, *extra, "--json"])


def _payload(result) -> dict:
    assert "Traceback" not in result.output
    return json.loads(result.output)


@pytest.mark.parametrize("command", sorted(WRITES))
def test_modifying_envelope_reports_the_digest_of_the_file_it_read(
    tmp_path: Path, command: str
) -> None:
    bib = _library(tmp_path)
    before = _digest(bib)

    preview = _invoke(WRITES[command], bib, "--dry-run")
    assert preview.exit_code == 0, preview.output
    assert _payload(preview)["source_sha256"] == before

    # A real write reports the state it read, not the state it wrote.
    applied = _invoke(WRITES[command], bib)
    assert applied.exit_code == 0, applied.output
    assert _payload(applied)["source_sha256"] == before
    assert _digest(bib) != before


@pytest.mark.parametrize("command", sorted(WRITES))
def test_matching_precondition_applies(tmp_path: Path, command: str) -> None:
    bib = _library(tmp_path)
    previewed = _payload(_invoke(WRITES[command], bib, "--dry-run"))["source_sha256"]

    result = _invoke(WRITES[command], bib, "--expect-sha256", previewed)

    assert result.exit_code == 0, result.output
    assert _payload(result)["modified"] is True


@pytest.mark.parametrize("command", sorted(WRITES))
def test_stale_precondition_is_a_conflict_and_writes_nothing(tmp_path: Path, command: str) -> None:
    bib = _library(tmp_path)
    previewed = _payload(_invoke(WRITES[command], bib, "--dry-run"))["source_sha256"]
    # Someone edits the file while the approval dialog is open.
    bib.write_bytes(bib.read_bytes() + b"\n@misc{Leibniz1684, year = {1684}}\n")
    moved = bib.read_bytes()

    result = _invoke(WRITES[command], bib, "--expect-sha256", previewed)

    assert result.exit_code == 2, result.output
    payload = _payload(result)
    assert payload["status"] == "conflict"
    assert payload["error"] == "ExternalModification"
    assert payload["expected_sha256"] == previewed
    assert payload["source_sha256"] == hashlib.sha256(moved).hexdigest()
    assert {option["id"] for option in payload["options"]} == {"reload", "manual_review"}
    assert bib.read_bytes() == moved


def test_stale_precondition_is_refused_on_a_dry_run_too(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    result = _invoke(WRITES["ref edit"], bib, "--dry-run", "--expect-sha256", STALE)
    assert result.exit_code == 2
    assert _payload(result)["error"] == "ExternalModification"


def test_precondition_digest_is_case_insensitive(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    result = _invoke(WRITES["ref edit"], bib, "--expect-sha256", _digest(bib).upper())
    assert result.exit_code == 0, result.output
    assert "note = {first edition}" in bib.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["", "abc", "z" * 64, "0" * 63])
def test_malformed_precondition_is_invalid_input(tmp_path: Path, value: str) -> None:
    bib = _library(tmp_path)
    result = _invoke(WRITES["ref edit"], bib, "--expect-sha256", value)
    assert result.exit_code == 1
    assert _payload(result)["error"] == "InvalidInput"
    assert bib.read_text(encoding="utf-8") == LIBRARY


def test_batch_checks_the_precondition_before_running_operations(tmp_path: Path) -> None:
    # Against a file that moved, an operation can fail for a reason that is
    # only a symptom; the precondition is reported instead.
    bib = _library(tmp_path)
    ops = '[{"op": "ref.edit", "key": "Missing1900", "fields": {"note": "x"}}]'
    result = runner.invoke(
        app, ["corpus", "batch", str(bib), "--ops", ops, "--expect-sha256", STALE, "--json"]
    )
    assert result.exit_code == 2
    assert _payload(result)["error"] == "ExternalModification"


def test_import_checks_the_precondition_before_asking_a_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*args, **kwargs):
        raise AssertionError("a stale precondition must not cost a provider lookup")

    monkeypatch.setattr(Bibliography, "import_reference", unreachable)
    bib = _library(tmp_path)
    result = runner.invoke(
        app,
        [
            "ref",
            "import",
            "10.1000/example",
            "--file",
            str(bib),
            "--expect-sha256",
            STALE,
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert _payload(result)["error"] == "ExternalModification"


def test_source_fingerprint_describes_the_bytes_read_and_follows_a_commit(
    tmp_path: Path,
) -> None:
    bib = _library(tmp_path)
    coll = Bibliography.open(bib)
    assert coll.source_fingerprint is not None
    assert coll.source_fingerprint.sha256 == _digest(bib)

    coll.edit_entry("Newton1687", fields={"note": "first edition"})
    coll.commit()
    assert coll.source_fingerprint is not None
    assert coll.source_fingerprint.sha256 == _digest(bib)


def test_unbound_bibliography_has_no_source_fingerprint() -> None:
    assert Bibliography.from_text(LIBRARY).source_fingerprint is None


def test_capabilities_list_exactly_the_commands_that_accept_the_precondition() -> None:
    described = get_capabilities()["write_precondition"]
    assert described["option"] == "--expect-sha256"
    assert described["envelope_key"] == "source_sha256"
    assert described["conflict"] in _ERROR_CODES["conflict"]["codes"]
    assert set(described["commands"]) == set(WRITES) | {"ref import"}
