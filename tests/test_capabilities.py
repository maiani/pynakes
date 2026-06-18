"""Tests for the machine-readable capability description."""

import json

from typer.testing import CliRunner

from pynakes.capabilities import VERSION, get_capabilities
from pynakes.cli import app

runner = CliRunner()


class TestGetCapabilities:
    def test_top_level_structure(self) -> None:
        caps = get_capabilities()
        assert caps["tool"] == "pynakes"
        assert caps["version"] == VERSION
        assert caps["safe_by_default"] is True
        assert caps["supports_dry_run"] is True
        assert caps["supports_json_output"] is True
        assert isinstance(caps["capabilities"], list)
        assert isinstance(caps["commands"], dict)

    def test_exit_codes_documented(self) -> None:
        codes = get_capabilities()["exit_codes"]
        assert set(codes) == {"0", "1", "2"}
        assert "conflict" in codes["2"].lower()

    def test_is_json_serializable(self) -> None:
        # Agents consume this over stdout; it must round-trip through JSON.
        caps = get_capabilities()
        assert json.loads(json.dumps(caps)) == caps

    def test_commands_match_registered_cli_commands(self) -> None:
        # The declared command list must not drift from the actual CLI surface.
        declared = set(get_capabilities()["commands"])
        registered = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
        registered |= {group.name for group in app.registered_groups}
        assert declared == registered


class TestCapabilitiesCommand:
    def test_json_output_is_valid(self) -> None:
        result = runner.invoke(app, ["capabilities", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == get_capabilities()

    def test_human_output_lists_commands(self) -> None:
        result = runner.invoke(app, ["capabilities"])
        assert result.exit_code == 0, result.output
        assert "pynakes v" in result.output
        for name in get_capabilities()["commands"]:
            assert name in result.output
