"""The compatibility forms retired in v0.10 are rejected without side effects."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import Bibliography, parse_bib
from pynakes.batch import BatchError, apply_operations, operation_catalog
from pynakes.capabilities import get_capabilities
from pynakes.cli import app
from pynakes.fields import encode_field
from pynakes.lint import lint
from pynakes.metadata import metadata_key_choices, metadata_value_choices

runner = CliRunner()

REMOVED_COMMANDS = [
    ["corpus", "combine"],
    ["corpus", "split"],
    ["corpus", "batch"],
    ["fields", "encode"],
    ["fields", "protect-title"],
    ["ref", "find"],
    *[
        ["groups", name]
        for name in (
            "tree",
            "list-entries",
            "add-entry",
            "remove-entry",
            "add-group",
            "remove-group",
            "rename-group",
            "move-group",
            "update-group",
        )
    ],
]
REMOVED_OPERATIONS = ["groups.add_entry", "groups.remove_entry", "fields.protect_title"]


@pytest.mark.parametrize("command", REMOVED_COMMANDS)
@pytest.mark.parametrize("json_output", [False, True])
def test_removed_cli_commands_are_usage_errors(tmp_path: Path, command, json_output):
    path = tmp_path / "refs.bib"
    source = b"@book{Newton, title={Principia}}\n"
    path.write_bytes(source)
    args = [*command, str(path), *(["--json"] if json_output else [])]
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert "No such command" in result.output
    assert "Traceback" not in result.output
    if json_output:
        payload = json.loads(result.output)
        assert payload["status"] == "error" and payload["error"] == "UsageError"
    assert path.read_bytes() == source
    assert list(tmp_path.iterdir()) == [path]


def test_removed_lookup_flag_cannot_trigger_network(monkeypatch):
    from pynakes import lookup

    def forbidden(*args, **kwargs):
        raise AssertionError("A rejected command must not reach the network")

    monkeypatch.setattr(lookup, "find_reference", forbidden)
    for command in ("find", "lookup"):
        result = runner.invoke(app, ["ref", command, "Principia", "--online", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error"] == "UsageError"


@pytest.mark.parametrize("operation", REMOVED_OPERATIONS)
def test_removed_batch_operations_are_rejected_without_committing(tmp_path: Path, operation):
    source = "@book{Newton, title={Principia}}\n"
    coll = Bibliography.from_text(source)
    with pytest.raises(BatchError, match="unknown operation"):
        apply_operations(coll, [{"op": operation}])
    assert not coll.is_dirty
    path = tmp_path / "refs.bib"
    path.write_text(source, encoding="utf-8")
    before = path.read_bytes()
    operations = [
        {"op": "fields.set", "field": "note", "value": "Staged only"},
        {"op": operation},
    ]
    result = runner.invoke(app, ["batch", str(path), "--ops", json.dumps(operations), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == "InvalidInput" and payload["index"] == 1
    assert payload["op"] == operation
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_removed_forms_are_not_advertised():
    capabilities = get_capabilities()
    assert capabilities["deprecations"] == []
    assert all(
        " ".join(command) not in capabilities["command_schemas"] for command in REMOVED_COMMANDS
    )
    assert set(REMOVED_OPERATIONS).isdisjoint(operation_catalog())
    assert "fields-encoding" not in capabilities["settings"]
    assert "fields-encoding" not in metadata_value_choices()
    assert "fields-encoding" not in metadata_key_choices()["pynakes"]


def test_removed_encoding_setting_is_preserved_but_never_used(tmp_path: Path):
    source = "@comment{pynakes-meta: fields-encoding:latex;}\n@book{Example, title={Café}}\n"
    bib = parse_bib(source)
    with pytest.raises(ValueError, match="Choose to"):
        encode_field(bib, "title")
    assert bib.entries["Example"].fields["title"] == "Café"
    (issue,) = [issue for issue in lint(bib) if issue.key == "fields-encoding"]
    assert issue.type == "unknown_metadata_key"
    assert "removed" in issue.message and "normalize-encoding" in issue.message
    path = tmp_path / "refs.bib"
    path.write_text(source, encoding="utf-8")
    before = path.read_bytes()
    result = runner.invoke(app, ["normalize", str(path), "--only", "encoding", "--json"])
    assert result.exit_code == 0
    assert path.read_bytes() == before
    assert "normalize-encoding" not in path.read_text(encoding="utf-8")
