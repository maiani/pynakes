# pynakes development plan

This plan is organized around the project [VISION.md](VISION.md): pynakes is a
**standalone bib-file engine** — a Python library + CLI that is complete and
valuable on its own. The lifelong bibliography-management system (**BiMaS**,
working name) is a **separate, downstream project built on top of pynakes** and
is explicitly *not* in this plan.

## Status

**v0.1 is shipped, and we are past it.** Beyond the original v0.1 scope, the tree
now also has: `convert`, `journals`, `files check`, structured JabRef `metadata`,
and — newly — the **`Volume` engine** with the CLI dogfooding it (Phase 5). The
package is **PyPI-release-ready** (clean metadata, `py.typed`, `twine check`
passing, fresh-venv install verified). 407 tests pass; coverage ≥90%; ruff clean.

### Shipped capabilities (standalone pynakes)

- Custom round-trip BibTeX/BibLaTeX parser + writer; atomic, re-parse-validated
  writes with `.bak` backups; surgical minimal-diff editing (`editing.py`).
- `inspect`, `lint`, `groups`, `keys` (generate/check/repair/rename + JabRef key
  patterns), `fields` (rename/move/append/clear/protect-title with `--where`).
- `convert` (BibTeX ↔ BibLaTeX), `journals` (abbreviate/expand/check),
  `files check` (linked-file validation), `metadata` (structured JabRef blocks).
- `doi import`, `used` (cited/unused/missing + tag + subset export), `normalize`.
- `capabilities` (machine-readable agent contract); unified JSON envelope and
  exit codes (0 ok / 1 error / 2 conflict).
- **`engine.Volume`**: the in-process load → stage → preview → commit lifecycle
  with external-change detection; the CLI is a thin `Volume` consumer.

For the per-phase v0.1 history see the git log and [CHANGELOG.md](CHANGELOG.md).

## Guiding principles (carried into all future work)

Invariants from [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md):

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve, don't impose.**
7. **Determinism** — no time/randomness/ordering in core logic; network is
   opt-in and isolated.

## Scope boundary: what "complete standalone pynakes" means

Everything below is **pure bib-file work** — no UI, capture, PDF, reading, or
sync. The goal is a standalone engine whose public API is stable enough that
BiMaS (and any consumer: CLI, MCP, app) can build on it without reaching inside.
**No BiMaS work begins until this roadmap is done and the engine API is pinned.**

---

## Phase 5: Engine API — `Volume` — ✅ done

**Goal**: lift the load → stage → preview → commit lifecycle into a reusable
in-process object and dogfood the CLI on it. See [ENGINE_API.md](ENGINE_API.md).

**Decided & implemented: stateless core + thin reconciled handle.** The file is
truth; `Volume`'s buffer is derived and reconciled on `commit`; VSCode-style
reload semantics (clean → reload, dirty → conflict, save-on-changed →
`ExternalModificationError`).

- [x] `engine.py` with `Volume` (`open`/`from_text`/`from_library`), read-only
      views, staged edits delegating to the operation modules, `preview`/`diff`.
- [x] `commit(force=)` (atomic + `.bak` + re-parse validate), `reset`, `reload`,
      fingerprint + `externally_changed` + `ExternalModificationError`.
- [x] `cli.py` modifying commands rewritten as `Volume` consumers; full suite
      passes unchanged (no behavior/envelope change). `tests/test_engine.py`.
- [x] **Decided: no `Volume.watch(callback)` in core.** A filesystem watcher is
      a non-deterministic background thread and a UX concern, so the *push* loop
      is the consumer's job; the pull primitives (`externally_changed`,
      `reload`, `is_dirty`) already enable VSCode-style live reload from the
      consumer's own event loop. A push helper, if ever needed, ships as an
      opt-in extra (`pynakes[watch]`) built when BiMaS needs it.

## Phase 6: Deduplication & merge

**Goal**: detect and safely merge duplicate works within a library — the major
missing standalone operation.

- [ ] `dedupe.py`: stable work identity (DOI / arXiv / other IDs first, then
      fuzzy title+author+year), surfaced as duplicate clusters.
- [ ] Conservative merge: prefer richer values, never silently discard data.
- [ ] **Report conflicts (exit 2) rather than guessing** when ambiguous.
- [ ] CLI: `pynakes dedupe check|merge` (`--dry-run`/`--diff`/`--json`).

## Phase 7: Engine API — `Library` (collection)

**Goal**: extend the engine from one file to a collection (a directory / git
repo of volumes) — the structure the lifelong corpus needs.

- [ ] `Library.open(dir)`; `volumes()`, `volume(path)`.
- [ ] Cross-file `search`, `find_key`, cross-file dedup (reuses Phase 6 identity).
- [ ] **Derived index** (e.g. SQLite FTS), rebuildable from the volumes — never a
      competing source of truth.
- [ ] Projections: formalize subset export (today's `used --out`) as a
      first-class "view of the collection".

## Phase 8: Interoperability

**Goal**: stop being a BibTeX island while keeping fidelity.

- [ ] CSL-JSON import/export (Zotero / pandoc / citeproc lingua franca).
- [ ] RIS import/export.
- [ ] First-class stable identifiers (DOI / arXiv / OpenAlex / ORCID) shared by
      dedup, import, and verify.

## Phase 9 (candidate): Integrity & enrichment

**Goal**: catch fabricated/incorrect references, fill gaps, and flag preprints
that now have a published version — high-value in the LLM era.
**Network-discipline decision required**: extends network beyond `doi import`;
calls must be opt-in and cached, tests stubbed against fixtures.

- [ ] `verify`: check entries against authoritative metadata (DOI resolves,
      title/author/year match, retraction flags); report discrepancies.
- [ ] `published` (preprint → published): detect preprint entries (arXiv /
      bioRxiv / medRxiv / SSRN eprints, preprint-registrant DOIs) and check
      whether a peer-reviewed version now exists (arXiv `journal-ref`/DOI,
      Crossref / OpenAlex version relations). Report it, and optionally upgrade
      the entry (→ `@article` with journal/volume/pages/doi/year) while
      preserving the preprint pointer. Conservative; conflict on ambiguity.
      Reuses the stable-identity machinery (Phase 6/8).
- [ ] `enrich`: fill missing DOIs/dates/identifiers conservatively, reviewably.
- [ ] CI-friendly `verify --strict` (gate a paper repo on citation integrity).

## Phase 10: Agent interface & API pinning — the BiMaS handoff

**Goal**: make the engine first-class for agents and freeze the contract BiMaS
(and ChatGPT/Claude) build on. **This is also the top adoption lever** (see
Distribution): an MCP server is how agents autonomously call pynakes.

- [ ] `pynakes-mcp`: expose operations as MCP tools over the `Volume`/`Library`
      engine (`open → op → dry_run ? diff() : commit()`), dry-run by default,
      write opt-in. Reuses `capabilities.py`.
- [ ] Pin and document the public Python API (`Volume`, `Library`, operations)
      as the stable engine contract in `docs/`.
- [ ] Version bump signaling API stability.

**Gate**: when this is met, pynakes is stable and complete, and BiMaS may begin —
not before.

---

## Distribution & traction (near-term, parallel track)

Impact does **not** come from publishing on GitHub alone; LLMs don't discover
tools by crawling repos. The realistic order (traction first, citability later):

- [ ] **PyPI release.** Move zero, and a prerequisite for everything. Packaging
      is ready; remaining: set the real repo URL in `[project.urls]` (currently a
      placeholder), decide the release version (suggest **0.2.0** to reflect the
      post-v0.1 surface), then `python -m build && twine upload`.
- [ ] **A 30-second demo** (asciinema/GIF): "messy `.bib` → clean `.bib` with a
      reviewable diff", and Claude cleaning a bibliography via pynakes. Shows the
      safety/diff story better than prose.
- [ ] **MCP server as the shareable hook** (Phase 10): both the autonomous-use
      mechanism *and* novel enough right now to attract the agent-tooling crowd.
- [ ] **Post where the pain lives**: r/LaTeX, JabRef community, LaTeX/academia
      corners of Bluesky/Mastodon, a Show HN once the demo is crisp. Ten of the
      right users beats a thousand impressions.
- [ ] **Deferred to after traction (Stage 2)**: Zenodo DOI (citable), then JOSS —
      JOSS explicitly requires demonstrated use, so it is downstream of adoption.

Keep the agent-trust invariants sacred (deterministic, dry-run, JSON, no
corruption): they're why an agent that meets pynakes once keeps using it.

## Out of scope (downstream / BiMaS)

In a **separate** project, only after the roadmap: capture (web/DOI/PDF),
reading/annotation, GUI, sync orchestration, and the lifelong-corpus workflow
(inbox → canonical → projections, provenance as a product feature). Permanently
out of scope for pynakes: a database of record, cloud service, PDF library,
arbitrary shell execution.

## Risks & mitigations

- **Dedup/merge correctness** → identity by stable IDs first; report conflicts
  instead of guessing; minimal-diff merges only.
- **Index drift** (Phase 7) → strictly derived and rebuildable; files are truth.
- **Network determinism** (Phase 9) → opt-in + cached + fixture-stubbed tests;
  decide explicitly before extending beyond `doi import`.
- **Scope creep into BiMaS** → the vision informs API shape only; no application
  concerns enter pynakes.

## Definition of done (standalone pynakes)

- [x] `Volume` engine implemented and the CLI dogfoods it.
- [ ] `Library` (collection) engine implemented.
- [ ] Deduplication/merge shipped.
- [ ] Interop (CSL-JSON/RIS) shipped.
- [ ] Integrity/enrichment shipped or explicitly deferred with a recorded decision.
- [ ] MCP interface shipped; public API documented and pinned.
- [ ] Published to PyPI.
- [ ] Invariants intact; coverage ≥90%; `ruff` clean.

When this is met, pynakes is stable and complete, and BiMaS development may start
on top of the pinned engine API.
