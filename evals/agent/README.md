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
  `prepare` and `collect` run a blind evaluation; `score` scores one transcript.

Initial tasks cover the cases the roadmap names first:

| Task | Category | What a correct run shows |
| --- | --- | --- |
| `ambiguous-reference` | ambiguous references | Names both volumes and says the request is ambiguous |
| `duplicate-conflict` | duplicate conflicts | Surfaces `DuplicateCitationKey` instead of editing either entry |
| `concurrent-edit` | concurrent edits | Stops on `ExternalModification` instead of overwriting another tool's change |
| `bounded-context` | bounded reads | Pages the saved query to completion, reads each key once, reports truncation |
| `coauthor-interpretation` | co-authorship analysis | Distinguishes count scopes, identity uncertainty and exclusions with citation evidence |

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

## Running a blind evaluation

Evaluate an installed wheel, not the source tree, so the run tests what ships:

```bash
python -m venv /tmp/eval-env && /tmp/eval-env/bin/pip install dist/pynakes-X.Y.Z-py3-none-any.whl
/tmp/eval-env/bin/python scripts/agent_eval.py measure --out baseline.json
python scripts/agent_eval.py prepare /tmp/eval-run --python /tmp/eval-env/bin/python
```

`prepare` gives each task a directory outside the repository with a fresh copy
of its fixture, a `bin/pynakes` wrapper around the engine under test, a
`brief.md`, and an empty `review.json`. The wrapper records every call in full
(argv, exit status, stdout, stderr) in `calls.jsonl`, and applies the task's
`mutate` steps after the first successful preview, as the reference solution
does.

Give each task's `brief.md`, verbatim and nothing else, to a fresh isolated
agent with shell access only: no parent conversation, repository or reference
solutions. The brief asks the agent to write its final answer to `answer.md`.
Run one task per agent.

Then review each answer against the recorded responses and fill `review.json`:
the keys the answer names, whether it reported ambiguity, and the number of
statements the tool responses do not support. Finally:

```bash
python scripts/agent_eval.py collect /tmp/eval-run --baseline baseline.json \
  --wheel dist/pynakes-X.Y.Z-py3-none-any.whl \
  --agent "model and client" --conditions "fresh fixture, offline, one task per agent"
```

`collect` writes each `<task>.transcript.json` (calls, the verbatim answer, the
reviewer's annotations, the library hash and the wheel hash) and
`<task>.score.json`, and a `summary.md` table. Copy those with the baseline and
a short README of the conditions into `runs/<date>-<agent>-<version>/`.

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

The [v0.8 review](REVIEW-0.8.md) records the historical runs’ limitations and
the semantic review required for the co-authorship task. New transcripts must
retain raw tool responses and verbatim final answers for independent review.
