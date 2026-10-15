# pynakes development plan

pynakes is a **reference management engine for BibTeX and BibLaTeX bibliographies and their research materials**,
exposed through a Python library and CLI. The product ambition is to support a
research library throughout its life: reference acquisition and curation,
material provenance, project bibliographies, manuscript citation maintenance,
and public release copies.

The current foundation is one authoritative `Bibliography` (`.bib`), optional
Pinax materials, and explicit operations across files. The next releases first
improve bounded research reads, then extend that foundation to `Library`, a
rebuildable `Catalogue`, and source-linked evidence. Applications for capture,
reading, graphical interaction,
and sync consume the same engine; they share its parser, data model and review
contract. Planned integrations are tracked here without being advertised as
implemented features.

This document is the **road to 1.0** and possible extensions beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### v0.7 — CLI beta, editor alpha

v0.7.0 moves the **CLI** to beta: its command syntax, options, JSON envelope,
exit codes, and error codes become a contract that changes only through a
documented deprecation. The **VS Code editor** follows independently as a
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
  its own settings. Revisit with the v0.9 `Library`.
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

#### Release — engine 0.7.0 Beta first

The checklist is [RELEASE.md](RELEASE.md). Release the engine first; editor
0.1.0 Alpha remains a separate publication with its own acceptance and publisher
setup. Engine release steps:

1. Record installed-wheel tests, disposable-library checks and manual agent
   acceptance separately from automated contract/workflow tests.
2. Date the engine changelog and commit the release changes; require the full
   CI matrix to pass on that commit.
3. Build and validate final-version artifacts from the clean release commit,
   then push `v0.7.0`. Verify the release workflow, PyPI and GitHub release.

Until then, fix regressions only. New features wait for v0.8; 0.7.x patches
fix bugs only.

**Done when**: candidate use has shown no data-loss or contract regression;
engine 0.7.0 is published and installable. Editor publication is not this gate.

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
  - *Fetch progress:* the engine now streams per-entry progress with
    `asset fetch --progress jsonl` (also under `--json`); the view does not yet
    consume it or offer `--access institutional`.
  - `keys generate` and `keys repair` move Pinax materials but do not report
    `pinax_materials` as `keys rename` does.

**Editor alpha gate**: the `.vsix` is published as a pre-release; its checks run
in CI against the beta envelope; every gap it surfaced was closed in the engine
rather than worked around in the client.

---

### Release approach from v0.8

Each minor release should deliver a coherent set of related workflows with
bounded acceptance cases. The versions below express an intended sequence, not calendar promises.
Do not accumulate unrelated features to fill a release, or make one release
wait for a companion application. If a slice remains too large, split it again
and renumber the later milestones. CLI compatibility follows the beta promise.
Command names and schema sketches below are proposals until implemented.

Pynakes owns bibliography operations, material identity, evidence locations, and
reviewable persistence. External agents supply interpretations and proposed
changes; researchers decide whether those interpretations are scientifically
sound. Missing evidence stays explicit. No built-in semantic classifier,
model dependency, or hidden network call is implied by this roadmap.

| Release | Cohesive scope | Main dependency |
| --- | --- | --- |
| 0.8 | Research context, saved searches and bibliography analysis | Existing reads and checks |
| 0.9 | Library, Catalogue and cross-file analysis | Bounded reads and identity evidence |
| 0.10 | Project assembly and mirrored bibliographies | Library and guarded writes |
| 0.11 | Curation: merges, directives and normalization | Existing editing and identity APIs |
| 0.12 | Materials and acquisition: linking, extraction, ingestion and providers | Pinax, bounded reads and provider registry |
| 0.13 | Evidence-linked research annotations | Material locations and hashes |
| 0.14 | Resumable plans and execution receipts | Batch, acquisition and material operations |
| 1.0 | Pin the exercised API and end-to-end contracts | Accepted workflows below |

These are seven substantial feature releases before 1.0. Related features share
one release and acceptance workflow; implementation tasks do not each need a
version. MCP and editor releases remain independently versioned companions.

#### Checks and evaluation throughout

- Every release has correctness tests, documentation, a changelog, and the
  applicable checks from `AGENTS.md`: full engine tests with coverage ≥90%,
  Ruff lint/format, ty, strict docs, and artifact checks for releases. Changed
  editor code also passes compilation and its tests.
- Start a small **agent evaluation suite in v0.8**, separate from deterministic
  contract tests. Use invented or public historical fixtures and record task,
  engine/model versions, tool calls, outcomes, and evaluation conditions.
  Begin with ambiguous references, duplicate conflicts, concurrent edits, and
  bounded reads; add cross-library assembly and evidence-grounded comparisons
  as their engine support ships. Mock provider responses for reproducible
  runs; keep explicit live-network exercises separate.
- Measure task correctness, unsupported claims, preservation of uncertainty,
  unnecessary calls, response size, and whether edits match the approved plan.
  Do not treat a passing CLI test as proof that an agent uses it correctly.
- Performance is a continuing requirement, not a release-sized catch-all.
  Extend `scripts/bench_scale.py` with representative corpus shapes, Python
  and platform details, peak memory, and timings for changed workflows.
  Include dense fuzzy-match cases as well as unrelated references. Establish
  baselines before regression budgets; avoid brittle timing assertions in
  correctness tests. Profile bulk source-span edits, index refreshes, and
  cross-file reconciliation when those paths show material cost.

### v0.8 — Research context and reusable queries

**Workflow:** select a set of papers, obtain bounded comparison context, and
save the selection criteria for later use.

The engine work is implemented and recorded under *Unreleased* in
[CHANGELOG.md](CHANGELOG.md): the bounded-read contract (`--select`,
`--include materials,provenance`, `--max-chars`, `--limit`, snapshot-bound
`--cursor`)
shared by `ref show --key`, `ref show --where`, and `search`, saved queries
(`query list/set/remove`, run anywhere as `--where 'query "NAME"'`), `analyze`, their `capabilities` schemas, and the
agent evaluation suite in `evals/agent`. Its tests cover the gate below.

Remaining before release:

- Agent runs: two per task are recorded in `evals/agent/runs/` — the first,
  then a second after compact envelopes, a 6 KB `capabilities` index,
  duplicate-key candidates, and plain piped help, which cut response bytes by
  88% (525 KB → 62 KB) and calls from 39 to 31. The owner still has to review
  the `unsupported_claims` counts. What the second run still shows is agent
  behaviour, not engine waste: the `duplicate-conflict` agent wrote to the
  entry it inferred although the conflict listed both and offered `ask_which`,
  and agents opted into `--pretty` or re-read `capabilities` unprompted.
- Release per [RELEASE.md](RELEASE.md).

**Done when:** selected context can be paged without omissions under a stable
snapshot; missing and truncated information are distinct; saved queries reflect
subsequent edits; analysis counts reconcile with underlying reports, including
empty and duplicate-key libraries.

### v0.9 — Library discovery and indexed search

**Workflow:** find a paper across existing collections and inspect collection-wide
coverage efficiently, without importing another copy.

- Introduce `Library` over explicitly selected `.bib` files or a declared root,
  with collections, key lookup, search and cross-file identity reports. Settle
  membership/configuration here; keep per-bibliography settings in the `.bib`.
- Expose `corpus search` and cross-file duplicate checks, retaining file/entry
  provenance and exact versus probable matching. Repeated keys across files
  do not establish work identity. Report unreadable members and changing inputs
  without claiming a globally atomic filesystem snapshot.
- Add a rebuildable `Catalogue` for bibliographic fields and abstracts, with
  documented freshness and refresh behavior. Carry bounded reads, field-scoped
  queries, match explanations and source locations into indexed search; retain
  direct reads for recovery and comparison. Files remain authoritative.
- Lift v0.8 analysis into Library rollups. Distinguish entry occurrences from
  identified works, reconcile per-file counts and expose partial-read failures.
- Test index refresh, deletion, rename and corruption recovery; measure index
  build/query/refresh cost and memory before making performance claims.

**Done when:** source locations and ambiguity survive cross-file discovery;
rollups reconcile; the index can be rebuilt without losing information; stale
results have explicit semantics and representative queries show measured benefit.

#### MCP and editor integration

Develop a query-only MCP companion against the v0.9 Library/Catalogue contract,
with bounded results and the same errors and provenance as the CLI. Derive its
schemas from the engine and test adapter parity; declare an engine compatibility
range. Add evidence reads after v0.12–v0.13. Companion publication does not gate
an otherwise complete engine release. The editor may read library-scoped data
but remains the project-scoped client, with no bibliography logic of its own.

### v0.10 — Project assembly and bibliography relationships

**Workflow:** seed a project from existing collections and maintain an explicitly
declared relationship to its master bibliography.

- Add `corpus pick` with source/entry selection, a destination preview, explicit
  group preservation/stripping/mapping, and destination identity/key checks.
  A single-entry `ref import --from` alias can share this implementation.
- Support explicit material copying with collision, missing-file and rollback
  rules. Prepare and validate outputs before mutation; never silently overwrite
  target materials or move originals. Report source-to-destination mappings,
  operation counts, skips and conflicts, guarded by input/output fingerprints.
- Declare master/subset relationships separately from Library membership and
  arbitrary copying. Propagate key renames through declared mirrors with
  previews covering TeX references and materials. Check all participating files
  before applying and reuse transaction/recovery mechanisms.

**Done when:** project assembly leaves sources intact; accepted copies and
renames preserve declared relationships and references; conflicting mirror
edits and interruptions cannot leave unreported partial changes. Do not expose
material copying until its recovery guarantees are tested.

### v0.11 — Curation decisions and bibliographic consistency

**Workflow:** resolve duplicate and metadata problems once, record deliberate
exceptions, and have later maintenance respect those decisions.

- Add field-level merge choices and provenance using existing identity evidence.
  Validate choices against source fingerprints; preserve materials and references
  and keep unresolved conflicts blocking. Extend this contract to annotations
  when v0.13 introduces them.
- Add `distinct-from`, `keep-key`, `no-fetch` and enrichment opt-outs to the
  directive grammar. Expose reasons, specify affected commands and explicit
  overrides, and handle renamed or missing targets.
- Ship a versioned journal abbreviation dataset with source/licensing records,
  justified extra styles and explicit ambiguous-name behavior. Keep data and
  algorithms independently inspectable; preserve existing defaults.
- Add individually opt-in HTML entity/markup conversion, Unicode/LaTeX
  conversion and LaTeX tidying to `normalize`. Document lossy cases and operation
  order; `format` remains layout-only. Include explicit new-entry type spelling
  for JabRef-style libraries without silently respelling existing entries.

**Done when:** chosen values are attributable, stale merge choices are refused,
commands honor exceptions, journal data is distributable and tested, and
normalization preserves untouched bytes with documented loss where applicable.

### v0.12 — Material acquisition and source-linked extraction

**Workflow:** bring existing papers into a research library, identify their
references, and retrieve passages tied to the exact material read.

- Add `asset link`: match existing files by key and then explicitly requested
  filename heuristics. Preview links, keep competing candidates unresolved,
  and never silently overwrite or relocate materials.
- Introduce optional PDF/TeX extraction. Keep rebuildable derivatives separate
  from originals and record source hash, extractor/version, options and usable
  locations: PDF page indices and available printed labels, or TeX paths and
  lines/sections. Detect staleness and report scanned or incomplete text honestly;
  OCR remains a later optional capability.
- Expose bounded passage retrieval independently of the Catalogue, then extend
  indexed content search through these derived records. Return source locations
  for checking quotations, equations and methods. Source text is data, not
  executable instructions; distinguish excerpts from external interpretations.
- Add `ref from-pdf`: embedded BibTeX/XMP, then extracted identifiers, then
  explicitly requested provider resolution. Reuse extraction and retain
  candidate evidence. Add offline `ref from-text` with recognized fields and
  unresolved text; existing `ref find` remains the online lookup path.
- Extend the provider registry as one acquisition workstream: NASA ADS bibcodes,
  RePEc/IDEAS handles, MathSciNet review numbers, institutional URNs starting
  with DiVA, SciELO, and additional ISBN coverage (evaluate WorldCat first).
  Verify supported access, credentials, mapping and recorded fixtures for each.
  Google Books and Library of Congress remain excluded; reconsider OpenReview
  only with supported access, without bypassing bot challenges.

**Done when:** accepted links and imports are reviewable and ambiguity remains
explicit; returned passages identify their material hash and supported location;
derivatives can be rebuilt without modifying originals. Each shipped provider
passes offline fixtures and a separate access check. Record an explicit decision
for every provider candidate; unavailable access defers that adapter, not the
whole release. No stub or invented metadata counts as supported ingestion.

### v0.13 — Evidence-linked research annotations

**Workflow:** record “uses a Markov approximation” with its supporting passage,
author, and review status, then find it after the citation key changes.

- Define a versioned, inspectable annotation format outside bibliographic fields.
  Settle its storage and stable reference/material identity before exposing writes.
  Annotations are authored records; unlike extracted text, they cannot be
  discarded and reconstructed from the PDF.
- Distinguish verbatim excerpts, agent interpretations, and human-authored notes.
  Record creator, evidence anchors, material version, and explicit review state;
  human review does not automatically mean a claim is scientifically correct.
- Provide read, preview, write and validation operations; preserve links through
  key renames and handle merges, removal, and material replacement explicitly.
  Mark stale or orphaned evidence rather than silently retargeting it.
- Let external tools create interpretations. Pynakes validates structure and
  references, not whether a paper supports a scientific conclusion. Define
  export/scrub behavior for private annotations before sharing is supported.

**Done when:** annotations remain attributable and retrievable after renames;
changed sources invalidate anchors visibly; unreviewed interpretations cannot
be mistaken for verbatim excerpts or human-reviewed records in the envelope.

### v0.14 — Resumable plans and execution receipts

**Workflow:** resume a collection-maintenance job after interruption without
repeating completed downloads or losing track of what changed.

- Build on `corpus batch` with persisted, versioned plans: operations, inputs,
  fingerprints, dependencies, permitted network steps, and expected outputs.
  Keep deterministic bibliography batches atomic within their existing scope.
- Persist receipts for completed, failed and pending steps, with output hashes
  and operation-level counts. Resume by checking recorded outputs and current
  preconditions, not by trusting that a previous process finished a write.
- Separate network acquisition from applying retrieved results. Record what was
  actually obtained; changed provider data or a changed source must invalidate
  affected expectations. An earlier approval covers only its stated plan and
  conditions, not arbitrary changes discovered during a retry.
- Document partial completion and recovery for filesystem/network steps; do not
  describe the whole workflow as atomic. Use existing fetch and material
  transaction mechanisms rather than a second write implementation.

**Done when:** interruption tests cover before/after writes and downloads;
retries neither duplicate successful work nor apply stale plans, and receipts
explain both completed changes and remaining work without parsing diffs.

### v1.0 — Pin the exercised public API

**A reference management engine with a dependable workflow from reference
acquisition through evidence-linked research to project bibliography and release
copy.** Freeze the public Python API after the smaller releases have exercised
its bibliography, Library, material, and evidence boundaries. The CLI keeps its
existing deprecation promise throughout.

- Exercise complete workflows for acquisition, curation, project assembly,
  manuscript citation maintenance, evidence retrieval, and public release.
- Document which records are authoritative and which are rebuildable, the
  compatibility/migration rules for persisted annotations and plans, and the
  limits of recovery across network and filesystem operations.
- Review the outstanding editor interoperability issues before pinning affected
  engine behavior. Complete the scheduled v0.8–v0.14 workflows before launch.
  Bimas and MCP publication are independent; provider candidates deferred from
  v0.12 must have a documented disposition, not an implied implementation claim.

**Done when:** these workflows and API boundaries have recorded acceptance
results, all applicable checks pass, compatibility and migration policies are
published, and 1.0.0 is on PyPI. No additional feature bundle belongs in the
launch release.

---

## Beyond 1.0

The data mechanisms below extend pynakes; they are not a single scheduled
release or a requirement to ship 2.0.
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
  PDF ingestion in v0.12. This one modifies a material rather
  than the `.bib`, so it needs the same preview-and-approve treatment as a
  bibliography edit and must never be implied by another command.
- **Further material formats** — EPUB metadata extraction alongside PDF, as
  open-access monographs become common. Lower priority than PDF by usage, and
  it shares the v0.12 extraction pipeline rather than duplicating it.
- **Optional semantic retrieval** — RAG/embeddings and richer agent memory
  built on the source-linked extraction and annotation contracts above. Keep
  model-specific dependencies optional, results attributable, and semantic
  judgments outside automatic bibliography mutation.
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

Schedule these as separate additive releases after their designs are accepted.
Use a new major version only when a compatibility change requires one. Bimas
begins once the integration boundary is pinned; it is not an engine release gate.

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
  need is real, but the planned MCP companion and the editor in v0.7 both address
  it over boundaries that already exist, without a background service listening
  on a well-known port.
