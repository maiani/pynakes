# Fresh blind acceptance: v0.8.0, 2026-10-21

At the owner's request, five fresh isolated Codex agents each received only
one original task prompt, the disposable bibliography and instrumented CLI
paths, and instructions to use shell/CLI only, offline, without reading the
repository, other directories or evaluation machinery. `fork_turns=none`
withheld parent history and reference solutions. The runtime inherited the
session model; its exact backend identifier was not exposed. This is one run
per task on one runtime, not evidence of universal agent reliability.

The CLI wrapper invoked the installed 0.8.0 wheel in a fresh Python 3.12.13
environment, recorded complete stdout/stderr and exit status, and injected the
specified concurrent edit immediately after that task's first successful
preview. Other fixtures were not modified by the harness. Wrapper response
bytes are measured before any transcript formatting. Final answers are stored
verbatim. Key/ambiguity annotations and semantic review were supplied by the
orchestrator; file hashes and task scores were checked mechanically.

| Task | Calls | Response bytes | Outcome and edit plan | Unsupported claims |
| --- | --- | --- | --- | --- |
| ambiguous-reference | 2 | 5,288 | pass | 0 |
| bounded-context | 5 | 15,315 | pass | 0 |
| coauthor-interpretation | 4 | 11,939 | pass | 0 |
| concurrent-edit | 4 | 6,612 | pass | 0 |
| duplicate-conflict | 2 | 4,320 | pass | 0 |

All five satisfy their task contracts. The duplicate-key agent asked for the
entry choice without writing. The concurrent-edit agent stopped on the guarded
write conflict. Bounded reads returned 5/5/2 entries with 300-character limits
and disclosed truncation. The co-author answer explained selection-wide versus
visible counts, components excluding focus, the initials variant, conflicting
ORCIDs, truncated authors and the excluded large paper, with supporting keys.

The orchestrator reviewed the complete answers against raw responses and found
zero unsupported claims. This is fresh evidence, not a reclassification of the
historical failures or a claim that the owner personally audited every response.
The historical 2026-10-15 runs remain unchanged. Run conditions and model differ,
so call/byte totals are not a controlled model-to-model performance comparison.

Each transcript records the exact evaluated wheel hash. The reference baseline
was rerun using that installed wheel. Artifacts remain local under
`.cache/release-0.8.0/evaluated-dist/`; subsequent release-document updates do
not change the evaluated engine implementation.
