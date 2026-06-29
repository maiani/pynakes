"""Small schema validators for agent-eval payloads.

The harness deliberately avoids adding a JSON-schema dependency. These checks
validate only the contract the runner needs before it trusts an agent payload.
"""

from __future__ import annotations

import json
from typing import Any


class PayloadError(ValueError):
    """Raised when an agent returns malformed structured output."""


FINDING_CATEGORIES = {"bug", "documentation", "inconsistent-behavior", "ux", "external"}


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a top-level JSON object from plain text or a fenced block."""

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise PayloadError("payload does not contain a JSON object") from None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PayloadError(f"payload is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise PayloadError("payload must be a JSON object")
    return payload


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"{path} must be a non-empty string")
    return value


def _require_str_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PayloadError(f"{path} must be a non-empty list")
    result: list[str] = []
    for idx, item in enumerate(value):
        result.append(_require_str(item, f"{path}[{idx}]"))
    return result


def _require_optional_str_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        raise PayloadError(f"{path} must be a list")
    result: list[str] = []
    for idx, item in enumerate(value):
        result.append(_require_str(item, f"{path}[{idx}]"))
    return result


def _require_task_kind(value: Any, path: str) -> str:
    kind = _require_str(value, path)
    if not all(char.isalnum() or char in {"-", "_"} for char in kind):
        raise PayloadError(f"{path} must contain only letters, digits, '-' or '_'")
    return kind


def validate_tasks_payload(
    payload: dict[str, Any], *, include_online: bool
) -> list[dict[str, Any]]:
    """Validate and return supervisor-generated tasks."""

    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise PayloadError("tasks must be a non-empty list")

    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            raise PayloadError(f"tasks[{idx}] must be an object")
        task_id = _require_str(raw_task.get("id"), f"tasks[{idx}].id")
        if task_id in seen_ids:
            raise PayloadError(f"duplicate task id: {task_id}")
        seen_ids.add(task_id)

        kind = _require_task_kind(raw_task.get("kind"), f"tasks[{idx}].kind")
        online = bool(raw_task.get("online", False))
        if online and not include_online:
            raise PayloadError(f"online task emitted without --include-online: {task_id}")
        if (kind == "online" or kind.startswith("online-")) and not online:
            raise PayloadError(f"{task_id} has online kind but online=false")

        tasks.append(
            {
                "id": task_id,
                "kind": kind,
                "online": online,
                "instruction": _require_str(
                    raw_task.get("instruction"), f"tasks[{idx}].instruction"
                ),
                "success_criteria": _require_str_list(
                    raw_task.get("success_criteria"), f"tasks[{idx}].success_criteria"
                ),
            }
        )
    return tasks


def validate_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a beta-tester report."""

    _require_str(payload.get("summary"), "summary")
    raw_results = payload.get("task_results")
    if not isinstance(raw_results, list):
        raise PayloadError("task_results must be a list")
    for idx, result in enumerate(raw_results):
        if not isinstance(result, dict):
            raise PayloadError(f"task_results[{idx}] must be an object")
        _require_str(result.get("task_id"), f"task_results[{idx}].task_id")
        status = _require_str(result.get("status"), f"task_results[{idx}].status")
        if status not in {"success", "partial", "failed", "skipped"}:
            raise PayloadError(f"unsupported task result status: {status}")
        _require_str(result.get("notes"), f"task_results[{idx}].notes")

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise PayloadError("findings must be a list")
    for idx, finding in enumerate(raw_findings):
        if not isinstance(finding, dict):
            raise PayloadError(f"findings[{idx}] must be an object")
        category = _require_str(finding.get("category"), f"findings[{idx}].category")
        if category not in FINDING_CATEGORIES:
            raise PayloadError(f"unsupported finding category: {category}")
        _require_str(finding.get("title"), f"findings[{idx}].title")
        _require_str(finding.get("details"), f"findings[{idx}].details")

    improvements = payload.get("improvements", [])
    if improvements is None:
        payload["improvements"] = []
    else:
        _require_optional_str_list(improvements, "improvements")
    return payload
