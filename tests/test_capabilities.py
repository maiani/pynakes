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


class TestCommandSchemas:
    def test_schemas_cover_full_command_surface(self) -> None:
        # Schemas are derived from the live CLI, so the top-level command/group
        # set they describe must equal the registered CLI surface.
        schemas = get_capabilities()["command_schemas"]
        top_level = {name.split(" ", 1)[0] for name in schemas}
        registered = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
        registered |= {group.name for group in app.registered_groups}
        assert top_level == registered

    def test_subcommands_are_expanded(self) -> None:
        schemas = get_capabilities()["command_schemas"]
        assert "groups add-entry" in schemas
        assert "keys rename" in schemas
        assert "metadata set" in schemas
        assert "journals" not in get_capabilities()["commands"]
        assert all(not name.startswith("journals ") for name in schemas)

    def test_schema_shape_for_a_command(self) -> None:
        split = get_capabilities()["command_schemas"]["split"]
        assert split["help"]
        # variadic positional input
        inputs = next(a for a in split["arguments"] if a["name"] == "inputs")
        assert inputs["type"] == "list[string]"
        assert inputs["variadic"] is True
        # the --to option carries its flag and type
        to_opt = next(o for o in split["options"] if o["name"] == "to")
        assert to_opt["flags"] == ["--to"]
        assert to_opt["type"] == "list[string]"
        # every option records its flags
        assert all(o["flags"] for o in split["options"])


class TestErrorCatalogAndGrammar:
    def test_error_codes_grouped_by_status_and_exit(self) -> None:
        codes = get_capabilities()["error_codes"]
        assert codes["error"]["exit_code"] == 1
        assert codes["conflict"]["exit_code"] == 2
        assert "FileNotFound" in codes["error"]["codes"]
        assert "DuplicateMergeKey" in codes["conflict"]["codes"]

    def test_predicate_grammar_is_present(self) -> None:
        grammar = get_capabilities()["predicate_grammar"]
        assert "contains" in grammar["field_operators"]
        assert "*" in grammar["split_predicates"]
        assert grammar["examples"]

    def test_search_query_grammar_is_present(self) -> None:
        grammar = get_capabilities()["search_query_grammar"]
        assert "field:term" in grammar["field_prefix"]
        assert grammar["examples"]


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
