"""Every agent-evaluation task stays solvable by its reference solution.

The suite in ``evals/agent`` measures how agents use pynakes; this test only
checks the engine side of each task — that the reference calls still return
what the task expects (a conflict, a stale-snapshot refusal, a complete page
set) and leave the library as the task's plan allows. The suite and its
runner are repository tooling, absent from the sdist, so the test is skipped
there.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "agent_eval.py"

if not RUNNER.is_file() or not (ROOT / "evals" / "agent" / "tasks.json").is_file():
    pytest.skip("the agent evaluation suite is not in this checkout", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("agent_eval", RUNNER)
assert _spec is not None and _spec.loader is not None
agent_eval = importlib.util.module_from_spec(_spec)
# Registered before it runs: dataclasses resolve their module through sys.modules.
sys.modules.setdefault("agent_eval", agent_eval)
_spec.loader.exec_module(agent_eval)

TASKS = agent_eval.load_tasks()


@pytest.mark.parametrize("task", TASKS, ids=[task["id"] for task in TASKS])
def test_reference_solution_meets_the_task(task: dict, tmp_path: Path) -> None:
    measured = agent_eval.measure_task(task, tmp_path)

    assert measured.failed_checks == []
    assert measured.expected_keys_reachable, measured.keys_seen
    assert measured.library_outcome_ok
