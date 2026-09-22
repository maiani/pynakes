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

### v0.7 — Project-scoped editor

The first graphical client, and the milestone that turns the JSON envelope from
a documented contract into a load-bearing one by giving it a consumer that is
not a human at a terminal. Scope is a bibliography belonging to a document or
repository being edited; library-scoped exploration is neither this milestone
nor this client. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).

- **The extension** — a VS Code / Open VSX client in `editor/`, distributed as a
  `.vsix`. It browses one bibliography as an entry table, shows the declared
  group hierarchy, runs the engine's search, surfaces lint findings as in-view
  markers and native diagnostics, and stages field edits for review as an exact
  diff before commit, alongside citation navigation, linked-material state, and
  entry-level mutation. The two items below are what remains before it earns the
  milestone; surfacing the single-bibliography analysis reports waits on v0.8.
- **Group *hierarchy* editing** — the entry table can now put an entry into a
  group and take it out again, but the tree itself is still read-only in the
  view: a group node cannot be added, renamed, moved, or removed there. No
  engine gap — `groups add-group`, `rename-group`, `move-group`,
  `remove-group`, and `update-group` all exist with `--dry-run --diff` — so this
  is the sidebar growing the same preview-and-approve path the entry actions
  already use. Ranked last of the remaining work because membership, not
  hierarchy, is what a project bibliography changes week to week.
- **`asset fetch` from the view** — an entry's missing material is marked, but
  fetching it still means a terminal. The command exists and is explicitly
  network-gated; the view needs to offer it under the same
  `pynakes.allowOnlineLookups` switch that now covers compare and import.
- **Distribution without a pynakes install** — the extension bundles the engine,
  so it needs a Python 3.11+ interpreter but no `pip install`. Every runtime
  dependency is a pure-Python wheel, so one universal build covers every
  platform with no per-platform build matrix and nothing to code-sign. An engine
  the user installed themselves is preferred when strictly newer than the
  bundled copy, so upgrading pynakes does not wait on an extension release.
- **Thin-client discipline** — no BibTeX parser, metadata schema, or source of
  truth in the client. When the view needs something the engine does not expose,
  the engine grows it; a workaround in TypeScript is a regression even when it
  works. This is the constraint the milestone exists to test, and every gap it
  surfaces is engine work.
- **Concurrent development** — until the library-scoped client starts, the CLI
  and the extension evolve together in this repository, so an engine gap and its
  client consumer can land in one reviewable change. A second client is what
  would justify splitting them apart.
- **Mirrored-bibliography rename propagation** — pynakes treats every `.bib` in
  isolation, but a common layout keeps a superset bibliography (e.g.
  `bibliography/`) and a working subset copy (e.g. `manuscript/`) that must
  track it; renaming a key in the superset has no way to propagate to the
  mirror today. Needs a declared mirror relationship (naming still open —
  avoid overloading "corpus") and a propagation step for `keys rename` (and any
  other key-changing operation) once that relationship exists.

Shipped so far: project-scoped browsing, search, lint as in-view markers and
native diagnostics, the group hierarchy, staged field edits with
diff-and-approve, citation navigation in both directions over the engine's
citation index, linked-material state with a click that opens the material, and
entry-level mutation — import by identifier, add, remove, group membership, and
per-cluster duplicate merging — each previewed as the engine's own diff and
approved before anything is written.

**Done when**: the two items above are covered as well; the extension is
published as a `.vsix`; every gap it surfaced was closed in the engine rather
than worked around in the client; its checks run in CI; CHANGELOG updated;
version bumped to 0.7.0.

---

### v0.8 — Multi-bib setup, Library, Catalogue, and MCP server

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
- **Single-bibliography analysis**: add a public `pynakes.analysis` API
  namespace and a read-only `analyze` command returning typed and JSON-friendly
  reports for one `BibFile`/`Bibliography`. Start with deterministic descriptive
  measures: entries by type and year, author/journal frequencies, identifier
  and required-field coverage, lint finding counts, group membership, and
  declared linked-file coverage. The report composes the existing
  `lint`/`files`/`filestore`/`identity` result objects rather than
  reimplementing their checks, and is sectioned so the library-wide rollup
  below aggregates it without redesign. Keep analysis offline and separate from
  mutation; do not turn heuristic scores into quality judgments. Deferred here
  from v0.6.
- **Library-wide analysis**: lift the single-bibliography analysis reports over
  `Library`, retaining per-file provenance while adding corpus-wide rollups and
  cross-library coverage/duplication views. Reuse the same typed results rather
  than creating an unrelated statistics implementation.
- **Further import paths**: candidates not yet in the inventory, ordered by the
  size of the community whose canonical identifier is not a DOI: NASA ADS
  (bibcodes; needs a user-supplied API token), RePEc/IDEAS handles, MathSciNet
  review numbers, institutional-repository URN resolvers such as DiVA, and
  SciELO. A cross-check against JabRef and Zotero adds zbMATH and IACR
  (discipline identifiers), PMCID alongside the existing PubMed path, ISBN via a
  book catalogue such as WorldCat or the Library of Congress, and title-based
  DOI lookup — the one non-identifier entry point, which must stay explicitly
  fuzzy and never auto-accept a single result. OpenReview is held back rather than planned: its public API answers a
  bot challenge to non-browser clients, so importing from it would mean
  defeating that challenge. Revisit only if a documented, key-based API path
  appears.
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

**Done when**: `Library`, `Catalogue`, single-bibliography and library-wide
analysis, and the
cross-library entry operations (`corpus pick`/`search`/`dedupe`) shipped with
tests and docs; MCP server published as a companion package; agent-plan and
change-summary features shipped; `pytest && ruff` green; CHANGELOG updated;
version bumped to 0.8.0.

---

### v0.9 — Performance and scale

Measure and improve the offline paths that become important once v0.8 can work
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
  cross-file search, and identity reconciliation from v0.8; optimize only
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
tests remain green; CHANGELOG updated; version bumped to 0.9.0.

---

### v0.10 — Ingestion and hygiene breadth

Close the gaps that a cross-check against JabRef and Zotero shows are
conspicuous in a single-file engine: getting an entry *in* from something that
is not already an identifier, and the value-level cleanups both tools ship. All
of it stays single-bibliography work, so it lands before the 1.0 pin rather than
after it. Network access remains explicit and opt-in per the existing rule.

- **`ref from-pdf`** — build an entry from a PDF. Layered cheapest-first: read
  embedded BibTeX and XMP metadata, then a DOI/arXiv id found in the document
  text, then fall back to resolving what was found through the existing
  provider registry. This is the reverse of `ref import` and the most commonly
  cited gap against both tools. Text extraction needs a PDF dependency, so it
  ships as an optional extra rather than a core requirement, and a scanned PDF
  with no extractable identifier must fail honestly instead of guessing.
- **`ref from-text`** — build an entry from a pasted reference string. Offline
  and dependency-free, reporting which fields it recognized and which it could
  not, so a partial parse is visible rather than silently thin. Never emit a
  confident entry from an ambiguous string; leave the uncertain fields out.
- **Journal abbreviation coverage** — the current LTWA seed table plus
  `--ltwa-table` covers the mechanism but not the data. Ship a curated
  abbreviation database so correct behavior is not conditional on the user
  finding a CSV, and widen `JOURNAL_STYLES` beyond `abbreviated`/`full`/`none`
  to the forms competitors expose (e.g. MEDLINE, shortest-unique). Title lists
  are data, not logic: keep them versioned and inspectable.
- **Further `normalize` formatters** — the most-used value-level cleanups from
  JabRef's save actions: HTML entities and markup to LaTeX, Unicode to LaTeX
  and back, and LaTeX markup tidying. These belong to `normalize` because they
  change bibliographic *values*; `format` stays layout-only and must not
  acquire any of them.
- **`asset link`** — scan a directory and match existing files to entries by
  citation key, then by a documented name heuristic, and report the matches for
  approval before writing any link. The batch counterpart to today's
  per-material workflow, and the answer to "I have 500 PDFs and a `.bib`".
  Ambiguous matches are reported, never silently resolved.
- **Richer `dedupe merge` conflict resolution** — JabRef resolves a merge with a
  visual field-by-field diff, which a headless tool cannot copy directly. The
  equivalent is better evidence and finer control: per-field provenance in the
  merge report, an explicit field-level choice rather than whole-entry
  precedence, and a refusal to auto-merge when the evidence is weak. Build it on
  the v0.6 work-matching evidence instead of a second similarity implementation.
- **`saved-search`** — persist a named predicate query in the `pynakes-meta`
  namespace and re-run it on demand, so a `--where` expression becomes a
  durable view instead of shell history. A saved search is a stored query, never
  a stored result set, and never a second source of truth about membership.

**Done when**: `ref from-pdf` and `ref from-text` ship with an optional-extra
boundary for the PDF dependency; the curated abbreviation database and widened
journal styles are in place; the added `normalize` formatters leave `format`
layout-only; `asset link` and `saved-search` ship with tests and docs;
`pytest && ruff` green; CHANGELOG updated; version bumped to 0.10.0.

---

### v1.0 — Launch

**A polished single-file maintenance engine, losslessly JabRef-compatible, with
a pinned public API and a PyPI release.** The unit of work is one
`Bibliography` (one `.bib`). The multi-bib `Library`, `Catalogue`, and MCP
server ship in v0.8 as optional companions.

- Stable API, semver promise.
- All [core architecture invariants](docs/guides/architecture.md#core-invariants)
  intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Beyond 1.0

The data and analysis items stay **in pynakes** as pure bib-file mechanisms.
The remaining GUI item is a separately distributed companion tracked here
because it exercises the pinned integration boundary. Clients divide by
**scope**, not by feature: the project-scoped editor ships in v0.7, and what
remains here is the library-scoped client — one serves a bibliography belonging
to a document you are editing, the other a library belonging to no project at
all. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).

- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation.
- **Additional interchange formats** — import/export beyond the existing
  CSL-JSON/RIS/MODS/EndNote/CSV codecs, building on `pynakes.interchange`. The
  cross-check against JabRef and Zotero puts TEI first (digital humanities),
  then Markdown and HTML for documentation workflows, then Wikidata Quick
  Statements for linked-open-data export. Export breadth is additive and low
  risk: each codec is a pure projection that never touches the write path.
  User-definable format filters, as JabRef offers them, are not planned as a
  separate mechanism: pynakes is a library, so `pynakes.interchange` is already
  the extension point for a format we do not ship.
- **Linked-material reference graph** — extract bibliography/reference lists
  from linked paper source or PDFs, resolve their identifiers conservatively,
  and expose the result as a derived citation graph for analysis. Preserve
  provenance and uncertainty; never write inferred references into the source
  `.bib` automatically.
- **Typed entry relationships** — a way to record non-hierarchical links between
  entries ("is review of", "is response to", "extends") that BibTeX's `crossref`
  and `xdata` inheritance cannot express. Zotero's related-items feature is the
  precedent. It needs a metadata model in the `pynakes-meta` namespace and must
  survive round-tripping, which is why it waits for the reference graph above
  rather than arriving as a loose field convention.
- **Material metadata writing** — `asset embed-xmp`: write an entry's
  bibliographic metadata into its linked PDF as XMP, making the file
  self-describing for sharing and archival, and the natural companion to
  reading metadata *out* of a PDF in v0.10. This one modifies a material rather
  than the `.bib`, so it needs the same preview-and-approve treatment as a
  bibliography edit and must never be implied by another command.
- **Further material formats** — EPUB metadata extraction alongside PDF, as
  open-access monographs become common. Lower priority than PDF by usage, and
  it shares the v0.10 extraction pipeline rather than duplicating it.
- **Content-intelligence layers** — full-text extraction, content search,
  RAG/embeddings, and rich agent notes/memory, as an opt-in extra never on the
  bibliography write path.
- **Library-scoped GUI (Bimas, working name)** — a standalone application for
  exploring a generic library: one that belongs to no particular project and
  outlives any workspace. It is *not* a fallback for the extension proving too
  confining. A VS Code custom editor binds a view to a single owned document, so
  library scope is out of the extension's reach however capable it becomes.
  Bimas reuses the same envelope and service boundary rather than gaining a
  bibliography implementation of its own. Starting it is the point at which the
  client layer earns its own repository, and the point by which the integration
  boundary must already be pinned — two clients cannot share an unversioned
  contract.

**Done when**: the core 2.0.0 release is on PyPI with its mechanisms documented.
Bimas is not a 2.0 gate: it begins once the integration boundary is pinned,
which the project-scoped editor in v0.7 is what first forces.

---

## Deliberately out of scope

A cross-check of JabRef and Zotero surfaced features that are **not** planned, so
that their absence reads as a decision rather than an oversight. They are
rejected on fit, not on merit — several are the reason people choose those tools.

- **Shared SQL database backend** (JabRef: PostgreSQL/MySQL with live sync). The
  file is the single source of truth and git is the collaboration story. A
  second authoritative store would contradict the core invariant.
- **Sync services and group libraries with permissions** (Zotero). Same reason:
  version control already provides history, merging, and sharing for plain text.
- **Word processor plugins** (both: Word, LibreOffice, Google Docs). Citation
  *rendering* against CSL styles is a different problem from bibliography
  maintenance, and it is already well served. pynakes stays on the `.bib` side
  of that line; the TeX-facing half is `tex ... scan` and citation navigation.
- **Browser extension with site translators** (Zotero's several thousand
  publisher scrapers). This is genuinely Zotero's strongest feature and it
  requires a browser runtime plus a scraper corpus maintained per publisher.
  `ref import` covers the identifier- and URL-addressable path instead.
- **Reading and annotation UI** (Zotero: PDF/EPUB reader, highlights, notes,
  read-aloud, reflowable view) and **mobile applications**. A different product
  category; nothing about them belongs in a bib-file engine.
- **RSS/journal feed subscriptions** (Zotero). Awareness of new literature is
  adjacent to, not part of, maintaining a bibliography.
- **Quick one-off bibliography generator** (ZoteroBib). A different audience:
  users who explicitly do not want a library to maintain.
- **Configurable material filename patterns** (JabRef's `[citationkey] - [title]`
  style patterns; Zotero's continuous renaming as metadata changes). Pinax
  addresses materials *by citation key* — `<key>.<kind>` is the lookup, not a
  cosmetic default — so user-defined naming would remove the property the whole
  store depends on, and renaming on every metadata edit would make the file
  layout a moving target under version control. The legitimate want beneath it,
  human-readable filenames for sharing, belongs to an export or copy operation
  that names files on the way out, leaving the store addressable.
- **Cite-as-you-write HTTP daemon on a fixed port** (JabRef, port 23119). The
  need is real, but the MCP server in v0.8 and the editor in v0.7 both address
  it over boundaries that already exist, without a background service listening
  on a well-known port.
