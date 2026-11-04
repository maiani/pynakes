# pynakes development plan

pynakes is a **reference management engine for BibTeX and BibLaTeX bibliographies and their research materials**,
exposed through a Python library and CLI. The product ambition is to support a
research library throughout its life: reference acquisition and curation,
material provenance, project bibliographies, manuscript citation maintenance,
and public release copies.

The current foundation is authoritative `Bibliography` (`.bib`) files, optional
Pinax materials, bounded research reads, and a direct-read `Library` with guarded
routing of supplied records. Initial PDF recovery links external originals;
joining recovery, routing and managed material ingestion is the immediate gap.
A rebuildable `Catalogue`, a long-lived engine service, and source-linked
evidence build on these contracts.
Applications for capture, reading, graphical interaction,
and sync consume the same engine; they share its parser, data model and review
contract. Planned integrations are tracked here without being advertised as
implemented features.

This document is the **road to 1.0** and possible extensions beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### Standing commitments

0.7.0 moved the CLI to beta; 0.8.0 added research context, saved queries and
bibliography analysis. Their scope is in [CHANGELOG.md](CHANGELOG.md). What
they settled still constrains every later release.

#### The beta promise

The **CLI** is in beta: its command syntax, options, JSON envelope, exit codes,
and error codes are a contract that changes only through a documented
deprecation. The Python API keeps its current status — the intended public
surface in [docs/guides/public-api.md](docs/guides/public-api.md), with breaking
changes documented but not deprecated — until 1.0 pins it.

- **A frozen surface, with deprecation.** Removing or renaming a command,
  option, envelope key, `action` value, exit-code meaning, or error code takes
  one minor release in which the old form still works and emits a structured
  warning (`{"type": "deprecated", "old": ..., "new": ...}`) before it is
  removed. Additions may ship in any minor release; patches fix bugs only.
- **No known data-loss bugs.** No command silently changes bytes outside the
  entries it edits, writes an unparseable file, reports a failed write as a
  success, or leaves a multi-file operation half-applied.
- **No tracebacks.** Every failure is a JSON error carrying a catalogued code.
- **Tested where advertised.** Every operating system and Python version the
  package metadata claims runs the suite in CI, as do the declared dependency
  floors.
- **Docs describe the real surface**, with a command reference generated from
  the live CLI.

#### Standing decisions

- The Python API is its own interface: a `Bibliography` method no command calls
  is not dead code for that reason alone.
- `--strict` gates a read-only command (`lint`, `verify`, `dedupe check`,
  `asset check`) or the completeness of `asset fetch`, always
  emitting the full envelope before exiting 1; `--check` is a transform's
  check mode
  (`format`, `scrub`). `-f` is `--file` everywhere, `--field` is a
  `name=value` assignment, and `--out PATH|-` is the one output flag.
- Settings are named for the command that applies them and `lint` verifies
  them. A setting for one entry is a directive comment above it
  (`% pynakes: verb args -- reason`), never a `pynakes-*` field; a new
  directive adds a word to `ref directive`, not a command.
- Git calls pynakes; pynakes does not call git. Git integration takes the form
  of drivers git invokes with the file versions in hand (`.gitattributes`
  `diff=`/`merge=`), so the engine still only sees files. No command reads
  repository state implicitly: output never depends on a dirty tree, the index
  or history, and the one planned exception, a revision-scoped selection, runs a
  read-only `git` subprocess only when its flag is passed, as `--online` gates
  the network. Locating the project boundary by a `.git` marker (key renames
  that rewrite TeX citations) is a filesystem check, not a git read. No git
  library dependency.
- No project-level config (`pynakes.toml`, `[tool.pynakes]`): each `.bib` carries
  its own formatting and operation settings. The Library manifest declares
  membership, an optional Catalogue location and cross-member routing policy.
  Routing belongs to the Library; it is not another bibliography setting.
- A personal Library and a project bibliography have separate ownership and
  lifetimes. Shared project copies need explicit selection and synchronization;
  they do not inherit private notes, paths or materials automatically.
- New Library additions have one owning member. Transversal collections such as
  books can take priority over subject collections; groups, keywords and search
  express overlapping interests. Existing duplicate occurrences remain readable
  and diagnosable. Routing never silently repartitions existing members.
- PDFs belong to the Library as Pinax materials when managed ingestion is
  requested. Initially, each member owns a distinct relative Pinax root beneath
  the Library directory. Several bibliographies must not independently mutate
  one shared store. Cross-member relocation needs a separate identity and
  recovery contract before it can move references and their materials.
- The library's key style is never inferred silently. `keys pattern` proposes
  a pattern, `metadata set` stores it, and `ref import` only warns. Keys
  change only after the pattern is stored.
- Progress for people goes to stderr as plain lines, so captured output keeps
  it. A `--json` run writes nothing to stderr, because agents often read
  `--json 2>&1` as one JSON document.
- `normalize` owns value conventions (title protection, text encoding);
  `fields` only edits fields. `keys usage` stays apart from `tex scan`: one
  key's occurrences in the sources given, with no `.bib`, is a different
  question from a used/unused/missing report for a whole bibliography.
- Group-tree commands edit the hierarchy, not entries, unless asked:
  `groups rename --members` moves memberships, and `groups remove` keeps them.
- Keep the shared public `pynakes.analysis` API and distinct CLI views: bounded
  summaries in `analyze`, full networks in `coauthors`. See the
  [analysis boundary](docs/guides/architecture.md#analysis-boundary) for ownership
  and identity semantics; future Library rollups must preserve them.
- BibLaTeX extended names (`family=..., given=...`) are not parsed yet. Add any
  future support to `authors.py` so all consumers share it. Identity corrections
  remain ordinary reviewed edits or future v0.13 directives. Editors as
  co-authors (with an explicit role choice), per-year pair counts beyond
  first/last year, and fractional counting remain unscheduled extensions.
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

#### Editor track

The VS Code extension is versioned on its own; 0.1.0 is an **alpha**
pre-release with no compatibility promise of its own, consuming nothing but the
beta envelope. Its scope is a bibliography belonging to a document or
repository being edited, not library-scoped exploration (see
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
  - *Opening materials with the system handler:* a `file`-field path is handed
    to the OS; on Windows an executable named by an untrusted `.bib` could run.
    Decide on an allow-list or a confirmation.
  - *Fetch progress:* the engine streams per-entry progress with
    `asset fetch --progress jsonl` (also under `--json`); the view does not yet
    consume it or offer `--access institutional`.

The editor consumes the 0.8 group memberships, entry-field schemas and selection
exports. Pending companion changes add citation insertion/completion, type-aware
creation with generated keys, selected-key regeneration and copy/export actions;
see [editor/CHANGELOG.md](editor/CHANGELOG.md). The engine additions for citation
grammar and headless generated-key creation must ship with that companion.
Host-level acceptance still needs interactive VS Code checks of these workflows.
Local attachment, exact lint repair actions, and identifier discovery for an
existing entry remain separate engine work.

**Editor alpha gate**: the `.vsix` is published as a pre-release; its checks run
in CI against the beta envelope; every gap it surfaced was closed in the engine
rather than worked around in the client.

---

### Release approach

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
| 0.9 | Settled command surface, bibliography links, documentation on Zensical | Existing reads and checks |
| 0.10 | Native PDF ingestion and Zotero-backed Library integration | PDF evidence, routing, Pinax and common bounded reads |
| 0.11 | Library discovery, measured indexing and engine sessions | The two v0.10 Library workflows and Bibliography lifecycle |
| 0.12 | Project assembly and synchronization of linked bibliographies | Library, declared links and guarded writes |
| 0.13 | Curation: merges, directives and normalization | Existing editing and identity APIs |
| 0.14 | Broader material linking, source-linked extraction and providers | Managed ingestion, Pinax and bounded reads |
| 0.15 | Evidence-linked research annotations | Material locations and hashes |
| 0.16 | Generalized resumable plans and execution receipts | Import recovery, batch and material operations |
| 1.0 | Pin the exercised API and end-to-end contracts | Accepted workflows below |

The two v0.10 goals are **native PDF ingestion** and **Zotero integration**.
Prioritize the useful Zotero read/select/project workflow first, while developing
native managed ingestion against the same identity, material and review contracts.
Neither backend requires migrating into the other. The native import ledger and
Pinax adoption move forward from v0.14/v0.16 because safe archive migration needs
them now. Catalogue indexing, aggregate analysis, services and GUIs do not gate
v0.10. MCP and editor releases remain independently versioned companions.

#### Checks and evaluation throughout

- Every release has correctness tests, documentation, a changelog, and the
  applicable checks from `AGENTS.md`: full engine tests with coverage ≥90%,
  Ruff lint/format, ty, strict docs, and artifact checks for releases. Changed
  editor code also passes compilation and its tests.
- Keep the **agent evaluation suite** (`evals/agent/`) separate from
  deterministic contract tests. Use invented or public historical fixtures and
  record task, engine/model versions, tool calls, outcomes, and evaluation
  conditions. It covers ambiguous references, duplicate conflicts, concurrent
  edits, bounded reads and co-author interpretation; add cross-library assembly
  and evidence-grounded comparisons as their engine support ships. Mock
  provider responses for reproducible runs; keep explicit live-network
  exercises separate.
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

### v0.9 — A settled command surface, bibliography links and documentation

**Workflow:** declare and validate a manuscript bibliography's relationship to
its source bibliography, on a command surface and documentation settled before
Library and the service layer build on them.

The completed scope is recorded under `[0.9.0]` in
[CHANGELOG.md](CHANGELOG.md). Release validation and the historical agent
assessment are recorded in [RELEASE.md](RELEASE.md). The final review includes
institution-aware keys, sorted insertion, settings discovery, optional
proper-name protection and all-capital author warnings.

### v0.10 — Native PDF ingestion and Zotero integration

**Workflows:** recover a local PDF archive into a private file-backed Library
with reviewable metadata, routed bibliography ownership and portable Pinax
materials; or use Zotero as the authoritative Library and select references into
a project bibliography through pynakes. Both workflows are release goals.

The direct-read file Library, routing of supplied metadata, and initial
single-bibliography PDF importer are implemented on the development branch; see
[CHANGELOG.md](CHANGELOG.md), [Library routing](docs/guides/library-routing.md)
and [PDF import](docs/guides/pdf-import.md). The
[backend design](docs/design/library-backends.md) is accepted and
[initial live Zotero checks](docs/design/zotero-local-api-study.md) exercise public
APIs; a production adapter and end-to-end native migration remain unimplemented.

#### Order of work and release gates

1. **Zotero-backed Library, first useful slice.** Wrap existing file reads behind
   the common read boundary, then add an explicit local Zotero connection.
   Preserve source-native records and instance-scoped identities/revisions;
   provide bounded enumeration, record reads, collections and material discovery.
   Test concurrent paging, disabled/unavailable access, unsupported versions and
   missing files. No private database access or cloud fallback.
2. **Selection into a project.** Use either backend to select supported records,
   review conversion losses and stage a project `.bib` through `Bibliography`.
   Keep project citation keys independent of source IDs. Persist source mapping
   and accepted values so repeat selection is idempotent and refresh distinguishes
   source changes from project edits. This bounded workflow moves forward from
   v0.12; general project assembly and two-way synchronization remain later.
   Zotero source reads do not require Pinax copies or write authorization.
3. **Native PDF ingestion.** Complete the acquisition sequence below: evidence,
   metadata review, variant-aware adoption, guarded routing, a durable ledger and
   interruption recovery. Keep ambiguous/unidentified PDFs pending without
   invented bibliography entries. Ship the native migration gate in this release.
4. **Private archive rehearsal.** Use an explicitly authorized old PDF archive
   to exercise both routes. First preserve PDFs in a dedicated Zotero review
   collection, with stored-byte verification and source-occurrence receipts;
   bibliographic recognition is a separate, reported outcome. Reuse locally
   cached recovery evidence, preserving uncertain candidates. Exercise native
   ingestion as its guarded operation becomes available. Private data and
   credentials never enter the engine repository. This operational migration is
   not proof that a reusable adapter or native ingestion feature has shipped.

**Done when:** the Zotero read/select/project gate and native migration gate both
pass with reproducible synthetic coverage and separately recorded live trials.
Every selected archive source is accepted, explicitly excluded, duplicated by
bytes, or durably pending with a reason. Verify hashes, repeat runs, stale-source
handling and recovery. Unresolved metadata may remain; it must not be hidden by
an attachment count or reported as completed reference recovery. State tested
Zotero versions/platforms and unsupported capabilities explicitly. General
Zotero writes, automatic recognition, annotation transfer, two-way sync, index
performance and a GUI are not release prerequisites.

#### Native sequence: PDF archive to managed Library

Local import trials establish useful failure classes, not a general recovery
rate. Keep their source inventories, extracted text, candidate bibliographies
and provider caches in the private Library. Public tests use invented fixtures
and recorded synthetic provider responses. Preserve the existing PDF command's
external-link workflow while adding managed ingestion explicitly. Each new API
and CLI option must follow the setting/override conventions in `AGENTS.md`;
routing policy stays in the manifest. Keep capabilities, error codes and the
generated command reference synchronized as each slice ships.

The engine backlog is:

| Gap | Required outcome |
| --- | --- |
| Unrelated identifiers on cover sheets or reference pages | Attribute identity evidence to the document; retain competing candidates for review |
| Mathematical and typographic title differences | Compare equivalent representations without relaxing identity checks broadly |
| Complete-looking embedded metadata with weak values | Validate type, names and dates; offer attributable field choices |
| Books with identifiers beyond the opening pages | Bounded front-matter inspection and ISBN/edition evidence |
| Recovered records still linked to external files | Guarded routing plus portable Pinax copies and provenance |
| Failed, unidentified or interrupted imports | Persistent accounting and safe retry without fabricated records |

**1. Improve document identity evidence.** Extend the inspection evidence model
before changing acceptance rules.

- Retain page and available block/region locations for candidate identifiers and
  titles. Distinguish the document's citation/title block from publisher
  recommendations, reference lists and other embedded works. Do not assume
  everything before an abstract describes the document itself.
- Keep included and rejected evidence with reasons. Multiple supported works,
  contradictory metadata or failed competing lookups still require review;
  neither the first DOI nor a provider's successful response establishes identity.
- Add comparison-only normalization for Unicode/LaTeX mathematical notation,
  ligatures, spacing and line-break hyphenation. Preserve original title fields
  and evidence. Do not solve mismatches by globally lowering a similarity cutoff.
- **Gate:** invented positive fixtures cover equivalent mathematical titles and
  layout variations; negative fixtures cover similar titles, recommendations,
  reference-list identifiers and genuinely different works. Every automatic
  choice has inspectable supporting locations; uncertain cases stay unwritten.

**2. Recover and review metadata, including books.** Build on existing providers
and lookup rather than introducing another resolution stack.

- Separate field presence from metadata quality. Validate embedded author/editor
  structure, publication dates and entry type; preserve questionable values as
  evidence instead of guessing author splits or treating PDF creation dates as
  publication dates. A successful lint run is not identity certification.
- Provide explicit provider comparison/enrichment for embedded records. Online
  mode currently accepts complete-looking embedded records before resolving
  identifiers; new review behavior must expose disagreements and chosen field
  provenance without silently replacing existing metadata.
- Add bounded front-matter inspection beyond the initial two-page window, with
  documented page/text/time/size budgets and structured limit failures. Measure
  peak memory; an input-size limit and timeout are not a hard memory bound. Extract
  and checksum ISBNs, reuse the existing ISBN resolver, and distinguish editions,
  volumes and print/electronic identifiers. Several ISBNs need evidence or a
  reviewed choice, not a first-match rule.
- Connect existing title/reference lookup as an explicitly requested online
  fallback. Preview the query and candidate evidence: sending title/author text
  is a different disclosure from identifier-only lookup. No filename guessing or
  page-count rule may silently classify a document as a book.
- **Gate:** book fixtures place identifiers after page two and include conflicting
  editions and irrelevant ISBNs. Metadata disagreements remain reviewable; an
  accepted book type triggers the transversal book rule before subject rules.
  OCR and repair of corrupt originals remain optional later work, not migration
  prerequisites. Password, unreadable-file and resource-limit failures remain
  distinguishable and leave the source untouched.

**3. Settle material adoption and variant identity.** This is a prerequisite for
copying any accepted PDF into Pinax, independent of recovery quality.

- Distinguish source occurrence, byte identity (SHA-256), bibliographic work and
  material role. Identical bytes can be recognized without merging distinct
  work records; different bytes for one work must remain distinguishable.
- Define an explicit unclassified role and multiple variants within a role.
  An annotated PDF must not overwrite an unannotated copy, or vice versa. Keep
  published/preprint distinctions and unresolved work relationships explicit.
  Decide the manifest/addressing schema and migration of existing Pinax layouts
  before exposing it; retain citation-key lookup as the public entry point.
- Implement general local-file adoption using Pinax's write/provenance helpers.
  Copy unchanged bytes by default, check source and destination hashes, record
  provenance, detect collisions and recognize an already-adopted artifact.
  Never rename, delete, repair or rewrite the external original implicitly.
- Use distinct member-owned stores and relative attachment links. Define key
  rename behavior for all variants and manifest records. A shared Library store
  or member-to-member move is a subsequent operation, not an assumption hidden
  inside import.
- **Gate:** test repeated bytes, multiple annotated variants, unknown roles,
  missing roots, destination collisions and key renames. Accepted materials
  retain their original hashes and are addressable after relocating the entire
  Library. Preserving embedded annotation bytes is required now; extracting
  annotations into the v0.15 model is separate work.

**4. Compose a guarded Library acquisition operation.** Reuse PDF inspection,
provider resolution, Library routing and Bibliography staging. Settle the Python
entry point and CLI spelling before exposing them; do not duplicate bibliography
logic in a migration script or client.

- Produce one reviewable plan with source hashes, identity evidence, metadata
  choices, generated keys, destination and routing reasons, bibliography diffs,
  material copies and provenance changes. Stage only candidates whose identity,
  metadata choices and destination are sufficiently resolved.
- Check work/key collisions across all members and other accepted records in
  the same batch. For an existing work, offer attachment to its current owner;
  do not add a second entry just because new routing rules choose another file.
  Probable matches and conflicting identifiers need review before attachment.
- Apply the selected member's key, dialect and normalization settings. Explicit
  destination overrides and priority ties keep the existing routing semantics.
  An inbox fallback applies to an identified reference without a matching route;
  it must not turn an unidentified PDF into invented bibliographic metadata.
- Recheck source PDFs, manifest/rules, membership, destination and relevant
  existing materials against the reviewed plan before mutation. Incomplete
  Library reads block uniqueness-dependent writes. A preview must not create
  destination files, Pinax directories or provenance records.
- Define the commit unit and recovery protocol for bibliography, material bytes
  and Pinax manifest writes. Prepare outputs before mutation, with rollback or
  a durable recovery journal for interruption. Several filesystem renames are
  not a globally atomic transaction. Report completed and pending units honestly.
- **Gate:** fixture imports route books and unmatched articles to separate
  members, attach variants to existing owners and reject duplicate/stale plans.
  Failure injection at each write boundary proves recovery without lost bytes,
  dangling accepted links or unreported partial changes. Retrying completed
  units produces no duplicate entries, copies or provenance records.

**5. Persist a minimal import ledger and review queue.** Ship this with managed
Library ingestion; v0.16 generalizes it to other operations.

- Inventory every selected source, including unsupported formats, with its hash
  and extraction/version information. Record candidates, resolution evidence,
  explicit selections, routing reasons, plan fingerprints and resulting
  bibliography/material hashes. Non-PDF files stay accounted for and are never
  executed. Do not require a fake citation key to retain an unresolved source.
- Distinguish candidate recovery, review acceptance and committed ingestion in
  reports. Track pending, ambiguous, failed, already-present and committed
  outcomes separately, with reasons and actions available to the reviewer.
- Resume from verified receipts and current hashes. Changed source bytes,
  metadata choices, rules or members invalidate affected plans; retain previous
  evidence without applying stale decisions. Make extraction/provider caches
  disposable, while explicit decisions and write receipts remain authoritative.
- Preserve offline operation and explicit network scope. Cached responses may
  be reused with provenance; uncached lookups require the requested online mode.
  Retry must not silently widen the selected sources, queries or providers.
- **Gate:** interrupt and resume a mixed batch, modify a source and a routing rule,
  remove a cache, and retry failures. Every source remains accounted for; no
  completed write repeats and no stale selection applies. Persisted formats are
  versioned and documented, with private paths/text excluded from public exports.

**6. Rehearse migration and restoration.** Run deterministic synthetic end-to-end
fixtures first, then separately authorized private trials. Real inventories,
metadata and reports stay outside the software repository.

- Start with a reviewed cohort covering each failure class and material role;
  expand only after the preceding gates pass. Keep live provider availability
  checks separate from reproducible correctness tests, and do not extrapolate a
  diagnostic sample into a collection-wide success rate.
- Reconcile all selected sources against committed materials, byte duplicates,
  explicit exclusions and outstanding review/failure items. Check bibliography
  links, Pinax manifests, hashes, routing reasons and unchanged source originals.
  A fully accounted-for batch can still have unresolved work; report both facts.
- Restore a Git-managed Library at a different root with the original archive
  unavailable. Demonstrate working relative links for restored PDF bytes and
  explicit missing-material diagnostics for a metadata-only clone. Document
  ordinary Git, optional LFS and external material backup choices without
  making the engine stage, commit, configure remotes or push anything.
- **Migration gate:** accepted references have one owner and intact, attributable
  materials; retries and restoration work; every unresolved source has a durable
  review record. No claim of a complete archive import while pending items
  remain. Keep the source archive intact after the rehearsal.

#### Accepted Library backend design

The [accepted Library backend design](docs/design/library-backends.md) defines
a common read interface over our file-backed Library and an optional Zotero-backed
Library. In the latter mode Zotero remains authoritative: users need not migrate
their collection into `.bib` members or Pinax to select references for a project.
The architecture is agreed; implementation, exact public signatures and persisted
schemas remain pending. Existing file-based APIs keep their current behavior.

Start with a wrapper around existing reads, synthetic adapter fixtures and a
disposable-profile compatibility experiment. This read-only implementation track
is the first implementation priority within the two-goal v0.10 release. Keep
placement, native edits and material writes as distinct capabilities, and preserve existing Bibliography contracts.

Zotero support is conditional. Test the exact client/API versions, completeness,
unsynced edits, identity, concurrent paging and material access before claiming
compatibility. Restrict support or drop the live backend if reliable behavior
requires weakening core guarantees or depending on private APIs. Native Library
development continues independently. The design gives acceptance and stopping
criteria; no full reference-management framework or two-way sync is committed.

#### Optional transfer: Zotero into the file-backed Library

After both v0.10 gates pass, consider explicit one-way acquisition
from Zotero as a subsequent workflow. This is an optional transfer
workflow, separate from using Zotero directly as the Library. For this workflow,
accepted member bibliographies, Pinax materials and persisted review records are
authoritative. Zotero is the capture/source application. The transfer reuses the
acquisition pipeline above and does not require the Catalogue or service layer.

- Start with selected items from the supported
  [Zotero local API](https://www.zotero.org/support/dev/web_api/v3/local_api).
  Declare and test supported client/API versions; report unavailable clients or
  disabled access explicitly. Keep source access read-only, with no direct
  SQLite manipulation, cloud-sync requirement or background polling.
- Map metadata into the existing staged review, identity checks and routing.
  Preserve source library/item identity, instance context where applicable,
  versions and the last accepted source values independently of citation keys.
  Repeated imports recognize previously accepted items; source changes produce
  reviewed proposals rather than overwriting local edits. Source deletion does
  not delete a Library entry or its materials.
- Treat Zotero collections as overlapping memberships, not automatic ownership
  of member files. Preview tag/collection mappings; explicit Library rules still
  choose one home. Report unsupported fields and item types without silently
  claiming lossless conversion. Notes and other private content need explicit
  selection and a documented destination.
- Adopt selected attachments through the same guarded Pinax copy operation,
  preserving originals and variants. Missing or unavailable files remain visible
  in the review queue. Zotero stores its own annotations separately from PDF
  bytes: preserve them through an explicit supported export or structured import,
  or report them as not transferred. Copying the original PDF alone must not be
  reported as complete annotation migration. See
  [Zotero annotation storage](https://www.zotero.org/support/kb/annotations_in_database).
- Keep optional Better BibTeX exports as source snapshots outside authoritative
  member files. Its [automatic export](https://retorque.re/zotero-better-bibtex/exporting/auto/)
  rewrites an export from Zotero; it is not a merge of edits made in both tools.
- **Gate:** synthetic fixtures cover repeat import, changed source metadata plus
  local edits, citation-key changes, overlapping collections, duplicate works,
  missing attachments and annotations. Accepted items remain usable with Zotero
  unavailable; unsupported or omitted content is accounted for. Validate API
  compatibility separately against a disposable local Zotero library.

Two-way synchronization is deferred and unscheduled. It needs a separate design
for field ownership, synchronization baselines, conflicts, deletions and material
or annotation changes. The first bridge never writes back to Zotero. Reusing its
capture workflow does not commit pynakes to implementing a browser extension,
reader, mobile application or hosted synchronization service.

#### Subsequent Library material moves

After ingestion is reliable, add a reviewed move between member bibliographies.
Preview the destination key and settings, material/variant mappings, provenance,
links and entry comments; check both members and stores before writing. Preserve
material identity and recover interrupted moves. A rule edit only changes future
routing until an explicit repartition operation is requested. Shared storage
independent of member keys needs its own design; the initial implementation must
remain safe with separate roots. The minimal project selection workflow belongs
to v0.10; broader project copies and synchronization remain the separate v0.12 workflow.

#### Command surface: direction, not destination

The read-side direction remains shared commands over Library inputs; routed
writes refine the boundary. The end state is revisited as each phase lands:

- **Reuse operations across input scopes.** An operation belongs to the
  Library only if it needs what a Library adds: membership, cross-member work
  identity, destination routing or the Catalogue. Commands that can read
  several files also accept a library through a `--library` option naming a
  manifest or member files, rather than gaining `library` twins: `search`,
  `ref show`, `dedupe check`, `analyze`, `coauthors`, and the multi-file
  writers below. Several positional files on `lint`, `verify` and
  `dedupe check` keep meaning "check each file on its own"; they never
  silently become a library.
- **A small `library` group for Library-owned decisions.** `library add`
  already routes supplied metadata into one member. Acquisition will compose
  this placement contract with existing recovery and material APIs. Manifest
  creation, member diagnostics and Catalogue refresh remain planned. Every
  bibliography edit still goes through `Bibliography`; multi-member workflows
  need explicit coordination and recovery.
- **No multi-file group.** `combine`, `split` and `batch` are top-level commands:
  they use nothing a library adds. v0.12's `pick` follows the same rule: bare
  source files, optionally given as a library.

### v0.11 — Library discovery, indexing and engine sessions

**Workflow:** keep a library open across many operations, so an interactive
client pays for parsing and full-library checks once rather than on every
action, and start the MCP companion and the library-scoped client from
`pynakes` itself.

The service layer opens a `Library`, and the MCP companion is built against
the Library read contract, so both follow the release that settles that
contract. A Catalogue is an optional optimization, not a service prerequisite.
The 2026-10 measurements also put full-library work, not process startup, at most
of a large refresh; what a
session saves depends on recomputing only what an operation touched.

#### Discovery beyond the v0.10 minimum

- Extend bounded Library search and cross-file identity reports, preserving
  occurrence provenance, exact versus probable matches and partial-read errors.
  Zotero collections remain overlapping memberships; native routing remains
  single-owner placement. Define common query semantics before pushing filters
  into either backend.
- Lift bibliography analysis into Library rollups. Count identified works rather
  than duplicate occurrences; retain all source locations and reconcile counts.
- Measure multi-library read cost and memory before adding a rebuildable
  `Catalogue`. Test freshness, deletion, rename and corruption recovery. The
  selected backend remains authoritative; an index is derived. Direct reads and
  service sessions must remain usable without this optimization.

#### Engine service layer

One long-lived, in-process service over `Library` and `Bibliography`, which
every interactive interface adapts rather than reimplementing. The MCP companion
needs a long-running process anyway; the library-scoped GUI needs one to be
responsive. Neither defines the server: both are adapters over this layer.

- **Sessions.** Open a library once and keep it parsed. A cached file is reused
  until its fingerprint changes; a change made outside the session is detected
  (`externally_changed`) and reloaded, never silently overwritten. Writes keep
  today's lifecycle — stage, preview, diff, then commit guarded by the source
  digest — with the same errors, codes and provenance as the CLI.
- **Incremental results.** An operation reports what it changed (entries added,
  removed, modified or re-keyed, and metadata), and lint, group, citation and
  material insights are recomputed for the entries it touched rather than the
  whole library. This is what a session saves over a process per action; the
  2026-10 measurements put full-library work, not startup, at most of a large
  refresh.
- **Adapters.** The MCP companion (MCP over stdio, query-only tools); the
  `pynakes gui` host (local HTTP/WebSocket, reads and writes, guarded by a
  per-launch token because it can write files); and later a stdio JSON-RPC
  adapter for the VS Code extension, which removes its per-action process
  startup. Text typed directly into the extension's buffer still needs a
  re-read, since that edit bypasses the engine. Adapters carry the JSON envelope
  where their protocol allows and are tested for parity with the CLI.
- **No hidden behaviour.** A session performs no network I/O beyond what the
  equivalent CLI call would, keeps ordering deterministic, and never writes
  without an explicit commit.

**Done when:** a session and the CLI produce the same results and errors for the
same operations; external changes and stale previews are refused or reloaded,
never overwritten; incremental insights match a full recomputation; and open,
query and edit latency for representative library sizes is measured with
`scripts/bench_scale.py` against the process-per-call baseline.

#### MCP and editor integration

Develop a query-only MCP companion as an adapter over the engine service layer,
against the v0.10 Library read contract, with bounded results and the same
errors and provenance as the CLI. Derive its
schemas from the engine and test adapter parity; declare an engine compatibility
range. Add evidence reads after v0.14–v0.15. Companion publication does not gate
an otherwise complete engine release. The editor may read library-scoped data
but remains the project-scoped client, with no bibliography logic of its own.

**Companion launchers.** `pynakes mcp` starts the MCP companion and `pynakes gui`
the library-scoped client (Bimas). They are the documented ways in, so an MCP
client is configured as `pynakes` with the argument `mcp` and needs nothing else
on `PATH`. Both are thin launchers, not the companions themselves:

- *Dependencies point one way.* The engine never imports companion code at
  module level. A companion registers itself under a Python entry-point group
  (`pynakes.companions`), and the launcher resolves it when it runs, so each
  companion stays a separate package and later a separate repository. A
  companion may also ship its own executable for packaging or desktop
  launchers.
- *Same engine, checked range.* The launcher runs the companion in the engine's
  own interpreter, then checks the companion's declared engine compatibility
  range and refuses a mismatch before starting it.
- *Failures before start use the envelope.* A missing companion (with its
  install hint, such as a `pynakes[mcp]` extra) or an incompatible one is a
  catalogued error through `_safe`, never a traceback. Once started, the
  companion owns the process: the MCP server speaks MCP over stdio, not the
  JSON envelope, and the contract documentation names these commands as that
  exception.
- *No stubs.* The commands are always registered, and `capabilities` reports
  whether each companion is installed and compatible, so the description is the
  same in every environment and never claims a companion that is absent.
- *Their own help panel*, apart from transforms and checks. Their flags
  (transport, port, which library to open) are run mechanics, exempt from the
  flag/setting/`metadata set` triple.
- *Scope in the help text.* `gui` is described as the library-scoped client, so
  it is not mistaken for the project-scoped VS Code extension, which has its own
  entry point.

### v0.12 — Project assembly and synchronization of linked bibliographies

**Workflow:** seed a project from existing collections and maintain an explicitly
declared relationship to its master bibliography.

- Add `pick` with source/entry selection, a destination preview, explicit
  group preservation/stripping/mapping, and destination identity/key checks.
  A single-entry `ref import --from` alias can share this implementation.
- Support explicit material copying with collision, missing-file and rollback
  rules. Prepare and validate outputs before mutation; never silently overwrite
  target materials or move originals. Report source-to-destination mappings,
  operation counts, skips and conflicts, guarded by input/output fingerprints.
- Build on v0.9's bibliography links and `biblink sync`, which moves values one
  step and in one chosen direction per run. Add `--recursive` (follow declared
  links past the first, parents before children, as one multi-file plan;
  cycles stop it) and two-way sync for links declaring `both`, which needs a
  stored baseline of last-synced values to tell which side changed a field,
  the same three-way comparison the merge driver below uses. Define explicit synchronization policies for direction, field ownership/local overrides, additions, deletions
  and conflicts before offering updates. Support reviewed parent-to-child and
  child-to-parent changes where the selected policy permits them; neither role
  automatically wins. An omitted child field must not implicitly delete the
  parent's value, and a shared parent must not trigger sibling propagation.
- Propagate key renames through explicitly selected linked bibliographies with
  previews covering TeX references and materials. Check all participating files
  before applying and reuse transaction/recovery mechanisms. Validate the
  declared constraints after proposed updates and reject unresolved conflicts.
- Reuse the entry-level three-way comparison as a git **merge driver**
  (`*.bib merge=pynakes`). Merge by citation key and field: changes that do not
  overlap resolve (two branches appending entries no longer conflict), untouched
  entries keep their bytes, and genuine clashes, including one key added on
  both sides with different content, are written as explicit conflicts instead
  of a silent duplicate key. Any merge policy follows the three-forms rule.
- Add an entry-level **diff driver** (`diff=pynakes`) so `git diff` and review
  show added, removed and changed entries with their changed fields. Add a
  revision-scoped selection (entries changed since a given revision) so CI and
  pre-commit can gate only what a change touched.

**Done when:** project assembly leaves sources intact; accepted copies and
renames preserve declared relationships and references; conflicting mirror
edits and interruptions cannot leave unreported partial changes. Do not expose
material copying until its recovery guarantees are tested. The merge driver
never produces an unparseable file or drops an entry either side kept, and
`git merge` reports every conflict it leaves.

### v0.13 — Curation decisions and bibliographic consistency

**Workflow:** resolve duplicate and metadata problems once, record deliberate
exceptions, and have later maintenance respect those decisions.

- Settle enrichment value policy: apply declared normalization to incoming
  fields without changing existing values or silently enabling whole-entry
  normalization. Cover page ranges, month expressions (including user string
  definitions), DOI resolver URLs, and provenance for provider publisher names.
  Provider spelling alone is not evidence that a publisher name is wrong.
  Imports follow the same policy: the library's author format and encoding
  apply to a new entry, and provider extras such as `abstract` or arXiv's
  `updated` field are opt-in through a setting.

- Add field-level merge choices and provenance using existing identity evidence.
  Validate choices against source fingerprints; preserve materials and references
  and keep unresolved conflicts blocking. Extend this contract to annotations
  when v0.15 introduces them.
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

### v0.14 — Material acquisition and source-linked extraction

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
- Build broader source-linked extraction on the earlier managed PDF ingestion
  and inspection evidence contracts. Reuse portable attachment addressing,
  variant identity, provenance and recovery; do not introduce a second material
  adoption path. Preserve original hashes and annotations and distinguish a
  metadata-only clone from restored material storage. See
  [Git workflows](docs/guides/git-workflows.md#keeping-a-personal-library-in-git).
  Add offline `ref from-text` with recognized fields and unresolved text;
  existing `ref lookup` remains the online lookup path. Evaluate optional OCR
  with language/tool provenance, bounded resources and explicit uncertainty;
  extracted or OCR text remains a rebuildable derivative.
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

### v0.15 — Evidence-linked research annotations

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

### v0.16 — Resumable plans and execution receipts

**Workflow:** resume a collection-maintenance job after interruption without
repeating completed downloads or losing track of what changed.

- Generalize the earlier import ledger and recovery protocol, retaining its
  persisted decisions and receipts. Share schemas and recovery primitives with
  material operations instead of creating an incompatible second job system.
- Build on `batch` with persisted, versioned plans: operations, inputs,
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
  Include an interrupted archive import into routed member bibliographies,
  restoration with materials at another filesystem root, and a project export
  that preserves the personal Library's private/shared boundary.
- Document which records are authoritative and which are rebuildable, the
  compatibility/migration rules for persisted annotations and plans, and the
  limits of recovery across network and filesystem operations.
- Review the outstanding editor interoperability issues before pinning affected
  engine behavior. Complete the scheduled v0.9–v0.16 workflows before launch.
  Bimas and MCP publication are independent; provider candidates deferred from
  v0.14 must have a documented disposition, not an implied implementation claim.

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
**scope**, not by feature: the project-scoped editor is the
[editor track](#editor-track), and what remains here is the library-scoped
client — one serves a bibliography belonging to a document you are editing,
the other a library belonging to no project at all. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).

- **Projections** — `combine` and `split` over a `Library` input, formalized
  as first-class **views** of it, with reconciliation.
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
  managed PDF ingestion. This one modifies a material rather
  than the `.bib`, so it needs the same preview-and-approve treatment as a
  bibliography edit and must never be implied by another command.
- **Further material formats** — EPUB metadata extraction alongside PDF, as
  open-access monographs become common. Lower priority than PDF by usage, and
  it shares the v0.14 extraction pipeline rather than duplicating it.
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
  contract. It starts with `pynakes gui`, a launcher on the terms set under
  [MCP and editor integration](#mcp-and-editor-integration); the generic command
  name outlives the working name.

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
- **Driving git** (auto-commit, staging, branching, undo through git history,
  refusing to run on a dirty tree, metadata such as "date added" read from
  `git blame`). These would make a command's effect or result depend on state
  outside the file. pynakes supplies git drivers instead; see the standing
  decisions.
- **Word processor plugins** (both: Word, LibreOffice, Google Docs). Citation
  *rendering* against CSL styles is a different problem from bibliography
  maintenance, and it is already well served. pynakes stays on the `.bib` side
  of that line; the TeX-facing half is `tex ... scan` and citation navigation.
- **Browser extension with site translators** (Zotero's several thousand
  publisher scrapers). This is genuinely Zotero's strongest feature and it
  requires a browser runtime plus a scraper corpus maintained per publisher.
  `ref import` covers the identifier- and URL-addressable path; the planned
  optional Zotero bridge imports selected records captured through its ecosystem.
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
  need is real, but the planned MCP companion and the VS Code editor both address
  it over boundaries that already exist, without a background service listening
  on a well-known port.
