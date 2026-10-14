# Agent evaluation suite

Small, reproducible tasks for checking how an agent uses pynakes, kept separate
from the deterministic contract tests. A passing CLI test shows the engine
behaves as documented; it does not show that an agent calls it correctly,
keeps uncertainty visible, or stays within a read budget. This suite measures
those things.

Fixtures are invented or old, famous historical works. Nothing here comes from a
private library or a bug report.

## Contents

- `tasks.json` — one record per task: the prompt an agent receives, its
  fixture, the expected outcome, and a *reference solution* (the CLI calls a
  careful agent would make, with checks on their responses).
- `fixtures/` — the libraries the tasks run against. Each run starts from a
  fresh copy.
- `../../scripts/agent_eval.py` — `measure` runs the reference solutions;
  `score` scores a recorded agent run.

Initial tasks cover the cases the roadmap names first:

| Task | Category | What a correct run shows |
| --- | --- | --- |
| `ambiguous-reference` | ambiguous references | Names both volumes and says the request is ambiguous |
| `duplicate-conflict` | duplicate conflicts | Surfaces `DuplicateCitationKey` instead of editing either entry |
| `concurrent-edit` | concurrent edits | Stops on `ExternalModification` instead of overwriting another tool's change |
| `bounded-context` | bounded reads | Pages the saved query to completion, reads each key once, reports truncation |

Add cross-library assembly and evidence-grounded comparisons as their engine
support ships. Mock provider responses for tasks that would reach the network;
keep live-network exercises out of this suite.

## Measuring the reference solutions

```bash
python scripts/agent_eval.py measure --out baseline.json
```

For each task the report gives the call count, the bytes of every response and
their total, the failed checks, whether the expected keys were reachable (for
bounded reads: read exactly once, in order), and whether the library ended in
the expected state. It also records the engine version, Python version, and
platform. The command exits 1 when a reference solution no longer passes, which
means the engine changed under the task. `tests/test_agent_eval_suite.py` runs
the same check in the regular test suite.

## Recording an agent run

Run the agent on a fresh copy of the task's fixture with only the task's
`prompt`, then write a transcript:

```json
{
  "task": "ambiguous-reference",
  "engine_version": "0.8.0",
  "agent": {"model": "…", "client": "…", "settings": "…"},
  "conditions": "fresh fixture copy, offline, no prior context",
  "calls": [
    {"argv": ["search", "lib.bib", "Introductio", "--json"], "exit_code": 0, "response_bytes": 1830}
  ],
  "answer": {"keys": ["Euler1748a", "Euler1748b"], "reported_ambiguity": true},
  "library_sha256_after": "<sha256 of the library file after the run>",
  "review": {"unsupported_claims": 0, "notes": "…"}
}
```

`review.unsupported_claims` is filled in by the person reviewing the run: the
number of statements in the agent's answer that its tool responses did not
support. Everything else is recorded mechanically.

## Scoring

```bash
python scripts/agent_eval.py score run.json --baseline baseline.json
```

| Metric | Meaning |
| --- | --- |
| `correct` | The answer names exactly the expected keys |
| `uncertainty_preserved` | Ambiguity was reported exactly when the task requires it |
| `unsupported_claims` | Reviewer count, carried through |
| `unnecessary_calls` | Calls beyond the reference solution's count |
| `response_size_ratio` | Response bytes relative to the reference solution |
| `edits_match_plan` | The library ended in the state the task's plan allows |

Keep transcripts and scores with the engine and model versions that produced
them. Compare runs only under the same recorded conditions.
