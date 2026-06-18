# pynakes development plan

This plan is organized around the project [VISION.md](VISION.md): pynakes is a
**standalone bib-file engine** — a Python library + CLI that is complete and
valuable on its own. The lifelong bibliography-management system (**BiMaS**,
working name) is a **separate, downstream project built on top of pynakes** and
is explicitly *not* in this plan.

## Status

**v0.1 (Phases 1–4) is shipped.** The standalone maintenance workflow is
complete and stable: a round-trip-faithful parser/writer, atomic validated I/O,
and the full operation surface, all with `--dry-run` / `--diff` / `--json`, a
stable JSON envelope + exit-code contract, and a comprehensive test suite
(property-based, stress, error-recovery, end-to-end; coverage ≥90%).

Several items originally slated as "after v0.1" also landed early and are
shipped: DOI import (`doi import`), citation analysis (`used`), the `normalize`
routine, title-capitalization protection, linked-file validation
(`files check`), and structured JabRef metadata (`metadata list/set`).

For the per-phase v0.1 history see the git log and [CHANGELOG.md](CHANGELOG.md).

### Shipped capabilities (standalone pynakes)

- Custom round-trip BibTeX/BibLaTeX parser + writer; atomic, re-parse-validated
  writes with `.bak` backups; surgical minimal-diff editing (`editing.py`).
- `inspect`, `lint`, `groups`, `keys` (generate/check/repair + JabRef key
  patterns), `fields` (rename/move/append/clear/protect-title with `--where`).
- `convert` (BibTeX ↔ BibLaTeX), `journals` (abbreviate/expand/check).
- `doi import`, `used` (cited/unused/missing + tag + subset export),
  `normalize`, `files check`, `metadata` (structured JabRef blocks).
- `capabilities` (machine-readable agent contract); unified JSON envelope and
  exit codes (0 ok / 1 error / 2 conflict).

## Guiding principles (carried into all future work)

These are the invariants from [ARCHITECTURE.md](ARCHITECTURE.md) and
[CLAUDE.md](CLAUDE.md). Future work preserves them:

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve, don't impose.**
7. **Determinism** — no time/randomness/ordering in core logic; network calls
   are opt-in and isolated.

## Scope boundary: what "complete standalone pynakes" means

Everything below is **pure bib-file work** — no UI, capture, PDF, reading, or
sync. The goal is a standalone engine whose public API is stable enough that
BiMaS (and any other consumer: CLI, MCP, app) can build on it without reaching
inside. **No BiMaS work begins until this roadmap is done and the engine API is
pinned.**

---

## Phase 5: Engine API — `Volume`

**Goal**: lift the load → stage → preview → commit lifecycle out of `cli.py`
into a reusable, in-process object, and dogfood the CLI on it. See
[ENGINE_API.md](ENGINE_API.md).

### Tasks
- [ ] Add `engine.py` with `Volume` (binds one `.bib` file): `open`, read-only
      views (`entries`, `lint`, `duplicate_keys`, `is_dirty`), staged edits
      delegating to existing operation modules, `diff`/`preview`,
      `commit`/`reset`/`reload`.
- [ ] Capture pristine text + per-entry snapshot at `open`; derive diff/commit
      via `editing.splice_into_text` with `write_bib` fallback.
- [ ] Fingerprint (size+mtime → content hash) and `ExternalModificationError`
      on `commit` when the file changed underneath.
- [ ] Rewrite `cli.py` modifying commands as `Volume` consumers (the test suite
      is the regression guard; behavior unchanged).
- [ ] Optional `Volume.watch(callback)` for file-change notification.

**Success**: the CLI is a thin `Volume` consumer; all existing tests pass
unchanged; no behavior or envelope changes.

## Phase 6: Deduplication & merge

**Goal**: detect and safely merge duplicate works within a library — the major
missing standalone operation.

### Tasks
- [ ] `dedupe.py`: stable work identity (DOI / arXiv / other IDs first, then
      fuzzy title+author+year), surfaced as duplicate clusters.
- [ ] Merge strategy that combines fields conservatively, preferring richer
      values and never silently discarding data.
- [ ] **Report conflicts (exit 2) rather than guessing** when a merge is
      ambiguous; offer resolution options.
- [ ] CLI: `pynakes dedupe check|merge` with `--dry-run`/`--diff`/`--json`.

**Success**: confident duplicates merge with a minimal diff; ambiguous cases are
reported, never auto-resolved; no data loss.

## Phase 7: Engine API — `Library` (collection)

**Goal**: extend the engine from one file to a collection (a directory / git
repo of volumes) — the structure the lifelong corpus needs.

### Tasks
- [ ] `Library.open(dir)` over a tree of `.bib` files; `volumes()`,
      `volume(path)`.
- [ ] Cross-file operations: global `search`, `find_key` (which volumes contain
      a key), cross-file dedup (reusing Phase 6 identity).
- [ ] **Derived index** (e.g. SQLite FTS) built from the volumes and rebuildable
      at any time — never a competing source of truth.
- [ ] Projections: formalize subset export (today's `used --out`) as a
      first-class "view of the collection" operation.

**Success**: cross-file queries and dedup work over a real multi-file corpus;
the index can be deleted and rebuilt with identical results.

## Phase 8: Interoperability

**Goal**: stop being a BibTeX island — bridge to the wider ecosystem while
keeping fidelity.

### Tasks
- [ ] CSL-JSON import/export (the lingua franca of Zotero, pandoc, citeproc).
- [ ] RIS import/export.
- [ ] First-class stable identifiers (DOI / arXiv / OpenAlex / ORCID) as a
      shared concept used by dedup, import, and verify.

**Success**: round-trip through CSL-JSON/RIS preserves known fields; identifiers
are recognized consistently across operations.

## Phase 9 (candidate): Integrity & enrichment

**Goal**: catch fabricated/incorrect references and fill gaps — high-value in
the LLM era. **Network discipline decision required**: this extends network
access beyond `doi import`; calls must be opt-in and cached, and tests run
against fixtures/recorded responses to preserve determinism.

### Tasks
- [ ] `verify`: check each entry against authoritative metadata (DOI resolves,
      title/author/year match, retraction flags) and report discrepancies.
- [ ] `enrich`: fill missing DOIs/dates/identifiers from Crossref/OpenAlex,
      conservatively and reviewably.
- [ ] CI-friendly `verify --strict` mode (gate a paper repo on citation
      integrity).

**Success**: hallucinated/incorrect references are flagged with evidence; all
network is opt-in, cached, and stubbed in tests; determinism preserved.

## Phase 10: Agent interface & API pinning — the BiMaS handoff

**Goal**: make the engine first-class for agents and freeze the contract BiMaS
will build on.

### Tasks
- [ ] `pynakes-mcp`: expose operations as MCP tools over the same engine
      (`open → op → dry_run ? diff() : commit()`), dry-run by default, write
      opt-in. Reuses `capabilities.py`.
- [ ] Pin and document the public Python API (`Volume`, `Library`, operation
      surface) as the stable engine contract in `docs/`.
- [ ] Version bump signaling API stability.

**Success**: an agent can drive pynakes via MCP with the same safety posture as
the CLI; the public API is documented and stable. **This gate is where BiMaS may
begin — and not before.**

---

## Out of scope (downstream / BiMaS)

Built on top of pynakes, in a **separate** project, only after the above:
capture (web/DOI/PDF), reading/annotation, GUI, sync orchestration, and the
lifelong-corpus workflow (inbox → canonical → projections, provenance as a
product feature). Also permanently out of scope for pynakes itself: a database
of record, cloud service, PDF library, arbitrary shell execution.

## Risks & mitigations

- **Engine refactor regressions** → the full v0.1 test suite guards the `Volume`
  extraction; behavior and envelope must not change.
- **Dedup/merge correctness** → identity by stable IDs first; report conflicts
  instead of guessing; minimal-diff merges only.
- **Index drift** → the index is strictly derived and rebuildable; the files
  remain the only source of truth.
- **Network determinism** (Phase 9) → opt-in + cached + fixture-stubbed tests;
  decide explicitly before extending beyond `doi import`.
- **Scope creep into BiMaS** → the vision informs API shape only; no
  application concerns enter pynakes.

## Definition of done (standalone pynakes)

- [ ] `Volume` + `Library` engine API implemented and the CLI dogfoods it.
- [ ] Deduplication/merge shipped.
- [ ] Interop (CSL-JSON/RIS) shipped.
- [ ] Integrity/enrichment shipped or explicitly deferred with a recorded
      decision.
- [ ] MCP interface shipped; public API documented and pinned.
- [ ] Invariants intact; coverage ≥90%; `ruff` clean.

When this is met, pynakes is stable and complete, and BiMaS development may
start on top of the pinned engine API.
