# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Applications built on top of it (capture, reading, a
UI, sync) remain separate companion projects rather than layers inside the core
engine. This plan may track their integration milestones, but they must consume
the same pinned public API instead of adding a second parser, data model, or
source of truth.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### v0.6 — Generalization, consolidation, and shared work matching

Generalize import paths beyond DOI/arXiv and consolidate the engine's
cross-cutting patterns. New providers and consumers build on the shared,
conservative work-matching evidence implemented in this release.
Tasks below are listed in implementation priority order.

- **Cross-cutting consolidation**: unify interface patterns, reduce duplication
  across import, identity, and metadata pathways.
- **New import paths**: expand the
  [import-provider inventory](docs/guides/import-providers.md) through the
  normalized provider interface and declarative URL resolver tables. The
  remaining Planned rows are the publisher platforms (IEEE, ACM, RSC, ACS,
  Project Euclid), the metadata indexes as import entry points (Crossref,
  DataCite, OpenAlex, Semantic Scholar), and the other book catalogues (Google
  Books, Library of Congress). Candidates not yet in the inventory, ordered by
  the size of the community whose canonical identifier is not a DOI: NASA ADS
  (bibcodes; needs a user-supplied API token), OpenReview, RePEc/IDEAS handles,
  zbMATH Open and MathSciNet review numbers, institutional-repository URN
  resolvers such as DiVA, and SciELO. Google Scholar stays out of scope: it has
  no API and scraping it is against its terms.
- **Complete JabRef formatting compatibility**: implement and test the remaining
  v5.15 formatter-as-modifier behavior and key-pattern markers/modifiers, using
  upstream JabRef implementations, tests, and golden vectors as the oracle.
- **`metadata doctor [--fix]` + metadata-aware `lint`**: rename known-legacy
  metadata keys to their current spelling, validate enum *values* (catch typo'd
  policy tokens), flag `[pynakes:unknown:*]` keys, and collapse duplicate
  metadata blocks — today metadata drift passes silently.
- **Single-bibliography analysis**: add a public `pynakes.analysis` API
  namespace and a read-only `stats` command returning typed and JSON-friendly
  reports for one `BibFile`/`Bibliography`. Start with deterministic descriptive
  measures: entries by type and year, author/journal frequencies, identifier
  and required-field coverage, lint finding counts, group membership, and
  declared linked-file coverage. Keep analysis offline and separate from
  mutation; do not turn heuristic scores into quality judgments.
- **Richer `search` + shared `--where` grammar**: fuzzy title matching, date-range
  filtering, "entries missing field X" queries, search-result JSON with match
  explanations. Extend the `--where` grammar beyond single predicates to boolean
  `and`/`or`, `key in [...]`, and numeric comparison (`year >= 2025`) — covers
  common agent facepalms without writing ad-hoc grep. Make it one transversal
  selector surface shared by entry-addressable commands (`search`, `fields`,
  `format`, and corpus operations) rather than adding command-specific filters.
- **Multi-entry triage view**: `ref show --keys k1,k2,… [--abstract]` (or
  `search --show-abstract`) to scan a set of candidate entries in one call
  instead of one invocation per key.
- **`asset fetch`/`check` file targeting**: a `--all`/`--file` form to operate
  on every entry in a specific library when sibling `.bib` files share the
  directory (today the first positional is read as a citation key, and bare
  auto-detect fails with multiple `.bib` files present).

**Done when**: broader import paths, richer `search`/`--where`, `metadata
doctor`, single-bibliography `analysis`/`stats`, and the
`lint`/`groups`/`asset` UX fixes are implemented, tested, and documented;
`pytest && ruff` green; CHANGELOG updated; version bumped to 0.6.0.

---

### v0.7 — Multi-bib setup, Library, Catalogue, and MCP server

- **`Library` (corpus)**: `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the
  work-matching evidence from v0.6. A Library holds many `.bib` files (many
  pinakes).
- **Cross-library entry operations** — the motions single-file mode can't
  express, built on the `Library` + v0.6 work-matching evidence:
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
- **Library-wide analysis**: lift the v0.6 analysis reports over `Library`,
  retaining per-file provenance while adding corpus-wide rollups and
  cross-library coverage/duplication views. Reuse the same typed results rather
  than creating an unrelated statistics implementation.
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

**Done when**: `Library`, `Catalogue`, Library-wide analysis, and the
cross-library entry operations (`corpus pick`/`search`/`dedupe`) shipped with
tests and docs; MCP server published as a companion package; agent-plan and
change-summary features shipped; `pytest && ruff` green; CHANGELOG updated;
version bumped to 0.7.0.

---

### v0.8 — Performance and scale

Measure and improve the offline paths that become important once v0.7 can work
across many bibliographies. Performance claims must be backed by reproducible
results, not estimates.

- **Reproducible benchmark suite**: add generated and fixture-backed corpora at
  documented sizes; measure parse, unchanged write, lint, search, dedupe,
  canonical formatting, bulk surgical edits, Library queries, and Catalogue
  builds. Record the Python version, platform, corpus shape, and peak memory
  alongside timing results.
- **Linear parser path**: remove repeated whole-prefix line counting and linear
  duplicate-key membership checks during parsing while preserving duplicate
  keys, exact source layout, and parse-error locations.
- **Blocked identity and dedupe matching**: use the shared work-matching
  evidence from v0.6 to build candidate sets by stable identifiers and metadata
  fingerprints; do not compare every unrelated pair with fuzzy title matching.
- **Single-pass bulk edits**: apply recorded source spans in source order rather
  than repeatedly searching and copying the entire bibliography for every
  changed entry.
- **Library and Catalogue profiling**: measure index construction, refresh,
  cross-file search, and identity reconciliation from v0.7; optimize only
  profiles that show material cost.
- **Regression budgets**: establish benchmark baselines before choosing
  thresholds, then gate material regressions in representative offline
  operations without using brittle wall-clock assertions in the correctness
  suite.
- **Evidence-based documentation**: publish only measurements produced by the
  benchmark suite, with their environment and corpus; document known scaling
  limits and do not infer an untested maximum library size.

**Done when**: the benchmark suite and baseline report are published; common
offline paths have no known accidental quadratic scans; dedupe avoids exhaustive
pairwise fuzzy comparison for ordinary nonmatching corpora; benchmarked
regression budgets are enforced; correctness, round-trip, and duplicate-key
tests remain green; CHANGELOG updated; version bumped to 0.8.0.

---

### v1.0 — Launch

**A polished single-file maintenance engine, losslessly JabRef-compatible, with
a pinned public API and a PyPI release.** The unit of work is one
`Bibliography` (one `.bib`). The multi-bib `Library`, `Catalogue`, and MCP
server ship in v0.7 as optional companions.

- Stable API, semver promise.
- All [core architecture invariants](docs/guides/architecture.md#core-invariants)
  intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## v2.0 — Beyond 1.0

The data and analysis items stay **in pynakes** as pure bib-file mechanisms.
The editor/GUI item is a separately distributed companion tracked here because
it exercises the pinned integration boundary.

- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation.
- **Additional interchange formats** — any import/export formats beyond the
  existing CSL-JSON/RIS/MODS/EndNote quartet, building on `pynakes.interchange`.
- **Linked-material reference graph** — extract bibliography/reference lists
  from linked paper source or PDFs, resolve their identifiers conservatively,
  and expose the result as a derived citation graph for analysis. Preserve
  provenance and uncertainty; never write inferred references into the source
  `.bib` automatically.
- **Content-intelligence layers** — full-text extraction, content search,
  RAG/embeddings, and rich agent notes/memory, as an opt-in extra never on the
  bibliography write path.
- **Editor/GUI companion** — prototype a VS Code/Open VSX extension (distributed
  as a `.vsix`) as the first graphical client. It should browse and search
  bibliographies, expose analysis/stats and linked-material state, navigate
  between TeX citations and entries, stage edits, show the exact diff, and
  require approval before commit. Keep it a thin client over the pinned
  pynakes API or MCP/service boundary: no independent BibTeX parser, metadata
  schema, or source of truth. A standalone Bimas desktop GUI can reuse the same
  boundary later if editor embedding proves too restrictive.

**Done when**: the core 2.0.0 release is on PyPI with its mechanisms documented,
and the first editor/GUI companion prototype is published against the pinned
integration API.
