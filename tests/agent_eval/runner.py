"""Manual real-agent beta-test runner for pynakes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.agent_eval.providers import AgentProvider, provider_from_name
from tests.agent_eval.schemas import (
    PayloadError,
    extract_json_object,
    validate_report_payload,
    validate_tasks_payload,
)
from tests.agent_eval.workspace import LabWorkspace, create_lab_workspace

OFFLINE_CATALOG = [
    "Discover the CLI from `pynakes --help`, `pynakes capabilities --json`, and "
    "`docs/llm-integration.md`, then summarize the safest workflow for editing refs.bib.",
    "Inspect refs.bib with JSON output and explain entry count, duplicate keys, metadata, "
    "and any Pinax material fields visible to an agent.",
    "Run lint and key checks with JSON output, identify duplicate-key or metadata issues, "
    "and explain which issues are warnings versus errors.",
    "Repair duplicate citation keys in refs.bib and update paper.tex citations if needed, "
    "using a dry-run/diff before applying.",
    "Normalize DOI and formatting fields with dry-run and diff first, then apply only if "
    "the preview is narrow and understandable.",
    "Use `search` or `--where` filters to target a single entry, then add and remove a "
    "group or keyword without touching unrelated entries.",
    "Edit one field on one entry and verify the resulting diff is surgical rather than a "
    "full-entry rewrite.",
    "Exercise metadata operations: list current metadata, set a pynakes-meta option, "
    "dry-run the change, apply it, and inspect the resulting file.",
    "Create a small second bibliography in the lab workspace, combine it with refs.bib, "
    "then split a subset back out and inspect both outputs.",
    "Trigger at least one expected structured error, such as a missing file or bad query, "
    "and report whether the JSON envelope is actionable.",
    "Create or inspect a Pinax files-dir without online access, then verify inspect/json "
    "and asset-check behavior on a bibliography with no fetched materials.",
    "Remove or rename an entry in a Pinax-style bibliography and verify the command output "
    "makes material cleanup or rename behavior clear.",
]

ONLINE_CATALOG = [
    "Import an old/stable DOI into refs.bib, inspect the generated entry, and report "
    "whether duplicate detection and citation-key selection are understandable.",
    "Import an old/stable arXiv identifier into refs.bib, then compare the imported "
    "metadata against the arXiv URL/eprint fields.",
    "Use `ref import --fetch` with an arXiv identifier to create a Pinax entry and fetch "
    "preprint PDF/source materials in one workflow.",
    "Create or inspect a Pinax files-dir, set fetch-policy metadata, "
    "then fetch arXiv materials and inspect the manifest.",
    "Configure fetch-policy for a DOI-backed entry and run `asset fetch`, distinguishing "
    "product issues from OpenAlex/provider failures.",
    "Start from a DOI-backed paper, use online published enrichment to backfill its arXiv id, "
    "then build a Pinax and fetch the arXiv PDF/source materials.",
    "Run online verify on entries with DOI/arXiv metadata and report whether mismatches, "
    "provider errors, and clean entries are easy to distinguish.",
    "Run online enrich with dry-run/diff first, apply a safe metadata fill, and verify the "
    "post-apply inspect output.",
    "Exercise provider-cache behavior by repeating an online verify/enrich/fetch command "
    "with the same cache directory and reporting whether the workflow is clear.",
    "Attempt an online operation with an intentionally invalid DOI or arXiv id and report "
    "whether the failure looks actionable rather than like a traceback.",
]


@dataclass(frozen=True)
class EvalConfig:
    provider_name: str = "fake"
    seed: int = 1
    tasks: int = 6
    out: Path = Path(".agent-eval-runs/seed-1")
    include_online: bool = False
    strict: bool = False
    timeout: int = 900


@dataclass(frozen=True)
class EvalResult:
    out: Path
    lab: LabWorkspace
    tasks: list[dict[str, Any]]
    report: dict[str, Any]
    validator_results: dict[str, Any]


class HarnessError(RuntimeError):
    """Raised when the harness, not the product under test, fails."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _supervisor_prompt(config: EvalConfig, lab: LabWorkspace) -> str:
    catalog = OFFLINE_CATALOG + (ONLINE_CATALOG if config.include_online else [])
    return (
        "You are the supervisor for a pynakes beta-test evaluation.\n"
        "Generate task instructions for a separate beta-tester agent that has no prior "
        "knowledge of pynakes.\n"
        "Return JSON only, with this shape: "
        '{"tasks":[{"id":"task-1","kind":"inspect","online":false,'
        '"instruction":"...","success_criteria":["..."]}]}.\n'
        f"Seed: {config.seed}\n"
        f"Task count: {config.tasks}\n"
        f"Workspace files: refs.bib={lab.bib.name}, paper.tex={lab.tex.name}, "
        f"docs={lab.docs_dir.name}/llm-integration.md\n"
        f"Allowed task catalog: {json.dumps(catalog, indent=2)}\n"
        f"Online tasks allowed: {config.include_online}\n"
        "Use only old, stable public identifiers for online tasks."
    )


def _beta_prompt(tasks: list[dict[str, Any]], lab: LabWorkspace) -> str:
    return (
        "You are beta-testing the pynakes CLI as a fresh user. You do not know the "
        "project internals. Use only the command surface and docs available in this "
        "workspace.\n\n"
        "Available starting points:\n"
        "- `pynakes --help`\n"
        "- `pynakes capabilities --json`\n"
        "- `docs/llm-integration.md`\n\n"
        "Attempt each task. Prefer dry-runs before edits. Record bugs, errors, "
        "unclear documentation, inconsistent behavior, and UX improvements. If a "
        "network/provider call fails, say whether it looks external or product-related.\n\n"
        f"Workspace root: {lab.root}\n"
        f"Tasks:\n{json.dumps(tasks, indent=2)}\n\n"
        "Return JSON only with this shape: "
        '{"summary":"...","task_results":[{"task_id":"task-1","status":"success|partial|failed|skipped","notes":"..."}],'
        '"findings":[{"category":"bug|documentation|inconsistent-behavior|ux|external","title":"...","details":"..."}],'
        '"improvements":["..."]}'
    )


def _validate_lab(lab: LabWorkspace) -> dict[str, Any]:
    env = {**os.environ, **lab.env}
    proc = subprocess.run(
        [sys.executable, "-m", "pynakes", "inspect", str(lab.bib), "--json"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return {
        "inspect_exit_code": proc.returncode,
        "inspect_json": _looks_like_json(proc.stdout),
        "stderr": proc.stderr,
    }


def _looks_like_json(text: str) -> bool:
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _write_markdown_summary(
    path: Path,
    *,
    config: EvalConfig,
    lab: LabWorkspace,
    tasks: list[dict[str, Any]],
    report: dict[str, Any],
    validators: dict[str, Any],
) -> None:
    lines = [
        "# pynakes Agent Beta-Test Summary",
        "",
        f"- Provider: `{config.provider_name}`",
        f"- Seed: `{config.seed}`",
        f"- Include online: `{config.include_online}`",
        f"- Lab: `{lab.root}`",
        f"- Validator inspect exit code: `{validators['inspect_exit_code']}`",
        "",
        "## Agent Summary",
        "",
        report["summary"],
        "",
        "## Tasks",
        "",
    ]
    for task in tasks:
        lines.append(f"- `{task['id']}` ({task['kind']}): {task['instruction']}")
    lines.extend(["", "## Findings", ""])
    findings = report.get("findings", [])
    if not findings:
        lines.append("- None reported.")
    else:
        for finding in findings:
            lines.append(f"- **{finding['category']}**: {finding['title']} - {finding['details']}")
    path.write_text("\n".join(lines) + "\n")


def run_eval(
    config: EvalConfig,
    *,
    provider: AgentProvider | None = None,
    repo_root: Path | None = None,
    lab_root: Path | None = None,
) -> EvalResult:
    root = repo_root or _repo_root()
    out = config.out
    out.mkdir(parents=True, exist_ok=True)
    lab = create_lab_workspace(root, seed=config.seed, lab_root=lab_root)
    provider = provider or provider_from_name(config.provider_name, timeout=config.timeout)

    supervisor_response = provider.run(
        role="supervisor", prompt=_supervisor_prompt(config, lab), cwd=lab.root, env=lab.env
    )
    (out / "supervisor.stdout.jsonl").write_text(supervisor_response.stdout)
    (out / "supervisor.stderr.txt").write_text(supervisor_response.stderr)
    (out / "supervisor.final.txt").write_text(supervisor_response.final_text)
    if supervisor_response.returncode != 0:
        raise HarnessError(f"supervisor provider exited {supervisor_response.returncode}")

    try:
        supervisor_payload = extract_json_object(supervisor_response.final_text)
        tasks = validate_tasks_payload(supervisor_payload, include_online=config.include_online)
    except PayloadError as exc:
        raise HarnessError(f"malformed supervisor payload: {exc}") from exc
    if len(tasks) > config.tasks:
        raise HarnessError(
            f"supervisor emitted {len(tasks)} tasks, expected at most {config.tasks}"
        )
    _write_json(out / "tasks.json", {"tasks": tasks})

    beta_response = provider.run(
        role="beta", prompt=_beta_prompt(tasks, lab), cwd=lab.root, env=lab.env
    )
    (out / "beta.stdout.jsonl").write_text(beta_response.stdout)
    (out / "beta.stderr.txt").write_text(beta_response.stderr)
    (out / "beta.final.txt").write_text(beta_response.final_text)
    if beta_response.returncode != 0:
        raise HarnessError(f"beta provider exited {beta_response.returncode}")

    try:
        report = validate_report_payload(extract_json_object(beta_response.final_text))
    except PayloadError as exc:
        raise HarnessError(f"malformed beta report: {exc}") from exc
    _write_json(out / "beta-report.json", report)

    validators = _validate_lab(lab)
    _write_json(out / "validator-results.json", validators)
    _write_markdown_summary(
        out / "summary.md",
        config=config,
        lab=lab,
        tasks=tasks,
        report=report,
        validators=validators,
    )
    if config.strict and (report.get("findings") or validators["inspect_exit_code"] != 0):
        raise HarnessError("strict run failed: report findings or validator failures present")
    return EvalResult(out=out, lab=lab, tasks=tasks, report=report, validator_results=validators)


def _parse_args(argv: list[str]) -> EvalConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["codex", "fake"], default="codex")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--tasks", type=int, default=6)
    parser.add_argument("--out", type=Path, default=Path(".agent-eval-runs/seed-1"))
    parser.add_argument("--include-online", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    return EvalConfig(
        provider_name=args.provider,
        seed=args.seed,
        tasks=args.tasks,
        out=args.out,
        include_online=args.include_online,
        strict=args.strict,
        timeout=args.timeout,
    )


def main(argv: list[str] | None = None) -> int:
    config = _parse_args(argv or sys.argv[1:])
    try:
        result = run_eval(config)
    except HarnessError as exc:
        print(f"agent eval failed: {exc}", file=sys.stderr)
        return 1
    print(result.out / "summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
