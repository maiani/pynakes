"""Headless creation shares the interactive engine's key rules and write guards."""

import json

from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography


def test_generated_add_api_and_headless_preview(tmp_path):
    source = "@comment{pynakes-meta: key-pattern:[auth:lower][year];}\n"
    fields = {"author": "Newton, Isaac", "year": "1687", "title": "Principia"}
    coll = Bibliography.from_text(source)
    assert coll.add_entry("book", None, fields).key == "newton1687"
    assert coll.add_entry("book", None, fields).key == "newton1687a"
    bib = tmp_path / "refs.bib"
    bib.write_text(source)
    args = ["ref", "add", str(bib), "--no-interactive", "--type", "book", "--json"]
    for name, value in fields.items():
        args.extend(["--field", f"{name}={value}"])
    runner = CliRunner()
    preview = runner.invoke(app, [*args, "--dry-run", "--diff"])
    assert preview.exit_code == 0, preview.output
    report = json.loads(preview.output)
    assert report["key"] == "newton1687"
    assert "newton1687" in report["diff"]
    assert bib.read_text() == source
    applied = runner.invoke(app, [*args, "--expect-sha256", report["source_sha256"]])
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["key"] == report["key"]
    stale = runner.invoke(app, [*args, "--expect-sha256", report["source_sha256"]])
    assert stale.exit_code == 2, stale.output
    assert len(Bibliography.open(bib).lib.entries) == 1
