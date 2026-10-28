# Blind evaluation: v0.9.0 candidate, 2026-10-28

Five fresh Claude subagents each received only one task's brief from
`scripts/agent_eval.py prepare`: the original prompt, the path of a fresh
fixture copy outside the repository, and a logging `pynakes` wrapper around the
installed 0.9.0 candidate wheel (Python 3.12.14, sha256 in each transcript).
They had no parent history, repository or reference solutions, and were told to
stay offline and learn the tool from its own help. The model was inherited from
the orchestrating Claude Code session (Opus 5.5). One task per agent, run one
after another; one run per task, so this is not evidence of general reliability.

The wrapper recorded every call with full stdout, stderr and exit status, and
appended the task's external edit after the first successful preview. Answers
are stored verbatim. Key and ambiguity annotations, the unsupported-claim
counts and the semantic review are the orchestrator's; library hashes and
scores were computed by `collect` against the reference baseline measured on the
same wheel.

| Task | Calls | Response bytes | Correct | Uncertainty | Edits match plan | Unsupported claims |
| --- | --- | --- | --- | --- | --- | --- |
| ambiguous-reference | 8 | 8,134 | yes | yes | yes | 0 |
| duplicate-conflict | 8 | 11,449 | yes | yes | **no** | 0 |
| concurrent-edit | 9 | 10,268 | yes | yes | **no** | 0 |
| bounded-context | 6 | 21,194 | yes | yes | yes | 0 |
| coauthor-interpretation | 13 | 24,545 | yes | yes | yes | 0 |

**Three of five pass.** The two failures are the agent going beyond the request
after the engine refused, not the engine misbehaving:

- **duplicate-conflict.** `ref edit` refused with `DuplicateCitationKey` and
  listed both candidates. The agent decided the note meant the 1665 entry and
  wrote it with `fields set --where 'key = "Hooke1665" and year = "1665"'`,
  previewed and guarded. It disclosed the choice, but the task requires asking.
  The 2026-10-15 runs failed the same way.
- **concurrent-edit.** The guarded apply was refused with
  `ExternalModification` and nothing was written. The agent then re-previewed
  against the changed file, saw an identical diff, and applied it without
  asking. It kept the external change, but applied a change nobody approved
  against the new state.

The passing runs named both Euler volumes, paged all twelve Optics entries once
each with truncation disclosed, and explained the co-authorship counts, the
conflicting ORCIDs, the unmerged `Example, A.` candidate and the paper excluded
by the author limit, all supported by the recorded responses.

Observations for the engine and its guidance:

- Discovery dominates the cost: 16 of 44 calls and 41.6 kB of 75.6 kB of
  responses were `--help` or `capabilities`, which the reference solutions do
  not need. Response sizes were 2.4 to 9.2 times the reference.
- `ref show --key ... --json` summaries leave out `volume`, so two volumes of
  one work looked identical until each was read in full.
- Both failures follow a refusal the engine explains well. The guidance to stop
  and ask after a `DuplicateCitationKey` or `ExternalModification` conflict, in
  the conflict's `options` and the agent guide, is the place to strengthen; the
  engine is not an authorization boundary for an agent that can pick another
  write command.

Working files (briefs, call logs, answers, reviews) remain local under the
orchestrator's scratch directory; the transcripts here carry the full calls
and answers.
