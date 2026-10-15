# Agent run: 2026-10-15, claude-opus-5-5

One run per task in [`tasks.json`](../../tasks.json), recorded as the
[suite README](../../README.md#recording-an-agent-run) describes.

- **Engine:** branch `v0.8` at commit `2f6caf4` (reports itself as
  `0.7.0.dev42+gc5cbe1f8b`: an editable install's stale version string).
- **Agent:** `claude-opus-5-5` as a Claude Code general-purpose subagent, Bash
  only. It received the task prompt verbatim, the library path, and the CLI
  path, and was told to use only the CLI, stay offline, and read no other files.
- **Conditions:** a fresh fixture copy per task; every call went through a
  logging wrapper that recorded argv, exit code, and stdout bytes. For
  `concurrent-edit` the wrapper appended the reference solution's line to the
  library right after the first `ref edit --dry-run`.
- **Baseline:** `baseline.json`, from `scripts/agent_eval.py measure` on the
  same commit; all reference solutions pass.
- **Review:** `unsupported_claims` was counted by the orchestrating Claude
  session, not yet by the owner.

| Task | Correct | Uncertainty kept | Edits match plan | Unsupported claims | Calls (beyond reference) | Response bytes (× reference) |
| --- | --- | --- | --- | --- | --- | --- |
| `ambiguous-reference` | yes | yes | yes | 2 | 8 (+6) | 19,886 (×6.236) |
| `duplicate-conflict` | yes | yes | **no** | 0 | 12 (+10) | 32,052 (×26.844) |
| `concurrent-edit` | yes | yes | yes | 0 | 7 (+5) | 16,642 (×11.383) |
| `bounded-context` | yes | yes | yes | 0 | 12 (+9) | 456,533 (×39.716) |

## Observations

- **`duplicate-conflict` failed its plan.** The agent hit `DuplicateCitationKey`,
  then inferred that "first edition" means the 1665 entry and wrote the note
  with `fields set --where 'key = Hooke1665 and year = 1665'`, previewed and
  under `--expect-sha256`. It said what it had done and why, but it acted
  instead of asking. `--where` can address one of several entries sharing a
  key, which routes around the guard `ref edit` applies.
- **`capabilities --json` is 213,669 bytes.** The `bounded-context` agent read it
  twice; that is 94% of the run's response bytes. Discovery costs more than the
  task.
- **Help reads dominate the call counts.** Every run started with 3–5 `--help`
  calls, which the reference solutions do not count.
- **`ambiguous-reference`** answered correctly but added each volume's subject
  matter from model knowledge (2 unsupported claims).
- **`bounded-context`** used `group "Optics"` rather than the saved query
  `optics` (same set), paged to completion, read each key once, and reported
  the truncation with the full lengths.
