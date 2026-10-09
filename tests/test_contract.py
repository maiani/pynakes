"""Gate 4: the CLI surface is enforced, not sampled.

Each test reads the live command tree, so a command, argument, flag, envelope
key, or error code that changes without its table here changing fails. The
tables are the contract the beta promises: editing one is a deliberate surface
change, which from 0.7.0 needs a deprecation (see docs/guides/public-api.md).
"""

import ast
import json
import shutil
from collections import defaultdict
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from pynakes.capabilities import command_schemas, get_capabilities
from pynakes.cli import app
from pynakes.cli_errors import CATALOGUE, ErrorCode

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
SRC = Path(__file__).parent.parent / "src" / "pynakes"

SCHEMAS = command_schemas()


def _flags(command: str) -> set[str]:
    return {flag for option in SCHEMAS[command]["options"] for flag in option["flags"]}


# --- positional signatures --------------------------------------------------

#: Every command's positional arguments: (name, required, variadic), in order.
POSITIONALS: dict[str, tuple[tuple[str, bool, bool], ...]] = {
    "asset check": (("files", True, True),),
    "asset fetch": (("file", False, False), ("target", False, False)),
    "asset repair": (("file", False, False),),
    "capabilities": (),
    "convert": (("file", False, False),),
    "corpus batch": (("file", False, False),),
    "corpus combine": (("inputs", True, True),),
    "corpus split": (("inputs", True, True),),
    "dedupe check": (("files", True, True),),
    "dedupe merge": (("file", False, False),),
    "enrich": (("file", False, False),),
    "fields append": (("file", False, False), ("field", True, False), ("value", True, False)),
    "fields clear": (("file", False, False), ("field", True, False)),
    "fields move": (("file", False, False), ("old", True, False), ("new", True, False)),
    "fields protect-title": (("file", False, False),),
    "fields rename": (("file", False, False), ("old", True, False), ("new", True, False)),
    "fields set": (("file", False, False), ("field", True, False), ("value", True, False)),
    "format": (("file", False, False),),
    "groups add-entry": (("file", False, False), ("key", True, False), ("group", True, False)),
    "groups add-group": (("file", False, False), ("name", True, False)),
    "groups list": (("file", False, False),),
    "groups list-entries": (("file", False, False), ("name", True, False)),
    "groups move-group": (("file", False, False), ("name", True, False)),
    "groups remove-entry": (("file", False, False), ("key", True, False), ("group", True, False)),
    "groups remove-group": (("file", False, False), ("name", True, False)),
    "groups rename-group": (("file", False, False), ("old", True, False), ("new", True, False)),
    "groups tree": (("file", False, False),),
    "groups update-group": (("file", False, False), ("name", True, False)),
    "init": (("file", False, False),),
    "inspect": (("file", False, False),),
    "keys check": (("files", True, True),),
    "keys generate": (("file", False, False), ("key", False, False)),
    "keys rename": (
        ("file", False, False),
        ("old", True, False),
        ("new", True, False),
        ("sources", False, True),
    ),
    "keys repair": (("file", False, False),),
    "keys usage": (("key", True, False), ("sources", True, True)),
    "lint": (("files", True, True),),
    "metadata adopt-jabref": (("file", False, False),),
    "metadata list": (("file", False, False),),
    "metadata remove": (("file", False, False), ("key", True, False)),
    "metadata set": (("file", False, False), ("key", True, False), ("value", True, False)),
    "normalize": (("file", False, False),),
    "ref add": (("file", False, False), ("key", False, False)),
    "ref compare": (("file", False, False), ("key", True, False)),
    "ref directive": (("file", False, False), ("words", True, True)),
    "ref edit": (("file", False, False), ("key", True, False)),
    "ref find": (("text", True, False),),
    "ref import": (("file", False, False), ("identifiers", True, True)),
    "ref remove": (("file", False, False), ("citekeys", True, True)),
    "ref show": (("file", False, False), ("key", False, False)),
    "scrub": (("file", False, False),),
    "search": (("file", False, False), ("query", True, False)),
    "tex add": (("file", False, False), ("paths", True, True)),
    "tex clear": (("file", False, False),),
    "tex list": (("file", False, False),),
    "tex remove": (("file", False, False), ("paths", True, True)),
    "tex scan": (("file", False, False), ("sources", False, True)),
    "verify": (("files", True, True),),
}


def test_every_command_has_exactly_the_recorded_positionals() -> None:
    actual = {
        name: tuple(
            (arg["name"], arg["required"], bool(arg.get("variadic"))) for arg in schema["arguments"]
        )
        for name, schema in SCHEMAS.items()
    }

    assert actual == POSITIONALS


def test_a_single_library_command_takes_it_first_and_as_file() -> None:
    # The library-first convention: an optional leading FILE (auto-detected
    # when omitted), also accepted as --file/-f.
    for name, positionals in POSITIONALS.items():
        if positionals and positionals[0][0] == "file":
            assert positionals[0][1] is False, name
            assert {"--file", "-f"} <= _flags(name), name


# --- one meaning per flag spelling -----------------------------------------

#: Spellings deliberately carrying more than one shape, and why.
FLAG_SHAPE_EXCEPTIONS = {
    # The key to assign on `ref import`; the keys to act on everywhere else
    # (see `pynakes.cli_common.key_option`).
    "--key": 2,
    # The same field name: several on `normalize`, one on `fields protect-title`.
    "--title-field": 2,
}


def test_each_flag_spelling_has_one_meaning() -> None:
    shapes: dict[str, set[tuple]] = defaultdict(set)
    for schema in SCHEMAS.values():
        for option in schema["options"]:
            shape = (option["type"], tuple(sorted(option["flags"])))
            for flag in option["flags"]:
                shapes[flag].add(shape)

    divergent = {
        flag: sorted(found)
        for flag, found in shapes.items()
        if len(found) != FLAG_SHAPE_EXCEPTIONS.get(flag, 1)
    }

    assert divergent == {}


def test_strict_gates_checks_and_check_previews_transforms() -> None:
    # --strict gates a read-only check; --check is a transform's check mode.
    strict = {name for name in SCHEMAS if "--strict" in _flags(name)}
    check = {name for name in SCHEMAS if "--check" in _flags(name)}

    assert strict == set(get_capabilities()["gate_commands"])
    assert check == {"format", "scrub"}


def test_every_writing_command_previews() -> None:
    # A command that writes the library offers --dry-run and --diff together.
    for name in SCHEMAS:
        flags = _flags(name)
        if "--dry-run" in flags:
            assert "--diff" in flags, name


# --- envelope schemas -------------------------------------------------------

#: One offline invocation per command, and the envelope family it returns.
#: ``ref find`` and ``ref import`` need the network; offline they return an
#: error envelope, which is checked like any other.
SAMPLES: dict[str, tuple[str, list[str]]] = {
    "asset check": ("check", ["asset", "check", "{bib}"]),
    "asset fetch": ("modify", ["asset", "fetch", "{bib}", "White2024", "--dry-run"]),
    "asset repair": ("modify", ["asset", "repair", "{pinax}", "--dry-run"]),
    "capabilities": ("read", ["capabilities"]),
    "convert": ("modify", ["convert", "{bib}", "--to", "biblatex", "--dry-run"]),
    "corpus batch": ("modify", ["corpus", "batch", "{bib}", "--ops-file", "{ops}", "--dry-run"]),
    "corpus combine": (
        "create",
        ["corpus", "combine", "{bib}", "{groups}", "--out", "{out}", "--dry-run"],
    ),
    "corpus split": ("create", ["corpus", "split", "{bib}", "--route", "{out}=*", "--dry-run"]),
    "dedupe check": ("check", ["dedupe", "check", "{bib}"]),
    "dedupe merge": ("modify", ["dedupe", "merge", "{dupes}", "--dry-run"]),
    "enrich": ("modify", ["enrich", "{bib}", "--dry-run"]),
    "fields append": (
        "modify",
        ["fields", "append", "{bib}", "note", "x", "--key", "Smith2020", "--dry-run"],
    ),
    "fields clear": (
        "modify",
        ["fields", "clear", "{bib}", "doi", "--key", "Smith2020", "--dry-run"],
    ),
    "fields move": (
        "modify",
        ["fields", "move", "{bib}", "doi", "note", "--key", "Smith2020", "--dry-run"],
    ),
    "fields protect-title": ("modify", ["fields", "protect-title", "{bib}", "--dry-run"]),
    "fields rename": ("modify", ["fields", "rename", "{bib}", "doi", "note", "--dry-run"]),
    "fields set": (
        "modify",
        ["fields", "set", "{bib}", "note", "x", "--key", "Smith2020", "--dry-run"],
    ),
    "format": ("modify", ["format", "{bib}", "--dry-run"]),
    "groups add-entry": (
        "modify",
        ["groups", "add-entry", "{groups}", "Smith2020", "Blockchain", "--dry-run"],
    ),
    "groups add-group": ("modify", ["groups", "add-group", "{groups}", "Optics", "--dry-run"]),
    "groups list": ("read", ["groups", "list", "{groups}"]),
    "groups list-entries": ("read", ["groups", "list-entries", "{groups}", "Blockchain"]),
    "groups move-group": (
        "modify",
        [
            "groups",
            "move-group",
            "{groups}",
            "Blockchain:Cryptocurrency",
            "--parent",
            "Machine Learning:AI Papers",
            "--dry-run",
        ],
    ),
    "groups remove-entry": (
        "modify",
        ["groups", "remove-entry", "{groups}", "Smith2020", "AI Papers", "--dry-run"],
    ),
    "groups remove-group": (
        "modify",
        ["groups", "remove-group", "{groups}", "Blockchain:Cryptocurrency", "--dry-run"],
    ),
    "groups rename-group": (
        "modify",
        ["groups", "rename-group", "{groups}", "Blockchain:Cryptocurrency", "Ledgers", "--dry-run"],
    ),
    "groups tree": ("read", ["groups", "tree", "{groups}"]),
    "groups update-group": (
        "modify",
        [
            "groups",
            "update-group",
            "{groups}",
            "Blockchain:Cryptocurrency",
            "--context",
            "independent",
            "--dry-run",
        ],
    ),
    "init": ("create", ["init", "{new}", "--dry-run"]),
    "inspect": ("read", ["inspect", "{bib}"]),
    "keys check": ("check", ["keys", "check", "{bib}"]),
    "keys generate": ("modify", ["keys", "generate", "{bib}", "--all", "--dry-run"]),
    "keys rename": ("modify", ["keys", "rename", "{bib}", "Smith2020", "Smith2020a", "--dry-run"]),
    "keys repair": ("modify", ["keys", "repair", "{dupes}", "--dry-run"]),
    "keys usage": ("read", ["keys", "usage", "Smith2020", "{tex}"]),
    "lint": ("check", ["lint", "{bib}"]),
    "metadata adopt-jabref": ("modify", ["metadata", "adopt-jabref", "{groups}", "--dry-run"]),
    "metadata list": ("read", ["metadata", "list", "{bib}"]),
    "metadata remove": (
        "modify",
        ["metadata", "remove", "{groups}", "groupsversion", "--dry-run"],
    ),
    "metadata set": ("modify", ["metadata", "set", "{bib}", "dialect", "biblatex", "--dry-run"]),
    "normalize": ("modify", ["normalize", "{bib}", "--dry-run"]),
    "ref add": (
        "modify",
        [
            "ref",
            "add",
            "{bib}",
            "Euler1748",
            "--type",
            "misc",
            "--field",
            "title=Introductio",
            "--dry-run",
        ],
    ),
    "ref compare": ("read", ["ref", "compare", "{bib}", "Smith2020", "--with", "Jones2021"]),
    "ref directive": (
        "modify",
        ["ref", "directive", "{bib}", "ignore", "missing_doi", "--key", "Brown2022", "--dry-run"],
    ),
    "ref edit": ("modify", ["ref", "edit", "{bib}", "Smith2020", "--field", "note=x", "--dry-run"]),
    "ref find": ("error", ["ref", "find", "Newton, Principia, 1687"]),
    "ref import": ("error", ["ref", "import", "{bib}", "not-an-identifier", "--dry-run"]),
    "ref remove": ("modify", ["ref", "remove", "{bib}", "White2024", "--dry-run"]),
    "ref show": ("read", ["ref", "show", "{bib}", "Smith2020"]),
    "scrub": ("create", ["scrub", "{bib}", "--out", "{out}", "--dry-run"]),
    "search": ("read", ["search", "{bib}", "machine"]),
    "tex add": ("modify", ["tex", "add", "{bib}", "{tex}", "--dry-run"]),
    "tex clear": ("modify", ["tex", "clear", "{bib}", "--dry-run"]),
    "tex list": ("read", ["tex", "list", "{bib}"]),
    "tex remove": ("modify", ["tex", "remove", "{bib}", "{tex}", "--dry-run"]),
    "tex scan": ("modify", ["tex", "scan", "{bib}", "{tex}"]),
    "verify": ("check", ["verify", "{bib}"]),
}

#: The keys each envelope family carries on success.
FAMILY_KEYS = {
    "modify": {
        "status",
        "action",
        "file",
        "dry_run",
        "modified",
        "modified_entries",
        "warnings",
        "source_sha256",
    },
    "create": {"status", "action", "dry_run", "warnings"},
    "read": {"status", "action", "warnings"},
    "check": {"status", "action", "file", "warnings", "source_sha256", "strict"},
}

#: Read-only commands that read no library, so report no digest of one.
NO_LIBRARY_READ = {"capabilities", "keys usage"}


def _library(tmp_path: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    for name, fixture in (
        ("bib", "simple.bib"),
        ("groups", "jabref_groups.bib"),
        ("dupes", "duplicate_entries.bib"),
        ("tex", "paper.tex"),
    ):
        target = tmp_path / fixture
        shutil.copy(FIXTURES / fixture, target)
        paths[name] = str(target)
    pinax = tmp_path / "pinax.bib"
    pinax.write_text(
        "@comment{pynakes-meta:\npinax-files-dir: pinax.files\n}\n\n"
        "@misc{Euler1748,\n  title = {Introductio},\n  year = {1748}\n}\n"
    )
    (tmp_path / "pinax.files").mkdir()
    paths["pinax"] = str(pinax)
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps([{"op": "fields.append", "field": "keywords", "value": "ml"}]))
    paths["ops"] = str(ops)
    paths["out"] = str(tmp_path / "out.bib")
    paths["new"] = str(tmp_path / "new.bib")
    return paths


def test_every_command_has_an_envelope_sample() -> None:
    assert set(SAMPLES) == set(SCHEMAS)


@pytest.mark.parametrize("command", sorted(SAMPLES))
def test_envelope_schema(command: str, tmp_path: Path) -> None:
    family, argv = SAMPLES[command]
    paths = _library(tmp_path)

    result = runner.invoke(app, [part.format(**paths) for part in argv] + ["--json"])
    payload = json.loads(result.output)

    if family == "error":
        code = ErrorCode(payload["error"])
        assert payload["status"] == CATALOGUE[code].status
        assert result.exit_code == CATALOGUE[code].exit_code
        assert isinstance(payload["message"], str) and payload["message"]
        return
    assert result.exit_code == 0, result.output
    assert payload["status"] == "success"
    assert FAMILY_KEYS[family] <= payload.keys(), FAMILY_KEYS[family] - payload.keys()
    assert payload["action"] == command.replace(" ", "_").replace("-", "_")
    assert all(isinstance(w, dict) and "type" in w for w in payload["warnings"])
    if family == "create":
        # A created file reports where it goes, and a digest of what it read.
        assert {"out", "written"} <= payload.keys() or "outputs" in payload
        assert command == "init" or {"source_sha256", "sources_sha256"} & payload.keys()
    if family == "read" and command not in NO_LIBRARY_READ:
        assert "source_sha256" in payload


def test_an_error_envelope_names_a_catalogued_code(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ref", "show", str(tmp_path / "missing.bib"), "A", "--json"])

    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert result.exit_code == CATALOGUE[ErrorCode(payload["error"])].exit_code


# --- error codes ------------------------------------------------------------


def _emitted_codes() -> tuple[set[str], set[str]]:
    """Return (string-literal codes, ``ErrorCode`` members) the source emits."""
    literals: set[str] = set()
    members: set[str] = set()
    for path in SRC.rglob("*.py"):
        if path.name == "cli_errors.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in {"_emit_error", "_emit_conflict"} and len(node.args) > 1:
                    if isinstance(node.args[1], ast.Constant):
                        literals.add(node.args[1].value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "error"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        literals.add(value.value)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "error"
                    ):
                        literals.add(node.value.value)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in {"ErrorCode", "_E"}:
                    members.add(node.attr)
    return literals, members


def test_every_emitted_error_code_is_catalogued() -> None:
    literals, members = _emitted_codes()
    catalogued = {code.value for code in ErrorCode}

    assert literals - catalogued == set()
    assert members - set(ErrorCode.__members__) == set()


def test_every_catalogued_error_code_is_emitted() -> None:
    literals, members = _emitted_codes()
    emitted = literals | {ErrorCode[name].value for name in members}

    assert {code.value for code in ErrorCode} - emitted == set()


# --- capabilities -----------------------------------------------------------


def _click_commands() -> dict:
    commands: dict = {}

    def walk(group, prefix: str) -> None:
        for name, command in group.commands.items():
            if hasattr(command, "commands"):
                walk(command, f"{prefix}{name} ")
            else:
                commands[f"{prefix}{name}"] = command

    walk(typer.main.get_command(app), "")
    return commands


def test_capabilities_describe_every_option_as_the_cli_parses_it() -> None:
    for name, command in _click_commands().items():
        described = {option["name"]: option for option in SCHEMAS[name]["options"]}
        for param in command.params:
            if param.param_type_name != "option":
                continue
            option = described[param.name]
            # Every spelling, including --no-* halves, -f, and the wired --file.
            assert set(option["flags"]) == {*param.opts, *param.secondary_opts}, (name, param.name)
            assert option["required"] == bool(param.required)
            if getattr(param.type, "name", "") == "choice":
                assert option["choices"] == list(param.type.choices), (name, param.name)
            if getattr(param, "is_flag", False):
                assert option["type"] == "boolean", (name, param.name)
            elif getattr(param.type, "name", "") in {"int", "int range"}:
                assert option["type"].endswith("integer"), (name, param.name)


def test_capabilities_error_codes_match_the_catalogue() -> None:
    described = get_capabilities()["error_codes"]

    for status, exit_code in (("error", 1), ("conflict", 2)):
        assert described[status]["exit_code"] == exit_code
        expected = {code.value for code, spec in CATALOGUE.items() if spec.exit_code == exit_code}
        assert set(described[status]["codes"]) == expected
