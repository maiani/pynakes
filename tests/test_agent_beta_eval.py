"""Tests for the manual agent beta-test harness."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.agent_eval.providers import FakeProvider
from tests.agent_eval.runner import EvalConfig, HarnessError, _parse_args, run_eval


def test_fake_provider_smoke_and_malformed_payloads(tmp_path: Path) -> None:
    config = EvalConfig(provider_name="fake", out=tmp_path / "run", tasks=1)
    result = run_eval(
        config,
        provider=FakeProvider(),
        lab_root=tmp_path / "lab",
    )

    assert result.report["summary"] == "Fake beta run completed."
    assert (tmp_path / "run" / "tasks.json").exists()
    assert (tmp_path / "run" / "beta-report.json").exists()
    assert (tmp_path / "run" / "summary.md").exists()
    assert result.validator_results["inspect_exit_code"] == 0

    bad_supervisor = FakeProvider(supervisor_payload={"tasks": [{"id": "missing-fields"}]})
    with pytest.raises(HarnessError, match="malformed supervisor payload"):
        run_eval(config, provider=bad_supervisor, lab_root=tmp_path / "bad-supervisor")

    bad_report = FakeProvider(report_payload={"summary": "missing lists"})
    with pytest.raises(HarnessError, match="malformed beta report"):
        run_eval(config, provider=bad_report, lab_root=tmp_path / "bad-report")


def test_runner_accepts_codex_model_and_reasoning_overrides() -> None:
    config = _parse_args(
        [
            "--provider",
            "codex",
            "--model",
            "gpt-5.6-luna",
            "--reasoning-effort",
            "low",
        ]
    )
    assert config.model == "gpt-5.6-luna"
    assert config.reasoning_effort == "low"


@pytest.mark.agent_eval
@pytest.mark.skipif(
    os.environ.get("PYNAKES_RUN_AGENT_EVAL") != "1",
    reason="real agent eval is manual; set PYNAKES_RUN_AGENT_EVAL=1",
)
def test_real_codex_agent_eval_manual(tmp_path: Path) -> None:
    result = run_eval(
        EvalConfig(
            provider_name="codex",
            seed=1,
            tasks=3,
            out=tmp_path / "real-run",
            include_online=True,
            timeout=900,
        ),
        lab_root=tmp_path / "real-lab",
    )

    assert result.tasks
    assert result.report["task_results"]
    assert (tmp_path / "real-run" / "summary.md").exists()
