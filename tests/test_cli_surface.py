"""The library-first convention, and the pre-0.7 forms it replaced failing cleanly.

0.7.0 removed the renamed and reordered forms outright rather than aliasing
them, so each must fail as a ``UsageError`` (exit 1) instead of running with a
different meaning.
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.capabilities import get_capabilities
from pynakes.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bib(tmp_path: Path) -> Path:
    target = tmp_path / "refs.bib"
    shutil.copy(FIXTURES / "simple.bib", target)
    return target


def _usage_error(args: list[str]) -> str:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["error"] == "UsageError"
    return payload["message"]


@pytest.mark.parametrize(
    ("command", "operands"),
    [
        (["ref", "show"], ["Smith2020"]),
        (["ref", "edit"], ["Smith2020"]),
        (["ref", "compare"], ["Smith2020"]),
        (["ref", "add"], ["Newton1687"]),
        (["ref", "import"], ["10.5555/example"]),
        (["search"], ["widgets"]),
        (["asset", "fetch"], ["Smith2020"]),
        (["keys", "generate"], ["Smith2020"]),
        (["tex", "add"], ["paper.tex"]),
        (["tex", "remove"], ["paper.tex"]),
    ],
)
def test_operand_first_order_is_a_usage_error(
    bib: Path, command: list[str], operands: list[str]
) -> None:
    message = _usage_error([*command, *operands, str(bib)])

    assert "looks like a library" in message
    assert f"pynakes {' '.join(command)} FILE" in message
    assert bib.read_bytes() == (FIXTURES / "simple.bib").read_bytes()


def test_library_named_twice_with_file_is_a_usage_error(bib: Path) -> None:
    message = _usage_error(["ref", "show", "Smith2020", "--file", str(bib), "-f", str(bib)])

    assert "more than once" in message


def test_file_option_with_a_library_in_the_operand_slot_is_a_usage_error(bib: Path) -> None:
    message = _usage_error(["ref", "show", "--file", str(bib), str(bib)])

    assert "looks like a library" in message


def test_short_file_flag_names_the_library_on_ref_add(bib: Path) -> None:
    # `-f` set a field before 0.7; it now names the library, as on every command.
    result = runner.invoke(
        app, ["ref", "add", "Newton1687", "-f", str(bib), "--field", "title=Principia", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert "Newton1687" in bib.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "args",
    [
        ["ref", "show", "{bib}", "--keys", "Smith2020"],
        ["search", "{bib}", "widgets", "--show-abstract"],
        ["search", "{bib}", "widgets", "--field", "title"],
        ["scrub", "{bib}", "--out", "{out}", "--keep-fields"],
        ["normalize", "{bib}", "--keys", "on"],
        ["normalize", "{bib}", "--title-protection", "true"],
        ["init", "{out}", "--type", "bibtex"],
        ["corpus", "split", "{bib}", "--to", "{out}=*"],
        ["format", "{bib}", "--stdout"],
        ["keys", "usage", "Smith2020", "--path", "paper.tex"],
        ["asset", "fetch", "{bib}", "--preprint"],
        ["asset", "check", "{bib}", "--fix"],
        ["groups", "add-group", "{bib}", "Optics", "--context", "1"],
        ["lint", "{bib}", "--category", "layout"],
    ],
)
def test_removed_spelling_is_a_usage_error(bib: Path, tmp_path: Path, args: list[str]) -> None:
    paths = {"bib": str(bib), "out": str(tmp_path / "out.bib")}

    _usage_error([part.format(**paths) for part in args])

    assert not (tmp_path / "out.bib").exists()


def test_capabilities_lists_no_deprecated_forms() -> None:
    assert "deprecations" not in get_capabilities()
