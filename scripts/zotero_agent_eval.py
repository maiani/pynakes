#!/usr/bin/env python3
"""Measure the Zotero project reference workflow without a running Zotero.

Developer-only acceptance task, not a blind model evaluation. Uses the shared
synthetic transport from tests; no network calls, source writes or personal data.
Run from a development checkout: python scripts/zotero_agent_eval.py --out REPORT.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from pynakes import Bibliography
from pynakes.cli import app
from pynakes.cli.commands import zotero as commands
from pynakes.project_selection import project_bindings
from pynakes.zotero import ZoteroLibraryBackend

ROOT = Path(__file__).resolve().parent.parent
# This harness is repository tooling, never part of the installed engine.
sys.path.insert(0, str(ROOT))
from tests.zotero_fixtures import LocalAPI  # noqa: E402


def measure(workdir: Path) -> dict:
    """Execute the reviewed four-call setup and one-call full refresh task."""
    task = json.loads((ROOT / "evals/agent/zotero-project.json").read_text(encoding="utf-8"))
    api = LocalAPI()
    api.items[2]["data"]["collections"] = ["DEFGHJKL"]
    original = json.dumps(api.items, sort_keys=True)
    path = workdir / "paper.bib"
    calls = []
    payloads = []
    failures = []
    runner = CliRunner()
    with patch.object(
        commands,
        "ZoteroLibraryBackend",
        lambda **kw: ZoteroLibraryBackend(transport=httpx.MockTransport(api), **kw),
    ):
        for step in task["reference"]:
            if step["phase"] == "refresh":
                # Simulate the user correcting metadata in Zotero between operations.
                api.items[0]["data"]["title"] = "Revised Principia"
                api.items[2]["data"]["title"] = "Revised experiment"
                api.revision += 1
            substitutions = {"file": str(path)}
            if len(payloads) >= 3:
                substitutions.update(
                    revision=payloads[2]["source_revision_digest"],
                    sha256=payloads[2]["source_sha256"],
                )
            argv = [arg.format(**substitutions) for arg in step["argv"]]
            result = runner.invoke(app, argv)
            calls.append(
                {
                    "phase": step["phase"],
                    "argv": argv,
                    "exit_code": result.exit_code,
                    "response_bytes": len(result.output.encode()),
                }
            )
            if result.exit_code:
                failures.append(f"{step['phase']}: {result.output}")
                break
            payloads.append(json.loads(result.output))
            if len(payloads) == 3:
                if Bibliography.open(path).entries or not payloads[-1].get("diff"):
                    failures.append("Preview must show a diff without writing entries")
            if len(payloads) == 4:
                if len(project_bindings(Bibliography.open(path))) != 2:
                    failures.append("Apply must persist both source bindings")
                if json.dumps(api.items, sort_keys=True) != original:
                    failures.append("Selection changed source items")
    if len(payloads) == 5:
        if {e.fields["title"] for e in Bibliography.open(path).entries.values()} != {
            "Revised Principia",
            "Revised experiment",
        }:
            failures.append("One refresh must update every bound entry")
    else:
        failures.append("The five-call workflow did not finish")
    if any(r.method != "GET" for r in api.calls):
        failures.append("Source reads must use GET only")
    return {
        "task": task["id"],
        "kind": "reference-solution acceptance",
        "passed": not failures,
        "failed_checks": failures,
        "calls": calls,
        "setup_calls": sum(c["phase"] == "setup" for c in calls),
        "refresh_calls": sum(c["phase"] == "refresh" for c in calls),
        "response_bytes": sum(c["response_bytes"] for c in calls),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pynakes-zotero-eval-") as directory:
        report = measure(Path(directory))
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
