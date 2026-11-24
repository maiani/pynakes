"""Sequential multi-file dispatch through the ordinary single-file commands."""

from collections.abc import Callable
from typing import Any

import typer

from pynakes.cli._common import _emit, _emit_error, _safe, _with_warnings
from pynakes.cli._result_collection import RESULT_COLLECTOR


def run_many(callback: Callable[..., None], action: str, arguments: dict[str, Any]) -> None:
    """Collect each command's unchanged envelope, including errors and conflicts."""
    files = arguments["file"]
    if arguments.get("expect_sha256") is not None:
        _emit_error(arguments["json_output"], "InvalidInput", "--expect-sha256 requires one input")
    if "-" in files:
        _emit_error(
            arguments["json_output"], "InvalidInput", f"{action} requires bibliography paths"
        )
    results: list[dict] = []
    human: list[str] = []
    for file in files:
        collected: list[dict] = []
        token = RESULT_COLLECTOR.set(collected)
        try:
            _safe(callback)(**{**arguments, "file": [file], "json_output": True})
        except typer.Exit:
            # The single-file path has already emitted the structured failure.
            pass
        finally:
            RESULT_COLLECTOR.reset(token)
        if len(collected) != 1:
            raise RuntimeError(f"{action} did not emit one result for {file}")
        result = collected[0]
        result.setdefault("file", file)
        result.setdefault("action", action)
        results.append(result)
        state = result.get("message") or (
            ("would change" if arguments["dry_run"] else "changed")
            if result.get("modified")
            else "unchanged"
        )
        human.extend(_with_warnings([f"{file}: {state}"], result.get("warnings")))
        if result.get("diff"):
            human.append(result["diff"])
    errors = sum(item["status"] == "error" for item in results)
    conflicts = sum(item["status"] == "conflict" for item in results)
    changed = sum(bool(item.get("modified")) for item in results)
    payload = {
        "status": "error" if errors else "conflict" if conflicts else "success",
        "action": action,
        "file": None,
        "dry_run": arguments["dry_run"],
        "modified": bool(changed),
        "modified_entries": sum(item.get("modified_entries", 0) for item in results),
        "warnings": [],
        "files": results,
        "summary": {"files": len(files), "modified": changed, "failed": errors + conflicts},
    }
    if errors:
        payload["error"] = "MultiFileError"
    elif conflicts:
        payload["options"] = [
            {"file": item["file"], "options": item.get("options", [])}
            for item in results
            if item["status"] == "conflict"
        ]
    human.append(f"{len(files)} file(s): {changed} changed, {errors + conflicts} failed")
    _emit(arguments["json_output"], payload, human)
    if errors or conflicts:
        raise typer.Exit(1 if errors else 2)
