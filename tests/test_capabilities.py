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
        assert caps["network_access_is_explicit"] is True
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

    def test_formatting_policies_and_defaults_are_explicit(self) -> None:
        formatting = get_capabilities()["formatting"]
        assert formatting["defaults"]["field_order"] == "preferred"
        assert formatting["defaults"]["block_order"] == "canonical"
        assert formatting["choices"]["wrap_values"] == ["off", "stable", "canonical"]
        assert "repeated fields" in formatting["lint_gate"]
        assert "format_bibliography" in get_capabilities()["capabilities"]

    def test_python_api_facade_is_machine_readable(self) -> None:
        api = get_capabilities()["python_api"]
        assert api["facade"] == "pynakes.Bibliography"
        assert api["transport_independent"] is True
        assert "Bibliography" in api["public_exports"]
        assert "change_plan" in api["review"]
        assert "commit" in api["persistence"]

    def test_work_matching_contract_is_explicit(self) -> None:
        matching = get_capabilities()["work_matching"]
        assert matching["statuses"] == ["exact", "probable", "conflict", "unknown"]
        assert matching["relationships_are_separate"] is True
        assert matching["non_work_identity"] == ["orcid"]
        assert "compare_work_evidence" in get_capabilities()["capabilities"]

    def test_commands_match_registered_cli_commands(self) -> None:
        # The declared command list must not drift from the actual CLI surface.
        declared = set(get_capabilities()["commands"])
        registered = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
        registered |= {group.name for group in app.registered_groups}
        assert declared == registered

    def test_command_groups_partition_every_command(self) -> None:
        # The by-nature grouping (shared with the --help panels) must cover every
        # command exactly once — no command unassigned, none in two panels, none
        # naming a command that does not exist.
        from pynakes.capabilities import COMMAND_GROUPS

        grouped = [name for names in COMMAND_GROUPS.values() for name in names]
        assert len(grouped) == len(set(grouped)), "a command appears in two panels"
        assert set(grouped) == set(get_capabilities()["commands"])

    def test_help_panels_follow_command_groups(self) -> None:
        # Every top-level command/group is assigned to its taxonomy panel.
        from pynakes.capabilities import COMMAND_GROUPS

        panel_by_command = {
            name: panel for panel, names in COMMAND_GROUPS.items() for name in names
        }
        for cmd in app.registered_commands:
            name = cmd.name or cmd.callback.__name__
            assert cmd.rich_help_panel == panel_by_command[name]
        for group in app.registered_groups:
            assert group.rich_help_panel == panel_by_command[group.name]


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
        split = get_capabilities()["command_schemas"]["corpus split"]
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
        assert "in [a, b]" in grammar["field_operators"]
        assert "*" in grammar["bucket_predicates"]
        assert "and" in grammar["boolean"]
        assert grammar["examples"]

    def test_schema_help_text_carries_no_console_markup_escapes(self) -> None:
        # Help strings escape `[` for Typer's Rich renderer; the schema is data,
        # so an agent must read `in [a, b]`, not `in \[a, b]`.
        schemas = get_capabilities()["command_schemas"]
        where = next(
            option for option in schemas["search"]["options"] if option["flags"] == ["--where"]
        )
        assert "in [article, inproceedings]" in where["help"]
        assert "\\[" not in where["help"]

    def test_predicate_grammar_names_every_selector_surface(self) -> None:
        # One transversal selector surface: if a command grows a --where, it
        # belongs here, so an agent can tell where a selector is accepted.
        grammar = get_capabilities()["predicate_grammar"]
        assert grammar["used_by"] == [
            "fields (--where, --key)",
            "search (--where, --key)",
            "format (--where, --key)",
            "corpus combine (--where, --key)",
            "corpus split (--to)",
            "batch (fields.* where)",
        ]
        # --key is the no-grammar shorthand, so its relationship to --where has
        # to be stated where an agent reads the selector surface.
        assert "key in [...]" in grammar["key_selector"]

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
