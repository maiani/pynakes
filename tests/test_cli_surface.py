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


def test_every_listed_deprecation_is_still_accepted() -> None:
    # A form in its deprecation period must keep working until its removal
    # release, so each one listed is still an option of its live command.
    capabilities = get_capabilities()
    for deprecation in capabilities["deprecations"]:
        schema = capabilities["command_schemas"][deprecation["command"]]
        flags = {flag for option in schema["options"] for flag in option["flags"]}
        # A whole command in its deprecation period names itself as the old form.
        assert deprecation["old"] in flags | {deprecation["command"]}, deprecation
        assert deprecation["new"] and deprecation["removal"], deprecation
        major, minor, _patch = (int(part) for part in deprecation["removal"].split("."))
        assert (major, minor) > (0, 7), deprecation


# --- operands that look like options -------------------------------------------


def _envelope(args: list[str]) -> dict:
    result = runner.invoke(app, args)
    assert "Traceback" not in result.output
    return json.loads(result.output)


def test_double_dash_passes_a_dash_led_group_name(bib: Path) -> None:
    added = _envelope(["groups", "add-group", str(bib), "--json", "--", "-x"])
    assert added["status"] == "success", added
    assert added["group"] == "-x"

    filed = _envelope(["groups", "add-entry", str(bib), "--json", "--", "Smith2020", "-x"])
    assert filed["status"] == "success", filed

    renamed = _envelope(
        ["groups", "rename-group", str(bib), "--members", "--json", "--", "-x", "-y"]
    )
    assert renamed["status"] == "success", renamed
    assert renamed["members_renamed"] == ["Smith2020"]


def test_double_dash_passes_a_dash_led_citation_key(bib: Path) -> None:
    added = _envelope(["ref", "add", str(bib), "--type", "misc", "--json", "--", "-k"])
    assert added["status"] == "success", added
    assert "@misc{-k," in bib.read_text(encoding="utf-8")

    renamed = _envelope(["keys", "rename", str(bib), "--json", "--", "-k", "-j"])
    assert renamed["status"] == "success", renamed

    removed = _envelope(["ref", "remove", str(bib), "--json", "--", "-j"])
    assert removed["status"] == "success", removed
    assert "{-j," not in bib.read_text(encoding="utf-8")


def test_double_dash_with_an_autodetected_library(bib: Path, monkeypatch) -> None:
    monkeypatch.chdir(bib.parent)

    added = _envelope(["groups", "add-group", "--json", "--", "-x"])

    assert added["status"] == "success", added
    assert added["file"] == "refs.bib"


def test_double_dash_passes_a_dash_led_search_query(bib: Path) -> None:
    found = _envelope(["search", str(bib), "--json", "--", "-nothing-matches"])
    assert found["status"] == "success", found


def test_json_is_compact_unless_pretty_is_asked_for(tmp_path) -> None:
    from typer.testing import CliRunner

    from pynakes.cli import app

    bib = tmp_path / "refs.bib"
    bib.write_text("@book{Newton1687, title = {Principia}}\n", encoding="utf-8")
    runner = CliRunner()

    compact = runner.invoke(app, ["ref", "show", str(bib), "Newton1687", "--json"]).output
    pretty = runner.invoke(
        app, ["ref", "show", str(bib), "Newton1687", "--json", "--pretty"]
    ).output
    after = runner.invoke(app, ["ref", "show", str(bib), "Newton1687", "--json"]).output

    assert compact.count("\n") == 1 and ": " not in compact.split('"fields"')[0]
    assert pretty.count("\n") > 1 and json.loads(pretty) == json.loads(compact)
    # The choice belongs to one invocation and never leaks into the next.
    assert after == compact


def test_help_is_plain_through_a_pipe_and_maps_jobs_to_commands() -> None:
    from typer.testing import CliRunner

    from pynakes.cli import app

    output = CliRunner().invoke(app, ["--help"]).output

    # No terminal: no padded Rich boxes, and the job map is there in one read.
    assert "╭" not in output and "│" not in output
    assert "Common jobs" in output and "ref show FILE --where EXPR" in output
    assert "[cyan]" not in output
