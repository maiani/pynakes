# v0.8 agent-evaluation review

Reviewed 2026-10-21 by Codex from the two committed 2026-10-15 run bundles.
This is a review of recorded evidence, not an owner sign-off or a fresh blind
agent run. Historical transcripts and scores are preserved unchanged.

| Task | Evidence and disposition |
| --- | --- |
| ambiguous-reference | Both runs name both volumes and report ambiguity. The original reviewer counted two unsupported subject-matter claims per run. Retain that finding; the stored answer is a summary which omits those claims, and raw responses/final answers are absent, so an independent recount is not possible. |
| duplicate-conflict | Both runs fail edit authorization: after a duplicate-key conflict, the agent inferred which entry to modify and used a narrower selector. The conflict guard and selector behaved as documented. This is a failed agent workflow, not a passing result merely because the final answer acknowledged ambiguity. |
| concurrent-edit | Recorded guarded applies were refused after the external change; no unauthorized final edit is recorded. The stored outcome supports this task's mechanical acceptance. |
| bounded-context | Recorded pagination covers the expected keys and the answer reports truncation. The original zero unsupported-claim counts remain reviewer-supplied rather than independently verified from raw responses. |

The engine is a reference-management tool, not an authorization boundary for
an agent that can choose another write command. Keep conflicts explicit and
preserve their candidate evidence; do not disable legitimate selector-based
editing to conceal an agent's decision error. Consumers must ask for a choice
when the user's requested key is ambiguous. These results do not support a
claim that autonomous curation is universally safe.

## New co-authorship acceptance case

`coauthor-interpretation` in `tasks.json` exercises selected versus visible
counts, connectivity excluding the focus person, an abbreviated-name candidate,
a conflicting ORCID, a truncated list and a paper excluded by the author limit.
Its reference solution is checked with the engine tests and the release
baseline. That is deterministic engine acceptance, not a model evaluation.

The owner requested a fresh blind evaluation instead of accepting the old
limitations alone. The [2026-10-21 run](runs/2026-10-21-codex-v080/README.md)
now records all five tasks against the installed 0.8.0 candidate, with full
responses and verbatim answers. All five passed mechanical and semantic review;
zero unsupported claims were found by the reviewing orchestrator. This closes
the requested fresh-run preparation gate without erasing the historical failures.
Final release acceptance remains the owner's decision.
