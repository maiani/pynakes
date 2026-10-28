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


def test_prepare_and_collect_run_a_task_through_the_logging_wrapper(tmp_path: Path) -> None:
    import json
    import os
    import subprocess

    run = tmp_path / "run"
    (task_dir,) = agent_eval.prepare(run, sys.executable, ["concurrent-edit"])
    library = task_dir / "historical.bib"
    assert str(library) in (task_dir / "brief.md").read_text(encoding="utf-8")
    preview = subprocess.run(
        [
            sys.executable,
            str(task_dir / "bin" / "pynakes"),
            "ref",
            "edit",
            str(library),
            "Newton1687",
            "--field",
            "note=first edition",
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert preview.returncode == 0, preview.stderr
    # The task's external edit lands after the first successful preview.
    assert library.read_text(encoding="utf-8").endswith("% edited in another tool\n")
    (task_dir / "answer.md").write_text("Stopped on ExternalModification.\n", encoding="utf-8")
    review = {"keys": ["Newton1687"], "reported_ambiguity": False, "unsupported_claims": 0}
    (task_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")

    (scored,) = agent_eval.collect(run, None, {"engine_version": "test"})
    assert scored["correct"] and scored["uncertainty_preserved"] and scored["edits_match_plan"]
    transcript = json.loads((run / "concurrent-edit.transcript.json").read_text(encoding="utf-8"))
    assert transcript["calls"][0]["argv"][:2] == ["ref", "edit"]
    assert '"dry_run":true' in transcript["calls"][0]["stdout"]
    assert "concurrent-edit" in (run / "summary.md").read_text(encoding="utf-8")
