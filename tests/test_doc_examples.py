"""Execute the documented offline CLI walkthroughs, with no network available."""

from __future__ import annotations

import re
import shlex
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes._cli_reference import render_command_reference
from pynakes.capabilities import command_schemas
from pynakes.cli import app

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ["README.md", "docs/guides/quickstart.md", "docs/guides/usage.md"]


@pytest.mark.parametrize("document", DOCUMENTS)
def test_offline_shell_examples(document: str, tmp_path: Path, monkeypatch) -> None:
    """Run every bash fence, in document order, in a new empty directory.

    These examples use simple command invocations, not shell scripting. Parse
    POSIX quoting and continuations, then run the real Click application. This
    exercises exactly the same operands on Windows without requiring bash.
    Package installation, online acquisition and terminal setup use sh fences.
    """
    text = (ROOT / document).read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def refuse_network(*args, **kwargs):
        pytest.fail("An offline documentation example attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    runner = CliRunner()
    count = 0
    for filename, content in re.findall(r'```csv title="([\w.-]+)"\n(.*?)```', text, re.S):
        (tmp_path / filename).write_text(content, encoding="utf-8")
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            args = shlex.split(line, comments=True)
            if not args:
                continue
            assert args[0] == "pynakes", f"Undeclared shell setup in {document}: {line}"
            assert not {"|", ">", "&&", ";"}.intersection(args), line
            result = runner.invoke(app, args[1:])
            assert result.exit_code == 0, f"{document}: {line}\n{result.output}"
            count += 1
    assert count > 0, f"No offline examples tested in {document}"
    library = tmp_path / ("mylib.bib" if document == "README.md" else "refs.bib")
    assert library.exists()
    assert "Newton1687" in library.read_text(encoding="utf-8") or document == "README.md"


def test_generated_command_reference_is_current() -> None:
    expected = render_command_reference()
    actual = (ROOT / "docs/guides/command-reference.md").read_text(encoding="utf-8")
    assert actual == expected, "Run mkdocs build --strict to regenerate the command reference"
    for name, schema in command_schemas().items():
        assert f"## {name}\n" in actual
        assert schema["stability"] in {"stable", "experimental"}
        for option in schema["options"]:
            for flag in option["flags"]:
                assert flag in actual


def test_current_engine_docs_do_not_claim_alpha_status() -> None:
    paths = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\balpha\b", line, re.I):
                # The engine is Beta; the independently versioned editor Alpha
                # is explicitly part of the coordinated release.
                assert re.search(r"\beditor\b|\bVS Code\b", line, re.I), f"{path}: {line}"


def test_terminal_help_has_no_literal_rst_quotes() -> None:
    import typer.main

    def check(group) -> None:
        for command in group.commands.values():
            assert "``" not in (command.help or "")
            for param in command.params:
                assert "``" not in (getattr(param, "help", "") or "")
            if hasattr(command, "commands"):
                check(command)

    check(typer.main.get_command(app))
