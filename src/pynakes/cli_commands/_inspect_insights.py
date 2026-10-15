"""Supplementary inspect reports sharing one bibliography snapshot.

One parse serves the whole read a client makes to draw a library: groups,
lint, citations in the linked TeX sources, and material state. Each report is
the envelope its own command would emit, and fails on its own.
"""

from collections.abc import Callable
from pathlib import Path

from pynakes import group_tree
from pynakes.bibtex_parser import ParseError
from pynakes.cli_checks import _file_result, error_code_for
from pynakes.cli_commands.asset_check import asset_check_collection
from pynakes.cli_commands.lint import _lint_collection
from pynakes.cli_commands.tex_scan import linked_scan_result
from pynakes.cli_common import _source_sha256
from pynakes.engine import Bibliography


def inspect_insights(
    coll: Bibliography, file: str, location: str | Path | None = None
) -> dict[str, dict]:
    """Return independent report envelopes; failures remain advisory.

    ``location`` is where the library lives (default ``file``): linked TeX
    sources, ``file`` links, and the Pinax directory resolve from it, so a
    client reading a copy of an unsaved buffer sees the original's neighbours.
    """
    where = location if location is not None else file

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
            return _error_envelope(exc)

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
        "lint": report(
            "lint", lambda: _file_result(_lint_collection(coll, file, location=where), False)
        ),
        "tex_scan": _guarded(lambda: linked_scan_result(coll, file, where)),
        "asset_check": _guarded(
            lambda: _file_result(asset_check_collection(coll, file, location=where), False)
        ),
    }


def _guarded(read: Callable[[], dict]) -> dict:
    """Return a complete envelope, or the error one if building it failed."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - supplementary reads must not hide the table
        return _error_envelope(exc)


def _error_envelope(exc: Exception) -> dict:
    code = (
        error_code_for(exc).value
        if isinstance(exc, (ValueError, OSError, ParseError))
        else "InternalError"
    )
    result: dict[str, object] = {"status": "error", "error": code, "message": str(exc)}
    if isinstance(exc, ParseError):
        result["line"] = exc.line
    return result
