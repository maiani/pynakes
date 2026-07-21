# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Any application built on top of it (capture, reading,
a UI, sync) is a **separate, downstream project** and is explicitly not in this
plan.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### v0.6 — Generalization and consolidation

Generalize import paths beyond DOI/arXiv and consolidate the engine's
cross-cutting patterns.

- **Complete JabRef formatting compatibility**: implement and test the remaining
  v5.15 formatter-as-modifier behavior and key-pattern markers/modifiers, using
  upstream JabRef implementations, tests, and golden vectors as the oracle.

- **New import paths**: PubMed PMID/PMCID, ISBN, SSRN ID, NBER ID, generalized
  journal-URL resolver table covering common publisher patterns.
- **Generalized URL import**: `ref import <url>` auto-detects identifier type
  from any supported publisher/catalog URL (DOI, arXiv, PubMed, SSRN, NBER,
  ISBN, nature.com, journals.aps.org, plus the new Elsevier/Springer/Wiley/PLOS
  patterns) and resolves it through the appropriate provider, normalizing the
  result into a uniform metadata dict.
- **Richer `search` + `--where` grammar**: fuzzy title matching, date-range
  filtering, "entries missing field X" queries, search-result JSON with match
  explanations. Extend the `--where` grammar (shared by `search`, `fields`, and
  `corpus split`) beyond single predicates to boolean `and`/`or`, `key in [...]`,
  and numeric comparison (`year >= 2025`) — covers common agent facepalms
  without writing ad-hoc grep.
- **Multi-entry triage view**: `ref show --keys k1,k2,… [--abstract]` (or
  `search --show-abstract`) to scan a set of candidate entries in one call
  instead of one invocation per key.
- **`metadata doctor [--fix]` + metadata-aware `lint`**: rename known-legacy
  metadata keys to their current spelling, validate enum *values* (catch typo'd
  policy tokens), flag `[pynakes:unknown:*]` keys, and collapse duplicate
  metadata blocks — today metadata drift passes silently.
- **Quieter `lint` consistency heuristic**: scope the "missing field X vs peers"
  check within entry-type *and* identity class (preprint/published/book/code),
  or gate it behind `lint --consistency`, so healthy libraries don't bury real
  issues under peer-consistency noise.
- **`asset fetch`/`check` file targeting**: a `--all`/`--file` form to operate
  on every entry in a specific library when sibling `.bib` files share the
  directory (today the first positional is read as a citation key, and bare
  auto-detect fails with multiple `.bib` files present).
- **Cross-cutting consolidation**: unify interface patterns, reduce duplication
  across import, identity, and metadata pathways.

**Done when**: broader import paths, richer `search`/`--where`, `metadata
doctor`, and the `lint`/`groups`/`asset` UX fixes implemented, tested, and
documented; `pytest && ruff` green; CHANGELOG updated; version bumped to 0.6.0.

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
- **Cross-library entry operations** — the motions single-file mode can't
  express, built on the `Library` + v0.7 identity primitive:
  - **`corpus pick`** — cross-library entry cherry-pick, the missing verb:
    `corpus pick SRC.bib… --keys K1,K2,… --into DEST.bib [--with-materials]
    [--strip-groups | --map-group "Src=Dest"] [--dedupe]`. Pull a focused subset
    out of one or more larger libraries into a target library in a single
    reviewable command, replacing a harvest→strip→combine→re-group script. This
    is the operation the "seed a new library from neighbors" workflow is built on
    and the one entry-level motion with no path today.
  - **`corpus search`** — one query across N libraries with a `[file]` column
    ("which of my libraries already has this?"), surfacing `Library.search` at
    the CLI.
  - **`corpus dedupe` / `dedupe --against other.bib`** — cross-file
    duplicate/identity check so entries are vetted against siblings before a
    transplant.
  - **`ref import --from sibling.bib KEY`** — pull a single entry from a sibling
    library by key without first digging out its DOI (a lighter cousin of
    `corpus pick`).
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

**Done when**: `Library`, `Catalogue`, and the cross-library entry operations
(`corpus pick`/`search`/`dedupe`) shipped with tests and docs; MCP server
published as a companion package; agent-plan and change-summary features
shipped; `pytest && ruff` green; CHANGELOG updated; version bumped to 0.8.0.

### v1.0 — Launch

- Stable API, semver promise.
- All eight guiding principles intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Guiding principles (non-negotiable)

Invariants from [docs/guides/architecture.md](docs/guides/architecture.md) and
[CLAUDE.md](CLAUDE.md):

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte unless
   the user explicitly requests canonical whole-file layout formatting.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve by default, and impose a
   canonical layout only when explicitly requested.**
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
