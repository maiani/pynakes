#!/usr/bin/env python3
"""Measure and score the agent evaluation suite in ``evals/agent``.

Developer-only: not part of the package. Two subcommands:

``measure``
    Run every task's *reference solution* — the calls a careful agent would
    make — against a fresh copy of its fixture, and report per task the number
    of calls, the bytes of every JSON response, whether each step's checks
    held, whether the expected keys were reachable, and whether the library
    ended in the expected state. These are the baselines a recorded agent run
    is compared with, and a check that the engine still supports each task.

``score``
    Score one recorded agent run (a transcript; see ``evals/agent/README.md``)
    against its task and, optionally, a ``measure`` report: answer
    correctness, preserved uncertainty, reviewer-counted unsupported claims,
    calls beyond the reference, response size relative to the reference, and
    whether the library ended where the approved plan says.

Neither subcommand runs a model or touches the network. Usage::

    python scripts/agent_eval.py measure [--task ID ...] [--out report.json]
    python scripts/agent_eval.py score run.json [--baseline report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from typer.testing import CliRunner

import pynakes
from pynakes.cli import app

SUITE = Path(__file__).resolve().parent.parent / "evals" / "agent"
_TEMPLATE = re.compile(r"\{step(\d+)\.([A-Za-z0-9_.]+)\}")
_MAX_PAGES = 100


@dataclass
class Call:
    """One CLI call: what was run, how it exited, and how large the response was."""

    argv: list[str]
    exit_code: int
    response_bytes: int


@dataclass
class TaskMeasurement:
    """The reference solution's run of one task."""

    id: str
    category: str
    calls: list[Call] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    keys_seen: list[str] = field(default_factory=list)
    expected_keys_reachable: bool = False
    library_outcome_ok: bool = False

    @property
    def response_bytes(self) -> int:
        return sum(call.response_bytes for call in self.calls)

    @property
    def passed(self) -> bool:
        return not self.failed_checks and self.expected_keys_reachable and self.library_outcome_ok

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "category": self.category,
            "passed": self.passed,
            "call_count": len(self.calls),
            "response_bytes": self.response_bytes,
            "max_response_bytes": max((call.response_bytes for call in self.calls), default=0),
            "failed_checks": self.failed_checks,
            "keys_seen": self.keys_seen,
            "expected_keys_reachable": self.expected_keys_reachable,
            "library_outcome_ok": self.library_outcome_ok,
            "calls": [asdict(call) for call in self.calls],
        }


# --- task loading ---------------------------------------------------------------------


def load_tasks(suite: Path = SUITE) -> list[dict]:
    """Return the task definitions of the suite."""
    data = json.loads((suite / "tasks.json").read_text(encoding="utf-8"))
    return list(data["tasks"])


def expected_library(task: dict, suite: Path = SUITE) -> bytes:
    """Return the bytes the library must hold after a correct run of ``task``."""
    original = (suite / "fixtures" / task["fixture"]).read_bytes()
    outcome = task["expected"]["library"]
    if outcome == "unchanged":
        return original
    if outcome == "external_change_only":
        mutation = "".join(
            step["mutate"]["append"] for step in task["reference"] if "mutate" in step
        )
        return original + mutation.encode("utf-8")
    raise ValueError(f"Unknown library outcome {outcome!r} in task {task['id']!r}")


# --- measuring the reference solutions ---------------------------------------------


def _lookup(payload: object, path: str) -> object:
    current = payload
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _render(argv: list[str], lib: Path, payloads: list[object]) -> list[str]:
    def substitute(match: re.Match[str]) -> str:
        return str(_lookup(payloads[int(match.group(1))], match.group(2)))

    return [_TEMPLATE.sub(substitute, part.replace("{lib}", str(lib))) for part in argv]


def _keys_in(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("entries") or payload.get("matches") or []
    return [str(row["key"]) for row in rows if isinstance(row, dict) and "key" in row]


def measure_task(task: dict, workdir: Path, suite: Path = SUITE) -> TaskMeasurement:
    """Run ``task``'s reference solution in ``workdir`` and measure it."""
    lib = workdir / task["fixture"]
    shutil.copyfile(suite / "fixtures" / task["fixture"], lib)
    runner = CliRunner()
    result = TaskMeasurement(id=task["id"], category=task["category"])
    payloads: list[object] = []

    for index, step in enumerate(task["reference"]):
        if "mutate" in step:
            with lib.open("a", encoding="utf-8", newline="") as handle:
                handle.write(step["mutate"]["append"])
            payloads.append(None)
            continue
        base = _render(step["argv"], lib, payloads)
        # Checks and {stepN...} templates read a step's first response; a paged
        # step continues with --cursor until its selection is complete.
        first: object = None
        argv = base
        for page in range(_MAX_PAGES):
            invoked = runner.invoke(app, argv)
            result.calls.append(Call(argv, invoked.exit_code, len(invoked.output.encode("utf-8"))))
            if invoked.exit_code != step.get("expect_exit", 0):
                result.failed_checks.append(f"step {index}: exit {invoked.exit_code}")
            try:
                payload = json.loads(invoked.output)
            except ValueError:
                result.failed_checks.append(f"step {index}: response is not JSON")
                break
            first = payload if page == 0 else first
            result.keys_seen += _keys_in(payload)
            next_cursor = _lookup(payload, "page.next_cursor")
            if not step.get("paginate") or not next_cursor:
                break
            argv = [*base, "--cursor", str(next_cursor)]
        payloads.append(first)
        for check in step.get("checks", []):
            actual = _lookup(first, check["path"])
            if actual != check["equals"]:
                result.failed_checks.append(
                    f"step {index}: {check['path']} is {actual!r}, expected {check['equals']!r}"
                )

    expected_keys = task["expected"]["answer_keys"]
    if task["category"] == "bounded_reads":
        # Paging must deliver the selection exactly: nothing skipped, nothing twice.
        result.expected_keys_reachable = result.keys_seen == expected_keys
    else:
        # The answer is reachable when every expected key was read or addressed.
        addressed = {key for call in result.calls for part in call.argv for key in part.split(",")}
        result.expected_keys_reachable = set(expected_keys) <= addressed | set(result.keys_seen)
    result.library_outcome_ok = lib.read_bytes() == expected_library(task, suite)
    return result


def measure(task_ids: list[str] | None = None, suite: Path = SUITE) -> dict[str, object]:
    """Measure every (or the selected) task and return the report."""
    tasks = [task for task in load_tasks(suite) if not task_ids or task["id"] in task_ids]
    measured = []
    for task in tasks:
        with tempfile.TemporaryDirectory() as tmp:
            measured.append(measure_task(task, Path(tmp), suite).to_dict())
    return {
        "suite": "evals/agent",
        "engine_version": pynakes.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tasks": measured,
    }


# --- scoring a recorded agent run --------------------------------------------------


def score(transcript: dict, baseline: dict | None = None, suite: Path = SUITE) -> dict[str, object]:
    """Score one recorded agent run against its task (and a ``measure`` baseline)."""
    tasks = {task["id"]: task for task in load_tasks(suite)}
    task = tasks.get(transcript.get("task", ""))
    if task is None:
        raise ValueError(f"Unknown task {transcript.get('task')!r}")
    expected = task["expected"]
    answer = transcript.get("answer") or {}
    calls = transcript.get("calls") or []

    reference = None
    if baseline is not None:
        reference = next((item for item in baseline["tasks"] if item["id"] == task["id"]), None)
    reference_calls = reference["call_count"] if reference else None
    reference_bytes = reference["response_bytes"] if reference else None
    response_bytes = sum(int(call.get("response_bytes", 0)) for call in calls)

    library_sha = transcript.get("library_sha256_after")
    expected_sha = hashlib.sha256(expected_library(task, suite)).hexdigest()
    review = transcript.get("review") or {}
    return {
        "task": task["id"],
        "engine_version": transcript.get("engine_version"),
        "agent": transcript.get("agent"),
        "conditions": transcript.get("conditions"),
        "correct": sorted(answer.get("keys") or []) == sorted(expected["answer_keys"]),
        "uncertainty_preserved": bool(answer.get("reported_ambiguity"))
        == expected["must_report_ambiguity"],
        "unsupported_claims": review.get("unsupported_claims"),
        "call_count": len(calls),
        "unnecessary_calls": (
            max(0, len(calls) - reference_calls) if reference_calls is not None else None
        ),
        "response_bytes": response_bytes,
        "response_size_ratio": (
            round(response_bytes / reference_bytes, 3) if reference_bytes else None
        ),
        "edits_match_plan": library_sha == expected_sha if library_sha else None,
    }


# --- command line ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    measure_parser = sub.add_parser("measure", help="Run the reference solutions")
    measure_parser.add_argument("--task", action="append", help="Measure only this task")
    measure_parser.add_argument("--out", type=Path, help="Write the report here")
    score_parser = sub.add_parser("score", help="Score a recorded agent run")
    score_parser.add_argument("transcript", type=Path)
    score_parser.add_argument("--baseline", type=Path, help="A measure report to compare with")
    args = parser.parse_args(argv)

    if args.command == "measure":
        report = measure(args.task)
        text = json.dumps(report, indent=2) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0 if all(task["passed"] for task in report["tasks"]) else 1

    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    sys.stdout.write(json.dumps(score(transcript, baseline), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
