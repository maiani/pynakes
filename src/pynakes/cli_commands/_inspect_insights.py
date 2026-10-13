"""Supplementary inspect reports sharing one bibliography snapshot."""

from collections.abc import Callable

from pynakes import group_tree
from pynakes.bibtex_parser import ParseError
from pynakes.cli_checks import _file_result, error_code_for
from pynakes.cli_commands.lint import _lint_collection
from pynakes.cli_common import _source_sha256
from pynakes.engine import Bibliography


def inspect_insights(coll: Bibliography, file: str) -> dict[str, dict]:
    """Return independent group and lint envelopes; failures remain advisory."""

    def report(action: str, read: Callable[[], dict]) -> dict:
        try:
            return {
                "status": "success",
                "action": action,
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                **read(),
            }
        except Exception as exc:  # noqa: BLE001 - supplementary reads must not hide the table
            code = (
                error_code_for(exc).value
                if isinstance(exc, (ValueError, OSError, ParseError))
                else "InternalError"
            )
            result = {"status": "error", "error": code, "message": str(exc)}
            if isinstance(exc, ParseError):
                result["line"] = exc.line
            return result

    return {
        "groups_tree": report(
            "groups_tree",
            lambda: {
                "tree": [node.to_dict() for node in group_tree.list_tree(coll.lib) or []],
            },
        ),
        "groups_list": report(
            "groups_list",
            lambda: {
                "groups": {
                    name: group_tree.list_direct_members(coll.lib, name)
                    for name in group_tree.known_group_names(coll.lib)
                },
            },
        ),
        "lint": report("lint", lambda: _file_result(_lint_collection(coll, file), False)),
    }
