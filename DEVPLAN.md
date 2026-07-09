# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Any application built on top of it (capture, reading,
a UI, sync) is a **separate, downstream project** and is explicitly not in this
plan.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Current state (v0.5 alpha — shipped)

v0.5 is the first public alpha release. The single-file engine is feature-complete
for this release; input conformance is verified against the TeX Live 2026 baseline
(BibTeX 0.99d, BibLaTeX 3.21, Biber 2.21). Until v1.0, pynakes does **not**
guarantee backward compatibility for the Python API, CLI syntax, or JSON envelopes.

Key shipped capabilities:
- **Parser/writer**: byte-for-byte round-trip fidelity; atomic, re-parse-validated
  writes; surgical minimal-diff editing. Handles all BibTeX/BibLaTeX constructs
  including `crossref`/`xdata`/`xref`/sets inheritance.
- **`engine.Bibliography`**: load → stage → preview/diff → commit lifecycle;
  external-change detection.
- **Operations**: `init`, `inspect`, `lint`, `groups`, `keys`, `fields`,
  `convert`, `normalize`, `ref add`/`ref import`, `search`, `tex scan`,
  `dedupe`, `verify`/`enrich`, `asset check`/`fetch`, `remove`, `metadata
  list`/`set`, `corpus combine`/`split`/`batch`.
- **Pinax corpus mode**: `FileStore`, arXiv download, provenance manifest,
  open-access PDFs, DOI→arXiv backfill, material merge on dedupe, coordinated
  key edits, pinax-aware combine/split.
- **JabRef v5.15 interop**: metadata vocabulary near-full (16 exact + 3 prefix
  keys recognized; rare/missing keys preserved verbatim); `saveActions` formatter
  suite partial (15 of ~24 formatters — missing `clear`, `escapeUnderscores`,
  `escapeAmpersands`, `cleanup_url`, `remove_braces`, `short_doi`,
  `unprotect_terms`, `minify_name_list`, and `normalize_names`/`clean_up_doi`
  live off-registry); key patterns partial (10 common markers + 5 modifiers,
  missing `authorLast`, `authorN`, `authIniN`, `authorIni`, `auth.easy` chain,
  and formatters-as-modifiers); group management at full parity (all four group
  types with native `group-tree` metadata and dynamic expression evaluation);
  `saveOrderConfig` sort implemented but missing crossref-parent hoisting.
- **Agent-native surface**: structured JSON envelope + exit codes, `--dry-run`/
  `--diff`/`--json`, structured `plan` objects, `capabilities`, multi-file
  `--strict` gates, `.pre-commit-hooks.yaml`, shell completion.
- **Parser conformance**: versioned corpus pinned to TeX Live 2026; differential
  tests against BibTeX 0.99d and Biber 2.21; property-based tests (Hypothesis).
- **Quality**: ~1087 tests, coverage ≥90%, `ruff` clean, docs site builds.

---

## Remaining v0.5 polish (pre-ship)

All of these block the v0.5.0 tag. They are small, well-scoped items that
close gaps identified during pre-release review.

- [x] **Group tree CLI — `groups list-entries` with descendant propagation.**
      Wired as `groups list-entries <name>` with descendant propagation as
      default (`--strict` opt-in for exact-match only). Dynamic groups
      (KeywordGroup/SearchGroup) are evaluated at query time.
      (`cli_commands/groups.py`)
- [x] **`metadata remove` command.** `metadata remove <key> [file]` deletes a
      single `pynakes-meta` or `jabref-meta` entry, auto-detecting the target
      namespace or accepting an explicit `--namespace`. Reports which namespace
      the key was removed from.
      (`cli_commands/metadata.py`)
- [x] **`init --json` is fully non-interactive.** The `--json` flag is marked
      `is_eager=True` to ensure error output is always JSON when requested.
      All configurable options have a non-interactive CLI path.
      (`cli_commands/init.py`)
- [ ] **`verify`/`enrich` help and docs clarify the split.** `verify` checks
      entries against authoritative online sources without modifying the file.
      `enrich` updates entries from those sources. Both accept `--published`
      and `--online` but with different intent. Ensure `--help` and the LLM
      integration guide make this distinction explicit.
- [ ] **Final changelog and version bump.** Tag v0.5.0.
- [ ] **JabRef parity audit correction.** The status reporting in DEVPLAN.md and
      `capabilities` should reflect the actual state — `saveActions` formatters
      at 15/24, key patterns at partial, groups at full — not claim "full
      parity" where gaps exist.

**Done when**: all items checked off; `pytest && ruff` green; CHANGELOG
updated; version bumped to 0.5.0.

---

## Road to 1.0

### v0.6 — Generalization and consolidation

Generalize import paths beyond DOI/arXiv and consolidate the engine's
cross-cutting patterns.

- **New import paths**: PubMed PMID/PMCID, ISBN, SSRN ID, NBER ID, generalized
  journal-URL resolver table covering common publisher patterns.
- **Generalized URL import**: `ref import <url>` auto-detects identifier type
  from any supported publisher/catalog URL (DOI, arXiv, PubMed, SSRN, NBER,
  ISBN, nature.com, journals.aps.org, plus the new Elsevier/Springer/Wiley/PLOS
  patterns) and resolves it through the appropriate provider, normalizing the
  result into a uniform metadata dict.
- **Richer `search`**: fuzzy title matching, date-range filtering,
  "entries missing field X" queries, search-result JSON with match
  explanations — covers common agent facepalms without writing ad-hoc grep.
- **Cross-cutting consolidation**: unify interface patterns, reduce duplication
  across import, identity, and metadata pathways.

**Done when**: broader import paths and improved `search` implemented, tested,
and documented; `pytest && ruff` green; CHANGELOG updated; version bumped to 0.6.0.

---

### v0.7 — Shared identity

Promote the DOI / arXiv / OpenAlex / ORCID / title machinery (currently spread
across `dedupe`, `verify`, and `add`) into one explicit, tested primitive. This
is the foundation for dedup, the `Library`, Catalogue, and projection
reconciliation — everything keys off a single notion of "the same work".

**Must include**:
- **Identity primitive**: a `Work` type that unifies identifier resolution
  (DOI, arXiv, OpenAlex ID, ORCID) with metadata fingerprinting (title hashing,
  author normalization) so any consumer answers "is this the same work?" through
  one tested path.
- **Refactor consumers**: `dedupe` uses the primitive for its similarity
  heuristic; `verify`/`enrich` use it for online-lookup routing; `ref import`
  uses it to reconcile metadata from multiple sources.

**Done when**: identity primitive shipped with tests and docs; consumers in
`dedupe`, `verify`, and `add` refactored to use it; `pytest && ruff` green;
CHANGELOG updated; version bumped to 0.7.0.

---

### v0.8 — Multi-bib setup, Library, Catalogue, and MCP server

- **`Library` (corpus)**: `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the identity
  primitive from v0.7. A Library holds many `.bib` files (many pinakes).
- **`Catalogue` (index)**: a derived, rebuildable search index (e.g. SQLite FTS)
  over the Library; strictly derived, never a competing source of truth.
- **MCP server**: a thin [Model Context Protocol](https://modelcontextprotocol.io)
  companion on the pinned pynakes API, allowing agents to interrogate a personal
  corpus conversationally — "find papers by X on topic Y", "which entries are
  missing PDFs", etc. Query-only layer over the `Library`/`Catalogue`.
- **Agent surface polish**:
  - **Plan-and-approve workflow**: allow composing multi-step operations
    (e.g. "dedupe these → normalize → fetch PDFs") into a single structured
    `plan` that the user approves once.
  - **Post-hoc change summary**: every mutating command emits a human-readable
    and machine-parseable summary alongside the diff — "3 keys renamed,
    12 fields normalized, 2 entries enriched" — so an agent can report what
    happened without re-parsing the diff.
- **`Catalogue`-backed rich query CLI**: `search` gains full-text and
  field-scoped queries against the index, not just raw entry iteration.

**Done when**: `Library` and `Catalogue` shipped with tests and docs; MCP
server published as a companion package; agent-plan and change-summary
features shipped; `pytest && ruff` green; CHANGELOG updated; version bumped
to 0.8.0.

---

### v0.9 — Testing release

- **First stable pre-release**: bump to **0.9.0**, sync `capabilities.VERSION`,
  `twine upload`, tag `v0.9.0`, point the pre-commit hook `rev:` in docs at it.
  Gather feedback before committing to the 1.0 API.
- A 30-second demo (asciinema/GIF): "messy `.bib` → clean `.bib` with a
  reviewable diff", and an agent cleaning a bibliography via pynakes.
- Lead the README/launch with the agent-tool + reviewable-diff story.
- Zenodo DOI and JOSS submission deferred to after traction.

**Done when**: 0.9.0 is on PyPI with a demo and the launch posts are out.

---

### v1.0 — Launch

- Stable API, semver promise.
- All eight guiding principles intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Guiding principles (non-negotiable)

Invariants from [docs/guides/architecture.md](docs/guides/architecture.md) and
[CLAUDE.md](CLAUDE.md):

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve, don't impose.**
7. **Determinism** — no time/randomness/ordering in core logic; network is
   opt-in and isolated.

**What "pynakes 1.0" is**

**A polished, deterministic, single-file maintenance engine — agent-safe,
losslessly JabRef-compatible — with a pinned public API, released on PyPI.** The
unit of work is one `Bibliography` (one `.bib`). 1.0 means: it does single-file
maintenance excellently, covers the JabRef bib-file feature set, promises API
stability (semver), and is installable. The multi-bib `Library`, `Catalogue`,
and MCP server ship in v0.8 as optional companions — they extend reach without
changing the core.

**Beyond 1.0** (deferred to [v2.0](#v20--beyond-10)): projections as `Library`
views with reconciliation, additional interchange formats,
content-intelligence layers, and the Bimas GUI.

## v2.0 — Beyond 1.0

These stay **in pynakes** — pure bib-file mechanisms, no application scope —
but together they are the cross-file corpus layer a downstream application builds
directly on.

- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation.
- **Additional interchange formats** — any import/export formats beyond the
  existing CSL-JSON/RIS/MODS/EndNote quartet, building on `pynakes.interchange`.
- **Content-intelligence layers** — full-text extraction, content search,
  RAG/embeddings, and rich agent notes/memory, as an opt-in extra never on the
  deterministic write path.
- **Thin `pynakes` Bimas GUI** — a lightweight desktop GUI built on the pinned
  API, reading/writing `.bib` files through the library, not the CLI.

**Done when**: 2.0.0 is on PyPI with all of the above shipped and documented.

---

## Risks & mitigations

- **`saveActions` format drift** → JabRef is reworking the format toward embedded
  JSON. Parse tolerantly (regex over `field[formatter]`), keep the pinned JabRef
  v5.15 baseline, and audit v6 only once a stable v6 release ships.
- **`saveActions` formatter suite incomplete** → 9 of ~24 JabRef v5.15 formatters
  are not yet implemented in `FIELD_FORMATTERS`. Key-pattern markers are also
  partial (missing `authorLast`, `authorN`, `authIniN`, `authorIni`, `auth.easy`
  chain, and formatters-as-modifiers). Gap tracked here; fill incrementally.
- **`saveOrderConfig` sort parity (partial)** → `normalize` honors JabRef's
  order type and `field;descending` criteria, but does **not** yet replicate
  JabRef's rule of hoisting `crossref`-referencing entries ahead of their
  parents (a BibTeX 0.99 processing requirement). A library JabRef would save
  with parents reordered can therefore differ in entry order. Deferred until a
  crossref-aware pass lands; track here rather than claiming full parity.
- **Scope creep** → no application concerns enter the pynakes core. GUIs,
  content-intelligence, and MCP servers ship as optional companions or separate
  releases (v0.8, v2.0).

## Quality gate (cross-cutting, every PR)

- [ ] `pytest && ruff check src tests && ruff format --check src tests` green.
- [ ] Coverage stays ≥90%; new behavior has tests and a `CHANGELOG.md` entry.
- [ ] All eight guiding principles intact; `capabilities`, README, and this plan
      stay honest (no stub described as shipped).

## Definition of done — 1.0

- [ ] Published to PyPI — first as the 0.9 testing release, then 1.0.0 with a demo.
- [ ] All guiding principles intact; coverage ≥90%; `ruff` clean.