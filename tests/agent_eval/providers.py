"""Agent provider backends for the manual beta-test harness."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AgentResponse:
    final_text: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class AgentProvider(Protocol):
    name: str

    def run(self, *, role: str, prompt: str, cwd: Path, env: dict[str, str]) -> AgentResponse:
        """Run one agent turn and return its final text."""


class FakeProvider:
    """Deterministic provider used by regular pytest runs."""

    name = "fake"

    def __init__(
        self,
        *,
        supervisor_payload: dict | None = None,
        report_payload: dict | None = None,
    ) -> None:
        self.supervisor_payload = supervisor_payload or {
            "tasks": [
                {
                    "id": "fake-1",
                    "kind": "inspect",
                    "online": False,
                    "instruction": "Inspect refs.bib and report the entry count.",
                    "success_criteria": ["The agent identifies that refs.bib is readable."],
                }
            ]
        }
        self.report_payload = report_payload or {
            "summary": "Fake beta run completed.",
            "task_results": [
                {
                    "task_id": "fake-1",
                    "status": "success",
                    "notes": "The fake provider returned a deterministic success.",
                }
            ],
            "findings": [],
            "improvements": [],
        }

    def run(self, *, role: str, prompt: str, cwd: Path, env: dict[str, str]) -> AgentResponse:
        del prompt, cwd, env
        if role == "supervisor":
            payload = self.supervisor_payload
        elif role == "beta":
            payload = self.report_payload
        else:
            raise ValueError(f"unknown fake role: {role}")
        return AgentResponse(final_text=json.dumps(payload, indent=2))


class CodexProvider:
    """Real non-interactive Codex CLI provider."""

    name = "codex"

    def __init__(
        self,
        *,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort

    def run(self, *, role: str, prompt: str, cwd: Path, env: dict[str, str]) -> AgentResponse:
        last_message = cwd / f".{role}-last-message.json"
        cmd = [
            "codex",
            "exec",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.reasoning_effort:
            cmd.extend(["--config", f'model_reasoning_effort="{self.reasoning_effort}"'])
        cmd.extend(
            [
                "--cd",
                str(cwd),
                "--sandbox",
                "workspace-write",
                "--ephemeral",
                "--json",
                "--output-last-message",
                str(last_message),
                "-",
            ]
        )
        proc = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=cwd,
            env={**os.environ, **env},
            timeout=self.timeout,
            check=False,
        )
        final_text = last_message.read_text() if last_message.exists() else proc.stdout
        return AgentResponse(
            final_text=final_text,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )


def provider_from_name(
    name: str,
    *,
    timeout: int = 900,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> AgentProvider:
    if name == "fake":
        return FakeProvider()
    if name == "codex":
        return CodexProvider(
            timeout=timeout,
            model=model,
            reasoning_effort=reasoning_effort,
        )
    raise ValueError(f"unknown provider: {name}")
