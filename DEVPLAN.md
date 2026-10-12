# pynakes development plan

pynakes is a **reference management engine for BibTeX and BibLaTeX bibliographies and their research materials**,
exposed through a Python library and CLI. The product ambition is to support a
research library throughout its life: reference acquisition and curation,
material provenance, project bibliographies, manuscript citation maintenance,
and public release copies.

The current foundation is one authoritative `Bibliography` (`.bib`), optional
Pinax materials, and explicit operations across files. The next planned step
extends that foundation to `Library`, a rebuildable `Catalogue`, and analysis
across collections. Applications for capture, reading, graphical interaction,
and sync consume the same engine; they share its parser, data model and review
contract. Planned integrations are tracked here without being advertised as
implemented features.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### v0.7 — CLI beta, editor alpha

v0.7.0 moves the **CLI** to beta: its command syntax, options, JSON envelope,
exit codes, and error codes become a contract that changes only through a
documented deprecation. The **VS Code editor** ships alongside it as a
**0.1.0 alpha** pre-release — usable, with no compatibility promise of its own,
and a consumer of nothing but the beta envelope. The Python API keeps its
current status — the intended public surface in
[docs/guides/public-api.md](docs/guides/public-api.md), with breaking changes
documented but not deprecated — until 1.0 pins it.

The pre-beta audit's six engineering stages are closed (gates met between
2026-10-01 and 2026-10-12), and the editor's alpha features and bug-fix audit
are done. Their changes are in [CHANGELOG.md](CHANGELOG.md) under 0.6.5 and
0.7.0 and in `editor/CHANGELOG.md`. What remains is the release itself.

#### The beta promise

What 0.7.0 commits to, and what every later change is held to:

- **A frozen surface, with deprecation.** From 0.7.0, removing or renaming a
  command, option, envelope key, `action` value, exit-code meaning, or error
  code takes one minor release in which the old form still works and emits a
  structured warning (`{"type": "deprecated", "old": ..., "new": ...}`) before
  it is removed. Additions may ship in any minor release; patches fix bugs only.
- **No known data-loss bugs.** No command silently changes bytes outside the
  entries it edits, writes an unparseable file, reports a failed write as a
  success, or leaves a multi-file operation half-applied.
- **No tracebacks.** Every failure is a JSON error carrying a catalogued code.
- **Tested where advertised.** Every operating system and Python version the
  package metadata claims runs the suite in CI, as do the declared dependency
  floors.
- **Docs describe the real surface**, with a command reference generated from
  the live CLI.

#### Standing decisions from the audit

Decisions that still constrain new work:

- The Python API is its own interface: a `Bibliography` method no command calls
  is not dead code for that reason alone.
- `--strict` gates a read-only command (`lint`, `verify`, `dedupe check`,
  `keys check`, `asset check`) or the completeness of `asset fetch`, always
  emitting the full envelope before exiting 1; `--check` is a transform's
  check mode
  (`format`, `scrub`). `-f` is `--file` everywhere, `--field` is a
  `name=value` assignment, and `--out PATH|-` is the one output flag.
- Settings are named for the command that applies them and `lint` verifies
  them. A setting for one entry is a directive comment above it
  (`% pynakes: verb args -- reason`), never a `pynakes-*` field; a new
  directive adds a word to `ref directive`, not a command.
- No project-level config (`pynakes.toml`, `[tool.pynakes]`): the `.bib` carries
  its own settings. Revisit with the v0.8 `Library`.
- Group-tree commands edit the hierarchy, not entries, unless asked:
  `rename-group --members` moves memberships, and `remove-group` keeps them.
- The surface contract is enforced by `tests/test_contract.py`, read from the
  live command tree; tests read option choices from `capabilities --json`,
  never from rendered `--help`.
- The ty baseline (`[[tool.ty.overrides]]` in `pyproject.toml`) only shrinks.
  No module exceeds 800 lines; `fetch.py`, `normalize.py` and `lint.py` are
  near it and must be split before substantial additions.
- Actions are referenced by major version tag, not commit SHA. The release
  workflow's TestPyPI option needs a `testpypi` environment and a trusted
  publisher on test.pypi.org first. The local-only `v0.6.2` tag was never
  released; retire it or leave it unpushed.

#### Release — engine 0.7.0 Beta with editor 0.1.0 Alpha

The checklist is [RELEASE.md](RELEASE.md). Remaining:

1. CI green on the release commit, the full matrix and the editor job.
2. Manual acceptance in VS Code against the ready engine, and manual agent
   acceptance recorded separately (the former hand-run harness was removed in
   `0ef2951`; `test_contract.py` and `test_workflows.py` are automated tests,
   not an agent evaluation).
3. Choose the editor's distribution channel (VS Code Marketplace, Open VSX, or
   both) and claim the `pynakes` publisher there.
4. Rebuild both artifacts from the clean release commit (the editor with
   `npm run package:prerelease` against the 0.7.0 engine), validate them, date
   both changelogs, then push the `v0.7.0` tag and publish the editor in the
   same window.

Until then, fix regressions only; new features wait for 0.7.1 or v0.8.

**Done when**: candidate use has shown no data-loss or contract regression; both
distributions are published in the coordinated release; the engine tag names
0.7.0.

#### Editor track

The extension's scope is a bibliography belonging to a document or repository
being edited, not library-scoped exploration (see
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope)).

- **Thin-client discipline** — no BibTeX parser, metadata schema, or source of
  truth in the client. When the view needs something the engine does not
  expose, the engine grows it; a workaround in TypeScript is a regression even
  when it works.
- **Concurrent development** — until the library-scoped client starts, the CLI
  and the extension evolve together in this repository, so an engine gap and
  its client consumer land in one reviewable change. A second client is what
  would justify splitting them apart.
- **Open after the 0.1.0 audit** (not gating the alpha):
  - *Groups-field separator:* pynakes reads and writes `groups` memberships on
    `;`, while JabRef's default keyword separator is `,`. A multi-group entry
    from a default JabRef setup reads as one group. Decide how the separator
    is declared or detected before 1.0.
  - *Opening materials with the system handler:* a `file`-field path is handed
    to the OS; on Windows an executable named by an untrusted `.bib` could run.
    Decide on an allow-list or a confirmation.
  - *Fetch progress:* the engine reports no per-file progress in `--json`
    mode, and the view does not offer `--access institutional`.
  - `keys generate` and `keys repair` move Pinax materials but do not report
    `pinax_materials` as `keys rename` does.

**Editor alpha gate**: the `.vsix` is published as a pre-release; its checks run
in CI against the beta envelope; every gap it surfaced was closed in the engine
rather than worked around in the client.

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
- **Mirrored-bibliography rename propagation** — pynakes treats every `.bib` in
  isolation, but a common layout keeps a superset bibliography (e.g.
  `bibliography/`) and a working subset copy (e.g. `manuscript/`) that must
  track it; renaming a key in the superset has no way to propagate to the
  mirror today. Needs a declared mirror relationship (naming still open —
  avoid overloading "corpus") and a propagation step for `keys rename` (and any
  other key-changing operation) once that relationship exists. Moved from v0.7,
  where it would have added surface during the freeze.
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
- **More per-entry directives.** `% pynakes: ignore` shipped with the
  `ref directive` writer (see CHANGELOG); each further verb is a word in the
  same grammar, not a new command. Candidates, each the per-entry form of a
  library setting or a recurring false positive: `distinct-from KEY` for a pair
  `dedupe check` flags but that are different works (the same commit-hook
  problem #2 raised for lint); `no-fetch` or a per-entry fetch policy for
  `asset fetch`; `keep-key` against key regeneration; and an opt-out from
  `enrich` when a provider's record for the work is wrong. `ref show` could list
  an entry's directives.
- **Type spelling of new entries** (only if asked for): under
  `format-entry-type-case: preserve`, `ref add` and `ref import` still write
  `@book`, so a JabRef library mixes spellings until JabRef next saves it. A
  JabRef spelling value for the setting, or a `consistency` finding for mixed
  spellings of one type, would close that.
- **Further import paths**: candidates not yet in the inventory, ordered by the
  size of the community whose canonical identifier is not a DOI: NASA ADS
  (bibcodes; needs a user-supplied API token), RePEc/IDEAS handles, MathSciNet
  review numbers, institutional-repository URN resolvers such as DiVA, and
  SciELO; then ISBN coverage beyond Open Library through a catalogue such as
  WorldCat (Google Books and the Library of Congress are out of scope, per
  [docs/guides/import-providers.md](docs/guides/import-providers.md)).
  OpenReview is held back rather than planned: its public API answers a bot
  challenge to non-browser clients, so importing from it would mean defeating
  that challenge. Revisit only if a documented, key-based API path appears.
- **MCP server**: a thin [Model Context Protocol](https://modelcontextprotocol.io)
  companion on the pinned pynakes API, allowing agents to interrogate a personal
  corpus conversationally — "find papers by X on topic Y", "which entries are
  missing PDFs", etc. Query-only layer over the `Library`/`Catalogue`.
- **Agent surface polish**:
  - **Plan-and-approve workflow**: extend `corpus batch`, which already
    previews and commits a sequence of bibliography operations as one, to
    material and network steps (e.g. "dedupe these → normalize → fetch PDFs"),
    so a whole multi-step plan is approved once.
  - **Post-hoc change summary**: the change plan already counts added, removed,
    renamed, and modified entries; add operation-level counts — "3 keys
    renamed, 12 fields normalized, 2 entries enriched" — so an agent can report
    what happened without re-parsing the diff.
- **`Catalogue`-backed rich query CLI**: `search` gains full-text queries
  against the index; its existing field-scoped terms carry over.
- **Editor toward beta**: whatever of the v0.7 alpha feature work remains, plus
  the library-scoped reads the `Library` makes possible. The extension may
  *read* library-scoped things; it never owns or curates them.

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
results, not estimates. The linear parser path was fixed in v0.7, because a
single real library already reaches the sizes where it matters.

Starting point, from `scripts/bench_scale.py` on synthetic libraries at the
close of v0.7 (one machine; measurements, not assertions):

| Entries | Parse | Lint | `format --check` |
| ---: | ---: | ---: | ---: |
| 4,000 | 0.40 s | 1.40 s | 2.31 s |
| 20,000 | 2.00 s | 6.97 s | 11.56 s |

- **Reproducible benchmark suite**: add generated and fixture-backed corpora at
  documented sizes; measure parse, unchanged write, lint, search, dedupe,
  canonical formatting, bulk surgical edits, Library queries, and Catalogue
  builds. Record the Python version, platform, corpus shape, and peak memory
  alongside timing results.
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

**A reference management engine with a pinned public API and a dependable
workflow from reference acquisition to project bibliography and release copy.**
Published as 1.0.0 on PyPI, it preserves authoritative files and interoperates
with JabRef. `Bibliography` remains the basic working unit; the planned v0.8
`Library`, `Catalogue` and MCP integration extend its reach across collections.

The launch must document and exercise the complete workflows, including
reference curation, material provenance and manuscript citation maintenance,
through the same Python API and CLI. Release claims follow verified behavior
and completed gates.

- Stable API, semver promise: the CLI contract, in beta since 0.7.0, and the
  Python API both fall under the semantic-versioning policy in
  [docs/guides/public-api.md](docs/guides/public-api.md).
- All [core architecture invariants](docs/guides/architecture.md#core-invariants)
  intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Beyond 1.0

The data and analysis items stay **in pynakes** as pure bib-file mechanisms.
The remaining GUI item is a separately distributed companion tracked here
because it exercises the pinned integration boundary. Clients divide by
**scope**, not by feature: the project-scoped editor ships as an alpha in v0.7,
and what remains here is the library-scoped client — one serves a bibliography
belonging to a document you are editing, the other a library belonging to no
project at all. See
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
