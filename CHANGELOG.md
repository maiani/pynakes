# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `dedupe merge --key` merges only the duplicate clusters containing the named
  citation keys, leaving every other cluster in the file untouched. Merging was
  all-or-nothing, which is the wrong shape for the decision it encodes: judging
  two records to be the same work is done one pair at a time, after looking at
  them, and accepting every other merge in the file as the price of resolving
  one is not a choice a reviewer should have to make. The selector is the same
  comma-separated, repeatable `--key` the rest of the CLI takes. A key that
  belongs to no cluster is an error rather than a silent no-op, since the caller
  believed it named a duplicate.

### Fixed

- `ref remove` emitted its warnings in the `diff` field and dropped them from
  `warnings`. It passed them into `_finish_mod`'s `diff_text` parameter
  positionally, so `--diff` produced the warning list instead of a diff — and
  when there were no warnings, produced nothing at all — while "citation key not
  found; skipped" never reached the envelope any caller reads. Both halves of
  the modifying-command contract were wrong for this one command. Everything
  after `human` in `_finish_mod` is now keyword-only, so the mistake cannot
  recur in the other twenty-nine callers.

- `ref add` reported a citation key that already exists as an exit-1
  `InvalidInput` error, while `ref import` reported the identical situation as
  an exit-2 `CitationKeyConflict` with the options that resolve it. A taken key
  is a decision for the caller — both choosing another key and appending anyway
  are legitimate, and `ref add` has `--allow-duplicate` for the second — so it
  is a conflict, not a malformed request. `ref add` now emits the same envelope
  as its sibling, and a client can branch on the situation without knowing which
  of the two commands produced it.

### Editor

#### Added

- The view can now change *which* entries exist, not only their fields.
  **Import…** resolves a DOI, arXiv id, ISBN or supported URL into a new entry;
  **New entry** appends an empty entry of a chosen type and selects it so the
  field editor fills it in; an entry's detail pane removes it; its **Groups**
  chips add and remove membership; and **Duplicates** lists what `dedupe check`
  found, each cluster with the merge that resolves it. These are not staged —
  none is a field edit — but they keep the staged editor's guarantee: the
  engine's own `--dry-run --diff` goes to the Staged diff pane, the approval
  dialog names what a diff cannot show (materials about to be deleted, a
  network request already made), and approving re-runs the identical invocation
  without `--dry-run`. An engine conflict is treated as the engine declining to
  guess rather than as a failure: an import of a reference already held asks
  whether to add it anyway and replays the answer, and a taken citation key
  says so and writes nothing.

- `pynakes.allowOnlineLookups` now gates every network-backed action in the
  view rather than comparison alone. Importing by identifier reads the same
  switch, so "no lookups" means the same thing whichever button was pressed;
  with it off, Import says so instead of failing at the provider.

- `editor/` — a VS Code / Open VSX extension companion. It opens a `.bib` file
  as a sortable, filterable entry table with a field detail pane, browses the
  declared group hierarchy, runs the engine's own search, surfaces lint findings
  per entry, and stages field edits for review as an exact diff before commit.
  It flags duplicate citation keys, reports encoding, line ending, `@string`
  count and which metadata namespaces the file carries, follows the text buffer
  rather than the file on disk, and jumps from a row to the entry's declaration
  in the source. The client holds no bibliography implementation of its own: every
  value it displays comes from the engine's JSON envelope, and every change
  leaves through `ref edit`. It is not published to either marketplace, is
  excluded from the Python sdist and wheel, and has its own Node toolchain —
  see [editor/README.md](editor/README.md).

- `pixi.toml` at the repository root provides the toolchain the VS Code
  extension needs — Node plus a Python pinned to 3.11, the floor of
  `requires-python` and the version CI builds with — so
  `pixi run build-extension` produces an installable
  `editor/pynakes-vscode-<version>.vsix` on a machine set up for neither.
  `install-extension`, `test-extension`, and `clean-extension` round out the
  set. This is additive: the pip workflow remains how the engine is developed.

- The detail pane gained a "Compare with remote" action, next to each of an
  entry's `doi` and `eprint` fields (both, when both are present): it fetches
  that identifier's DOI/arXiv record via the engine's new `ref compare` and
  shows a three-column Local / Other / Merged table in a new "Compare" panel
  tab, word-level diff highlighting differing spans within each field.
  Clicking a Local or Other cell selects that value into the Merged column,
  which is also freely editable; the merged column defaults to the local
  value on a genuine conflict (never silently overwritten) or the other side
  when the field is missing locally. Nothing is written automatically —
  "Apply merged" stages each field through the existing field-edit path, so
  it goes through the normal preview/diff/commit flow like any manual edit.
  Network access is controlled by the new `pynakes.allowOnlineLookups`
  setting (on by default); with it off, compare still runs but reports that
  online lookups are disabled rather than silently doing nothing.
- The view now shows which entries the manuscript cites, and where. With
  `tex-sources` declared, entries nothing cites carry a `○` marker and a
  new **uncited** toggle narrows the table to them; an entry's **Cited at**
  list opens the `.tex` file at that `\cite`, positioned by the engine's
  per-occurrence line and column. Citations naming a key no entry declares are
  published as diagnostics on the `.tex` file that makes them, so an undefined
  citation appears in Problems where it was typed rather than as a note about
  the bibliography. All of it comes from the engine's new `tex scan --json`
  citation index; the client scans nothing itself.

- Entries with linked files now carry a `🗎` marker, and the detail pane
  lists each material by kind — published PDF, preprint, source, supplement,
  erratum for a Pinax store, plus any BibLaTeX `file`-field link — marking a
  missing or wrong-type link rather than hiding it. Clicking one opens it with
  the operating system's handler; a directory is revealed in the file manager.
  Every path comes from `asset check --json`: the client never constructs
  `<key><suffix>.pdf` itself, since that is the Pinax store's addressing
  scheme and belongs in one place. A path the view asks to open is opened only
  when the last read actually reported it.

  Both reads take the document's real path on disk rather than the temporary
  mirror used for an unsaved buffer, because `tex-sources`, `pinax-files-dir`,
  and relative `file` paths all resolve from the `.bib`'s own directory — from a
  temp directory they resolve to nothing, and the view would report a library
  with no sources and no materials. The cost, noted in the README, is that an
  unsaved edit to `tex-sources` or to a `file` field is not reflected until the
  file is saved.

- The view's findings are now published as native VS Code diagnostics, so they
  appear in the Problems panel — and as squiggles in any text editor showing
  the same `.bib` file — in addition to the in-view severity markers and the
  findings panel. Each diagnostic sits at the finding's entry declaration line,
  located by the engine's new per-issue `line` field rather than any client-side
  scanning. `pynakes.showFindings` gates both presentations together, and a
  failed re-read (parse error, engine unavailable) clears the published set so
  Problems can never outlive what the view shows.

- All panes (the groups sidebar, the detail pane, and the bottom findings/diff
  panel) are now resizable by dragging their border, the same way table
  columns already were; each dragged size is remembered per workspace.
- The detail pane's citation key is now editable: renaming it runs the
  engine's `keys rename`, which also rewrites matching `\cite{...}` keys in
  any linked TeX sources. Asks for confirmation first, since (unlike a field
  edit) it can touch files beyond the `.bib` itself; refuses if the entry has
  pending staged changes, since those are keyed by the old citation key.
- Icon buttons (undo/remove a field, collapse toggles) are bigger, with a
  wider hit target and hover highlight — mainly to make the new "Compare with
  remote" buttons comfortable to click.
- `editor/src/test/cliContract.test.ts` runs the real engine (not a mock)
  against a temp `.bib` file, checking argument order and envelope shapes for
  `ref edit`, `ref compare --with`, and `keys rename` — the client's other
  tests are pure and would not have caught either of two real regressions
  from this session: a renamed envelope key (`FieldComparison.remote` ->
  `.other`) and a wrong argument order for `keys rename`. Requires a
  `python3` that can import this repo's `src/pynakes`; skips itself with a
  clear reason otherwise, so `npm test` still works for editor-only
  contributors without a Python setup.
- `editor/` now bundles the engine, so the extension needs a Python 3.11+
  interpreter but no pynakes install. `npm run vendor-engine` builds the engine
  and its dependencies into `editor/engine/` (generated, git-ignored, shipped
  only inside the VSIX); every runtime dependency is a pure-Python
  `py3-none-any` wheel, so one universal bundle covers every platform with no
  per-platform build and nothing to code-sign. An engine the user installed
  themselves is preferred when its version is strictly newer than the bundled
  one, so upgrading pynakes takes effect without an extension release. The
  interpreter is taken from the Python extension's selection, then a workspace
  virtual environment, then `PATH`; `pynakes.executable` still overrides
  everything and `pynakes.engine` can force `bundled` or `installed`.

#### Changed

- The view's panes — the entry editor, Findings, Staged diff, and Compare — are
  now relocatable between two docks: the right dock (where the editor normally
  sits) and the bottom dock (where findings and the diff live). A pane moves via
  the small arrow beside its tab, and a dock holding more than one pane shows a
  tab row to choose among them. Its location and the active tab per dock are
  remembered per workspace, so the editor can live at the bottom as an "Edit"
  tab or stack with the diff on the right, whichever suits the task.
- `pynakes.search.fuzzy` and `pynakes.showFindings` are now honored. Both were
  declared but read by nothing: the fuzzy toggle started from persisted view
  state alone (it now seeds from the setting on first open, and a toggle made
  in the view still persists over it), and lint markers were shown regardless
  of the setting (the severity markers per row and the findings panel tab now
  both disappear with it). Setting changes reach an open view live, like
  everything else it re-reads.

#### Fixed

- Sorting a column descending put blank values first: blanks were sorted last
  ascending and the whole order was then reversed, contradicting the rule that
  gaps never lead. Direction now lives inside the comparator.
- Engine discovery kept a single memoized resolution keyed on settings, so two
  open bibliographies in different workspace folders evicted each other's entry
  and re-probed — respawning version probes — on every read. Resolutions are
  cached per key instead.
- A pending entry-type change was never checked against the dry-run plan at
  commit time, unlike field edits, so a type changed elsewhere could be
  silently overwritten; the commit is now refused with the other conflicts.
- Staged changes are dropped when their document closes, where they previously
  lingered for the session.
- Closing one bibliography view no longer hides the status bar item while a
  sibling view is still active.

## [0.6.3] - 2026-09-20

### Added

- `--key` selects entries by citation key on every command that takes
  `--where`: `fields` (all six operations), `search`, `format`, and
  `corpus combine`. It is comma-separated and repeatable, and exactly equivalent
  to `--where 'key in [...]'`; giving both narrows, since they are ANDed.
  Previously the simplest possible request — act on this one reference I can
  name — had to be spelled through the expression grammar, and `--key` was
  accepted only by `ref add` and `ref import`, where it names the key to
  *assign*. So a caller who reached for it as a selector got Click's bare
  `No such option: --key` and nothing to go on. `--key` now means "the citation
  key" across the whole CLI, and a usage error for a near-miss spelling names
  what that command does accept — the selector where it selects, the positional
  citation key where it takes one. `pynakes capabilities` reports the shorthand
  under `predicate_grammar.key_selector`.

- `lint` reports a page range BibTeX does not spell that way as
  `nonstandard_page_range` (a `content` warning, fixed by `normalize`). A raw
  Unicode en-dash renders under UTF-8 plus `inputenc` but breaks under 8-bit
  `bibtex` with some styles, and it is near-indistinguishable from a hyphen, so
  it survives review and propagates once it is in the file. The finding fires
  exactly when `normalize` would rewrite the value, so lint never reports
  something the command it names would leave alone: an article number and a
  list like `7,41,73--97` are not flagged.

### Changed

- `normalize` reports a step the library has turned off as `off` rather than
  `0`. The two are different claims — `journals=0` means every journal title was
  checked and none changed, while the step had in fact never run, because
  journal-style conversion is off unless configured. There was no way to tell
  from the output which one had happened. The human summary now names the flag
  that turns each skipped step back on, and `--json` carries the full reason
  under `operations.skipped`.

### Fixed

- Reference import no longer writes a Unicode en-dash into `pages`. The repair
  existed but lived in the DOI content-negotiation client, so it covered only
  the one route: every other provider — Crossref's JSON records, Europe PMC,
  PubMed, zbMATH and the rest — still passed the registrar's own spelling
  through, as did the Crossref supplement that `enrich` merges into an entry
  without ever rendering it to a BibTeX entry. Page ranges are now spelled the
  way BibTeX spells them on `ReferenceMetadata` itself, which is what every
  import, `--fetch` and `enrich` route builds, so the format repair happens once
  instead of per client. A lone hyphen (`231-252`, which is what Crossref
  returns) is corrected too; an article number or a page list is left alone.

## [0.6.2] - 2026-09-14

### Fixed

- Online enrichment now falls back to structured Crossref metadata when DOI
  BibTeX omits an article number, maps Crossref's `article-number` to BibTeX
  `pages`, and removes inline APS markup without discarding its text.
- Published-preprint promotion now parses conventional arXiv journal references
  into journal, volume, pages, and year; replaces an arXiv DOI with the published
  DOI; and retains `eprint` and `archiveprefix` provenance fields.
- Reference comparison now recognizes known full and abbreviated journal titles
  as equivalent instead of reporting a false metadata mismatch.

- `enrich` no longer writes a `journal` field into entry types that cannot
  carry one. DOI content negotiation renders a book chapter's container title
  into `journal` whatever the work actually is, so copying it across put a book
  title into the one field only `@article` styles read — and re-added a
  `journal` a user had deliberately cleared in favour of `booktitle`, leaving
  the two redundant. A provider's container title is now routed by the *local*
  entry's type: `journal`/`journaltitle` for article-like types, `booktitle`
  for chapters and proceedings papers, and dropped for a `@book` or `@misc`
  whose own title is the container. An entry that already records a container
  under any spelling is left alone. Promotion to `@article` now happens before
  the container is written, so a preprint gaining its published journal still
  receives it. `pynakes.entry_types.container_field()` is the single decision
  point.

- Provider requests now retry a throttle, a transient server error, or a read
  timeout instead of surfacing the first one as a permanent failure. HTTP 429 —
  which is a request to slow down, not a refusal — along with 500/502/503/504
  and network timeouts are retried up to three attempts with deterministic
  backoff (no jitter, so behavior stays reproducible), honoring `Retry-After`
  in both its documented forms and clamping an absurd value rather than
  blocking the run. A genuinely permanent failure such as 404 is not retried,
  and the final error still reports what actually went wrong. The default read
  timeout rises from 15s to 30s: a loaded provider answers slowly long before
  it answers not at all, and a timeout costs a whole import.

- `ref import arXiv:<id>` now falls back to the work's registered DataCite DOI
  when arXiv's own API cannot answer. Every arXiv id has a deterministic DOI
  (`10.48550/arXiv.<id>`) served by a different host with different rate
  limits, and pynakes already knew how to import it, so a throttled arXiv no
  longer has to mean a failed import. When both routes fail the error names the
  DOI, putting the workaround in the message. A caller supplying its own
  fetcher keeps full control over what is contacted.

- Reference import now repairs the BibTeX registrars actually return, so an
  import never yields an entry that fails pynakes' own `lint`:
  - arXiv deposits get one entry type. DataCite renders some as `@article` and
    others as `@misc` from the same DOI prefix, and the `@article` form has no
    journal to supply, so it linted as an error the user did nothing to cause.
    Every arXiv record is now `@misc` (`@online` in BibLaTeX) with
    `eprint`/`archivePrefix`/`primaryClass` recovered from the identifier that
    was already in the DOI, and its upper-cased DOI restored to canonical form.
  - Crossref subtypes it renders `@misc` are recovered from evidence already in
    the record: a reference book becomes `@book`, and a chapter — which arrives
    with its book title in `journal` — becomes `@incollection` with a
    `booktitle`.
  - Repeated keywords are dropped (DataCite repeats `FOS: Physical sciences`
    verbatim in every arXiv record) and en-dash page ranges are rewritten.
  All of it is derived from fields the record already carries, so refinement
  costs no extra request and stays offline and deterministic. Each recovered
  type is one the target dialect can actually satisfy with the fields present:
  a chapter with no editor becomes `@inbook` rather than `@incollection` in
  BibLaTeX, which requires an editor Crossref rarely supplies.

- DOI import now follows the library's own dialect. It was the one import route
  that assumed BibTeX, which went unnoticed while DOI imports emitted no
  dialect-specific fields; a BibLaTeX library importing an arXiv DOI now gets
  `@online` with `eprinttype`/`eprintclass` rather than BibTeX's spellings.

- `enrich`'s summary now counts every update the command applied. With
  `--published` the human summary described only the enrichment half while the
  JSON envelope and the printed diff covered both, so a dry run — the review
  gate — under-reported the change about to be made. The two directions of
  travel are now also counted apart: promoting a preprint to its published
  version, and adding arXiv provenance to an already-published entry. The
  latter was previously reported as "promoted N preprint(s) to a published
  version", which described the reverse of what happened. `verify`/`enrich`
  `--published` reports gain `promoted` and `linked` counts.

- Page ranges are normalized to BibTeX's `start--end` by default. Crossref
  hands out ranges punctuated with a Unicode en-dash; it renders under UTF-8 +
  `inputenc` but breaks 8-bit `bibtex` with some styles and is invisible in a
  diff, so it propagated silently. A value that is not a simple range — an
  article number, or a list like `7,41,73--97` — is left alone, and a library
  whose own JabRef `saveActions` already run `normalize_page_numbers` keeps
  owning that step rather than having it applied twice.

- `lint`'s cross-entry consistency check no longer reports a missing `pages` on
  an entry that carries a DOI, article number, or page count. Modern journals
  issue article numbers rather than page ranges, so the finding was
  correct-by-convention noise that buried real findings on a mixed library. It
  still fires where nothing else locates the work, which is where a missing
  page range genuinely leaves the reference incomplete.

- `asset fetch --dry-run` now says `Would fetch <key>.` instead of
  `Skipped <key> (would fetch).`, which made two contradictory claims at once
  and was unskimmable over a long queue. Genuine no-action cases keep their
  "Skipped" wording.

### CLI

#### Added

- `normalize --pages on|off|metadata` controls page-range normalization, also
  settable as `normalize-pages` metadata. On by default: `--` is the format's
  own convention for the same value, not an editorial preference.

- `tex scan --json` now locates every citation. The report gains a `usages`
  object mapping each cited key to its occurrences — one
  `{path, line, column, text, macro}` per `\cite`-family macro naming it —
  collected in the same single pass over each source that already answered
  *which* keys are cited. Keys cited but **missing** from the library are
  included, since a citation with no entry behind it is the one most worth
  locating, and an entry cited nowhere simply has no occurrences. This is the
  whole-library citation index `keys usage` could only answer one key at a
  time: a client marking cited/uncited entries, listing undefined citations, or
  jumping from an entry to the `\cite` that motivates it now needs one call
  rather than one subprocess per key, each re-reading every `.tex`.
  `pynakes.usage.collect_citation_occurrences()` is the engine entry point and
  is now the module's only citation scanner — `collect_cited_keys()` and
  `find_key_usages()` are projections of it, so the cite-macro pattern, comment
  stripping, and position arithmetic are defined once.

- `lint` findings now carry source locations. Each issue in the JSON envelope
  gains a `line` field — the one-based line of the finding's `@type{key,`
  declaration or metadata `@comment` block, `null` for file-level findings and
  in-memory libraries — and the human-readable output names it too
  (`[error] key (line 12): ...`). The parser records the declaration line of
  every entry and metadata block (`start_line` on `BibEntry` /
  `MetadataBlock`), so duplicate keys resolve to the exact instance rather
  than a best-effort text scan. Graphical clients can turn findings into
  native diagnostics without locating entries themselves.

- `enrich --online` now consults a journal-preferred metadata-source registry
  before DOI content negotiation. The initial APS rules use the documented APS
  Harvest API to recover the publisher's article identifier (`pages`) and page
  count (`numpages`) for Physical Review journals. It works automatically from
  an APS-authorized institutional network; `PYNAKES_APS_API_TOKEN` optionally
  supplies an APS-issued bearer token elsewhere, and a denied request falls
  back to DOI content negotiation.

- `verify --online` and `enrich --online` now render a Rich progress bar over
  the entries being checked, mirroring `asset fetch`'s: a spinner, a bar over
  the whole entry queue, and the current key, so a large library gives visible
  feedback even while most entries have no DOI to look up. Suppressed for
  `--json` output and non-terminal stderr, same as `asset fetch`.

- `verify`, `enrich`, and their folded-in `--published` preprint check now run
  provider lookups concurrently instead of one DOI/arXiv fetch at a time.
  `-j/--concurrency N` (default 8) controls how many run at once; report
  ordering, applied field updates, and progress-bar events are unaffected —
  they always follow the library's own entry order, never fetch completion
  order, so a run's output is identical regardless of concurrency.

- `keys usage <key> --path <dir>` scans `.tex` sources directly for
  `\cite`-family macros citing one key, reporting each occurrence's file and
  line. It takes no `.bib` file and never consults `tex-sources` metadata, so
  it covers sources `tex add` deliberately does not track (frozen snapshots,
  generated diffs) — the lookup an agent needs to check a rename's blast
  radius before committing to it.

- `normalize --keys on` now stops before committing when a declared
  `tex-sources` file is missing, with a structured `MissingTexSource` error
  that names the sources and explains the safe resolution. Pass `--force` to
  update citation keys while deliberately leaving unavailable sources
  unrevised; the normalize report records them as warnings.

- `search` accepts an empty query, selecting entries by `--where` predicate
  alone: `pynakes search "" refs.bib --where 'doi missing'` answers "which
  entries are missing this field" with no text match involved. This is the
  read-only path for the shared selector grammar, which until now was reachable
  only from commands that write. Predicate-only results report no matched fields
  and stay in file order, since relevance ranking needs terms to rank by. The
  query argument remains required, so a lone path can never be taken for a
  query, and an empty query with no `--where` is rejected rather than silently
  matching the whole library.

- `inspect --display` adds a `display` object per entry: title-family fields
  cleaned of LaTeX markup and braces (`latex_to_plain_text`), and
  `author`/`editor` split into individual, cleaned names via the existing
  brace-aware `split_name_list` rather than a raw `A and {B and C}` string.
  Names are split before cleaning, so a brace-protected `{Smith and Sons}`
  survives as one name instead of being cut in two. It is a read-only
  presentation view for a UI to render, not a value to write back; combine
  with `--resolved` to clean the crossref/xdata-inherited view instead of the
  entry's own fields.
- `ref compare <key>` reports every field where the local entry differs from
  (or lacks a value present in) another reference — read-only, so a caller
  can review the differences and apply only the fields they choose via
  `ref edit <key> --field name=value`. That other reference is either a
  fetched DOI/arXiv provider record (`--online`, preferring the entry's DOI
  and falling back to arXiv), or another entry already in the library
  (`--with <other-key>`, no network access — e.g. reviewing a candidate
  duplicate pair before merging). `pynakes.integrity.compare_entry_with_remote()`/
  `compare_entries()` and `Bibliography.compare_entry_with_remote()`/
  `compare_entries()` are the underlying engine entry points. Complements the
  existing whole-library, always-fill `enrich` and read-only `verify` for a
  one-entry, human-in-the-loop workflow.
- `normalize --drop-field NAME` (repeatable) removes a field from every entry
  — e.g. `--drop-field abstract` to strip abstracts on every normalize pass.
  Off by default, like journal-style conversion: dropping a field is
  opinionated and not reversible, so it only runs for fields named explicitly,
  either via the flag or a persisted `normalize-drop-fields` metadata key
  (the two combine). Reported as `dropped_fields` in the normalize report.

#### Changed

- Lint's citation-key remediation hint now names `normalize --keys on`, and
  collision-prone key-pattern findings report the same deterministic suffix
  (`…a`, `…b`, ...) that normalization will assign.

- **Provider-response caching is now opt-in, and the cache is one file.** Online
  commands (`verify`, `enrich`, `ref compare`, `ref import --fetch`,
  `asset fetch`) used to write a `.pynakes-cache/` directory beside the `.bib` by
  default, one sha256-named file per identifier — so a single `verify --online`
  over a few hundred entries left a few hundred files in the user's folder,
  unasked for and never pruned. Now nothing reaches disk unless the renamed
  `--cache-file PATH` says so, and what it writes is a single newline-delimited
  JSON file with identifiers in plain text: readable, greppable, covered by one
  `.gitignore` line, removable with one `rm`. Responses are memoized for the life
  of the process regardless, which is where most of the benefit was — one run asks
  a provider about a given DOI once, however many entries carry it. This matches
  the rule the project already applies to the network: explicit or not at all.

  **Breaking.** `--cache-dir` is now `--cache-file` and takes a file path; a
  directory is rejected rather than written into. The `cache_dir=` keyword on the
  `Bibliography`, `integrity`, `fetch`, and provider APIs is likewise
  `cache_file=`. Nothing reads the old cache layout: delete any
  `.pynakes-cache/` directory a previous release left behind, which costs only
  refetches.

  No record expires. A cache is a snapshot the caller chose to keep, and provider
  metadata does change, so a long-lived cache should be deleted rather than
  trusted indefinitely; this is now stated in the docs.

#### Fixed

- Source line numbers were reported one too high for anything starting
  mid-line, because the shared helper counted the lines its prefix *spanned*
  rather than the newlines before the position. It affected `lint`'s new
  per-issue `line` and the parser's `start_line` whenever a second `@entry`
  shared a line with the previous block's closing brace, and it would have
  affected every `\cite` in running text.

- `keys generate` no longer mangles entries with no author/editor or title —
  e.g. a physics paper's `@misc{SM, note = {See Supplemental Material...}}`
  placeholder, cited only so the bibliography numbers it. There is nothing to
  build an `AuthorYearTitle`-style key from, so it previously produced
  `Anon__`-style noise from the empty pieces; such entries now keep their
  existing key, the same way `@xdata` containers already do. `lint`'s
  citation-key-pattern check is exempt for the same entries, so it no longer
  reports their real key as a "mismatch" against the noise it would have
  generated.

- Pinax material writes no longer leave debris in the files directory. Temporary
  files staged during a PDF write, an arXiv source extraction, or a manifest
  update were created beside the materials themselves and cleaned up only on the
  success and `OSError` paths — so interrupting `asset fetch`, the slowest and
  most network-bound command in the tool, left `.<key>.published.pdf.<rand>.tmp`
  and `.<key>.source.<rand>/` in the user's folder permanently, with nothing to
  sweep them. Temporaries now stage under `.pinax/tmp/<pid>/`, and each write
  first removes scratch belonging to processes that have exited, so a killed run
  is self-healing and concurrent runs never disturb each other. A write that
  fails, or a store that never had a manifest, leaves no `.pinax` directory
  behind at all.

- The documented idiom for a predicate-only search, `pynakes search . --where
  '...'`, was quietly lossy: `.` is a real search term, so the results were
  restricted to entries whose text happened to contain a period, and entries
  without one were dropped from answers like `--where 'abstract missing'`. The
  guides now use the empty query added above.
- The test suite imported whichever copy of pynakes was installed in the
  environment rather than the working tree, because nothing put `src/` on the
  import path and a non-editable install shadows it. A green run therefore said
  nothing about the source under test. `pythonpath = ["src"]` fixes it, so
  `pynakes` now resolves to `src/pynakes` during a test run.

### Internal

- `integrity.py` is split into `_integrity_common.py` (report types and the
  field accessors all three operations share) and `_integrity_published.py`
  (preprint detection, promotion, and arXiv backfill), with `integrity.py`
  remaining the single public import site. It had grown past the 1000-line
  ceiling; each module is now under 550 lines.
- Eprint provenance field naming (`archivePrefix`/`primaryClass` in BibTeX,
  `eprinttype`/`eprintclass` in BibLaTeX) had three independent definitions
  that had already drifted apart in casing. They now come from
  `pynakes.entry_types.eprint_fields()`, so one work imported by arXiv id or by
  its DOI lands with identically-spelled fields.

## [0.6.1] - 2026-08-18

### Added

- Journal-title abbreviation now resolves against a bundled copy of every
  list JabRef itself ships (`journal_abbreviations/*.csv`, all 19 lists
  vendored from [abbrv.jabref.org](https://github.com/JabRef/abbrv.jabref.org),
  CC0) by default, replacing the old ~15-entry hardcoded table — matching
  JabRef's own behavior of combining all of its lists. A new
  `normalize-journal-source` metadata key (and `normalize --journal-source`
  flag) selects `jabref` (default) or `none` to fall back to pure rule-based
  resolution; a `normalize-journal-table`/`--journal-table` still layers a
  user table on top either way. `scripts/update_journal_abbreviations.py`
  re-syncs the vendored CSVs from upstream (the file list is discovered from
  the GitHub API, not hardcoded, so it tracks lists JabRef adds or removes).
- Single-word journal titles (`Nature`, `Science`, `Econometrica`, ...) are
  now recognized as already correctly abbreviated per the ISO 4 rule that
  one-word titles are never abbreviated, instead of relying on a hardcoded
  per-title exception list.

### Changed

- An already-abbreviated (or already-full) journal title that matches the
  configured style is now recognized as correct instead of being reported
  `unknown_journal`. Previously, `expected_journal_title`/lint only matched a
  field's *full* title against the exact-mapping table (or the reverse for
  `full` style), so a value already in its target form — e.g. a `journal`
  field already reading `Phys. Rev. Lett.` — fell through to LTWA word
  generation, which cannot re-derive an abbreviation from already-abbreviated
  tokens and declined the whole title.
- Because the bundled abbreviation table changed (see Added), a handful of
  economics journals normalize to slightly different abbreviations than
  before (e.g. `American Economic Review` now abbreviates to
  `Amer. Econ. Rev.` instead of `Am. Econ. Rev.`, matching JabRef's own list).

- Commands that consume ``tex-sources`` metadata (``tex scan``, ``keys
  generate``, ``keys rename``, ``keys repair``) now emit a ``missing_tex_source``
  warning when a configured path does not exist on disk, instead of raising an
  unhandled ``FileNotFoundError``. The missing paths are skipped and the command
  succeeds with the remaining sources.
- `lint` now reports the same `missing_tex_source` finding (category
  `correctness`) when the library's `tex-sources` metadata points at a path
  that doesn't exist relative to the `.bib` file, so a broken link surfaces
  without having to run `tex scan` or `keys generate` first.

### Fixed

- A mixed-case citation-key pattern marker (`[Auth]`, `[Veryshorttitle]`, ...)
  no longer lowercases everything after the first letter. It previously
  applied Python `.capitalize()`-style casing, which corrupted legitimately
  mixed-case values — a compound surname with its hyphen stripped
  (`Pioro-Ladriere` → `PioroLadriere` → wrongly `Pioroladriere`) or a title
  starting with an acronym (`AI for ...` → wrongly `Ai`). It now only forces
  the first letter to uppercase, matching JabRef's marker semantics (marker
  case doesn't otherwise affect the value; only the fully-lower/fully-upper
  forms, `[auth]`/`[AUTH]`, force casing).
- `last_name()` (used by `[auth]`/`[Auth]`/etc. and duplicate-detection) now
  drops a BibTeX "von" particle from a `von Last, First` author — e.g.
  `van den Berg, J.` → `Berg`, not `vandenBerg` — matching real BibTeX/JabRef
  name parsing, where a leading run of lowercase-starting words before the
  comma is not part of the last name.
- Journal-table CSV loading (`load_journal_table`/`load_ltwa_table`, and the
  bundled JabRef lists above) now tolerates a stray space after the
  delimiter before a quoted field (`"Full Name", "Abbreviation"`). A few
  upstream lists have this malformed-CSV quirk; without `skipinitialspace`,
  the leading space and quote characters were kept as literal text in the
  abbreviation instead of being parsed as a quoted field.
- `keys repair`'s plain-text summary no longer counts a missing `tex-sources`
  path as an "ambiguous citation". The two warning types were previously
  merged into one count, so a missing source with no actual ambiguous
  citation still printed "N citation(s) now ambiguous in linked TeX sources."
  The missing-source message is now shown on its own line, matching `keys
  generate` and `keys rename`.

## [0.6.0] - 2026-08-18
### Added

- `ref import` now accepts the scholarly metadata indexes as import entry
  points in their own right: `Crossref:<doi>`, `DataCite:<doi>`,
  `OpenAlex:W<digits>`, and `SemanticScholar:<paper id>`, along with the
  `api.crossref.org/works/…`, `api.datacite.org/dois/…`,
  `api.openalex.org/works/…`, `openalex.org/W…`, and
  `semanticscholar.org/paper/…` record URLs. A `Crossref:` or `DataCite:`
  prefix selects that index's own JSON record instead of DOI content
  negotiation, which is the reason to name it explicitly. DataCite is a new
  provider covering members whose content-negotiated BibTeX is thin, such as
  Dryad, Figshare, and Dataverse. None of the four requires an API key: the
  Crossref and OpenAlex `mailto=` parameter is polite-pool courtesy rather than
  authentication, and the Semantic Scholar Graph API answers unauthenticated at
  low volume.
- `ref import` now accepts three further communities whose canonical identifier
  is not a DOI. RFC and IETF documents resolve through their deterministic
  `10.17487/rfc<number>` DOI — accepted as `RFC:9110`, a bare `rfc9110`, or a
  `datatracker.ietf.org`, `rfc-editor.org`, or legacy `tools.ietf.org` URL —
  with the RFC number left unpadded, since the zero-padded form does not resolve
  for low numbers. IACR ePrint accepts `IACR:<year>/<number>` and
  `eprint.iacr.org` URLs, reading the BibTeX record embedded in each paper's
  landing page because the archive publishes no separate citation endpoint.
  zbMATH Open accepts `zbMATH:<Zbl or DE number>` and `zbmath.org` URLs through
  its public, key-free JSON API. OpenReview was evaluated and left unsupported:
  its public API answers a bot challenge to non-browser clients, so covering it
  would mean defeating that challenge.
- `ref import` now resolves ACM Digital Library, American Chemical Society,
  Royal Society of Chemistry, and Project Euclid article URLs. ACM and ACS carry
  the DOI in the path, with or without a view segment (`abs`, `full`, `pdf`,
  `epdf`, `fullHtml`, `book`); an RSC `articlelanding`/`articlehtml`/`articlepdf`
  URL maps its article suffix to a `10.1039/<suffix>` DOI; and a Project Euclid
  journal URL carries a DOI containing an internal slash, with an optional
  `.full` or `.short` suffix.

- A multi-entry triage view: `ref show --keys k1,k2,…` summarizes a set of
  candidate references in one call instead of one invocation per key. Each
  entry reports its title, the first present of `author`/`editor`, the first
  present of `year`/`date`, its most specific venue field, and every identifier
  it carries; `--abstract` adds the abstract, reported as `(none)`/`null` when
  the entry stores none, so "no abstract" is distinguishable from "not
  requested". Keys may be comma-separated or the option repeated, repeats
  collapse, the requested order is preserved, and every unknown key is reported
  together rather than one per run. `search --show-abstract` prints the same
  triage material inline under each hit, so a result list can be narrowed
  before any entry is opened. The new public `pynakes.triage` module exposes
  the summary and excerpt selection.
- One transversal entry selector: the new public `pynakes.query` module compiles
  the `--where` grammar shared by `fields`, `search`, `format`, `corpus combine`,
  `corpus split --to`, and the `fields.*` batch operations. Predicates now
  compose with `and`, `or`, `not`, and parentheses, and the operator set grows
  beyond `contains`/`=`/`exists` to `!=`, ordered comparison (`>`, `>=`, `<`,
  `<=`), `in [a, b]` / `not in [...]`, `matches` (regular expression), `~`
  (fuzzy), and `missing`. Ordered comparison is numeric for numbers, partial-date
  for `YYYY[-MM[-DD]]` dates, and textual otherwise, so `year >= 2025` and
  `date >= 2020-06` mean what they read as. The special fields are `key`, `type`,
  `year` (falling back to the year inside `date`), and `date` (falling back to
  `year`/`month`/`day`); `corpus split` buckets keep `*`, `used`, `unused`, and
  `group "Name"`, which now compose with everything else
  (`used and year >= 2020`). `capabilities --json` reports the grammar under
  `predicate_grammar`.
- `search --fuzzy` matches misspelled and inflected terms by normalized
  similarity, and every result now explains itself: `matches` lists one entry per
  hit with its field, term, `exact`/`fuzzy` kind, score, and the matching
  excerpt, alongside a result `score` and the parsed selector in `where_parsed`.
  Ranking breaks within-tier ties by score, so exact hits outrank fuzzy ones.
- `format --where` reformats only the entries a selector matches, leaving every
  other byte of the file — including unmatched entries — identical. A selection
  owns the layout inside an entry, so the whole-file `--entry-order`,
  `--block-order`, and `--blank-lines` options are refused alongside it.
- `corpus combine --where` keeps only the matching entries in the combined
  output, so a focused subset of several libraries no longer needs a
  combine-then-prune script.
- A public `pynakes.identity` module now extracts normalized offline work
  evidence and returns explainable `exact`, `probable`, `conflict`, or
  `unknown` comparisons. Stable identifiers remain evidence rather than a
  universal work entity; metadata similarity is only `probable`, ORCID is
  excluded as author identity, and provider relationship lookup stays separate.
- The Python package now exposes a curated top-level application API, including
  `Bibliography`, core model and lifecycle result types, formatting policy,
  parser/writer functions, file I/O, and common exceptions. The API guide
  documents transactional, in-memory, and future MCP/service embedding
  workflows; `pynakes.canonical` is now explicitly public.
- `format` now supports explicit `--alignment`, `--field-order`,
  `--entry-order`, and `--block-order` policies. The same defaults can travel
  with a library through validated `format-*` metadata, and
  `capabilities --json` reports the complete policy surface and defaults.
- Opt-in `format --wrap-values stable|canonical --line-width N` safely wraps
  prose and name-list values while preserving delimiters and protecting
  verbatim/date fields, bare macros and numbers, brace/math groups, and `#`
  concatenations.
- `ref import` now accepts PubMed and PubMed Central identifiers, Europe PMC
  records, SSRN and NBER working papers, bioRxiv and medRxiv preprints, Zenodo
  records, OSF Preprints, HAL records, ChemRxiv preprints, and Research Square
  manuscripts. Provider-prefixed identifiers and canonical archive URLs are
  supported, with duplicate detection across repository ids and returned DOIs.
- `ref import` now resolves Springer Nature, Wiley Online Library, PLOS, and
  Elsevier ScienceDirect article URLs, so a page URL can be imported without
  first extracting its DOI. Springer, Wiley, and PLOS URLs carry the DOI in
  their path or query; ScienceDirect URLs and `PII:` identifiers resolve through
  the Crossref `alternative-id` index to the article's DOI, keeping the PII as
  identifier evidence.
- `ref import` now resolves IOPscience, SciPost, and JSTOR article URLs, plus
  legacy `aip.scitation.org/doi/<doi>` URLs. SciPost article ids map to their
  `10.21468` DOI and numeric JSTOR stable ids to their `10.2307` DOI, while
  JSTOR book chapters and hosted content carry the full DOI in the stable path.
- `ref import` now reports actionable advice instead of a generic failure for
  URLs that are recognizable but carry no recoverable identifier: modern AIP
  `pubs.aip.org` article URLs, legacy ISSN-based IOPscience URLs, and JSTOR
  stable ids that are neither numeric nor a DOI.
- `ref import` now accepts INSPIRE-HEP records (record id or texkey), DBLP
  records, and ACL Anthology papers, each through the BibTeX those services
  publish, so eprints, report numbers, and venue/editor detail that DOI records
  omit are preserved. An INSPIRE texkey is adopted verbatim by `--key-source
  provider`; DBLP's unusable key is discarded in favor of a generated one, and
  its `timestamp`/`biburl`/`bibsource` bookkeeping fields are dropped.
- `ref import` now accepts ISBNs and Open Library `openlibrary.org/isbn/<isbn>`
  URLs, producing a `@book` entry with publisher, place, edition, and series
  from Open Library edition data. Hyphenated or spaced ISBN-10/ISBN-13 values
  and compact `978`/`979` ISBN-13 values are recognized bare; a compact ISBN-10
  uses the `ISBN:` prefix. Check digits are validated before any lookup, and
  duplicate detection matches the `isbn` field of existing entries.
- `pynakes.identity.identity_class` classifies an entry as `preprint`,
  `published`, `book`, `code`, or `unknown` from offline evidence, with
  publication evidence outranking eprint evidence so a published article that
  also exists as a preprint is classified as published.
- Every `lint` finding now carries a `category` — `correctness`, `content`,
  `layout`, `consistency`, or `profile` — and the `fixer` command that resolves
  it, so a report says whether `normalize`, `format`, or a human decision is
  needed. `lint --category` filters the report, `lint --json` gains `info` and
  `by_category` counts alongside per-finding `category` and `fixer` keys, and
  human output ends with the commands that would clear the fixable findings.
  `lint` remains read-only.
- Metadata-aware `lint` findings for the library's stored settings, so metadata
  drift no longer passes silently. `unknown_metadata_key` flags any
  `pynakes-meta` key outside the pynakes schema (`jabref-meta` is JabRef's own
  namespace, and pynakes only catalogues a subset of its vocabulary, so an
  uncatalogued JabRef key is tolerated); `invalid_metadata_value` validates a
  key's value against the grammar pynakes defines for it — a typo'd
  `pinax-fetch-policy` or `normalize-journal-style` token, a dialect that is
  not `bibtex`/`biblatex`, or a bad formatting choice; and
  `duplicate_metadata_block` reports repeated blocks for one key within a
  namespace, which make the effective metadata ambiguous. The JabRef flat
  `groups:` format is exempt from the duplicate check because it repeats the
  `groups` key once per group line by design. All three findings are warnings
  that, like the other stored-profile deviations, also gate `lint --strict`.
- Citation-key pattern generation gains an editor-field marker family (`edtr`,
  `editors`, `editorIni`, `edtrIniN`, `editorsN`, `editorLast` — these read
  only the `editor` field and never fall back to `author`, unlike the existing
  `auth`-family default), page markers derived from the `pages` field
  (`firstpage`/`lastpage` scan every number in the value rather than just the
  ends of one range, and `pageprefix` extracts a leading non-digit prefix like
  `L` from `L7`), and a `fulltitle` marker that keeps a title's every word and
  original spacing instead of filtering to significant words. The modifier
  chain gains `sentencecase`, a `regex("pattern","replacement")` modifier, and
  a `(default)` fallback inserted when the preceding marker resolved empty;
  more usefully, any registered field formatter (`latex_cleanup`,
  `remove_braces`, `unicode_to_latex`, ...) is now usable directly as a
  modifier, e.g. `[title:latex_cleanup]`, closing the gap between the
  citation-key pattern language and the formatter registry. `truncateN` now
  trims trailing whitespace after truncating, so a value cut mid-word never
  ends in a stray space. A handful of rarer combinator markers
  (`authN_M`, `authorsAlpha`, `editorLastForeIni`, `keywordN`, and similar)
  remain unsupported and continue to fail explicitly rather than silently
  generating a wrong key.

### Changed

- `groups list` now reports the union of flat per-entry tags and group-tree
  nodes, listing each group's direct members. Previously, the presence of any
  tree node switched the listing to tree names alone, so a flat-only group and
  its members disappeared from the report while remaining in the file — a
  grouped entry read as ungrouped, with a `success` status. Member-less tree
  nodes now appear too. Use `groups list-entries` for descendant-inclusive
  membership.
- `groups list-entries` reports a `KeyNotFound` error for a group name matching
  neither a tree node nor a flat tag, instead of returning an empty list with a
  `success` status, so a mistyped name is distinguishable from a group that has
  no members. This matches `remove-group`, `rename-group`, `move-group`, and
  `update-group`.
- `groups tree --json` serializes nodes through a new `GroupNode.to_dict()`
  rather than the instance `__dict__`, so the payload is an explicit projection
  like every other structured output. The emitted keys are unchanged.
- The record-normalization helpers shared by metadata services and repository
  clients moved from `providers.repositories._common` to `providers._common`,
  beside `providers._http`, because both trees are equally their consumers.
  Metadata services answering with JSON now share the fetch-decode-unwrap step
  in `providers.metadata._json_service`, the counterpart of the existing
  `_bibtex_service`, and `registry` builds every provider loader from one
  helper instead of hand-written closures for the ones taking a fixed keyword.
- Google Books, the Library of Congress, and IEEE Xplore are now recorded as
  deliberately unsupported rather than planned. Google Books needs an API key
  for dependable quota and Open Library already covers ISBN-addressed books;
  IEEE Xplore addresses articles by an internal document number with no
  published offline mapping to a DOI, so it joins the hosts that are recognized
  and explained instead of scraped.

- `validate_metadata_value` now enforces the `normalize-journal-style` enum
  (`none`, `abbreviated`, or `full`), so `metadata set` refuses a typo'd journal
  style at write time and `lint` reports it as `invalid_metadata_value` rather
  than the profile-specific finding.
- `format` now lowercases entry types, which BibTeX treats case-insensitively,
  the way it already lowercases field names. This clears every `layout`-category
  lint finding, which previously included one (`noncanonical_entry_type_case`)
  that only `normalize` resolved — so layout drift no longer reaches
  `normalize --check` as content drift. Surgical edits still preserve the entry
  type as spelled.
- The `lint` cross-entry consistency check now groups entries by entry type
  **and** identity class, and ignores publisher decoration (`issn`, `publisher`,
  `month`, `url`, `abstract`, `keywords`, `language`, `isbn`, `eissn`, `day`,
  `pagetotal`, `urldate`, `copyright`). A preprint is no longer judged against
  published articles that carry issue and publisher metadata by construction,
  and a record from a discipline database is no longer flagged for the publisher
  decoration that DOI content negotiation happens to supply. Gaps between
  genuinely comparable peers are still reported.
- `lint` gained an `info` severity beneath `warning`, and layout and consistency
  findings now use it: `noncanonical_entry_type_case`,
  `noncanonical_field_name_case`, `inconsistent_field`, and `missing_doi`. This
  keeps advisory findings from burying a structural `error`. Exit-code behavior
  is unchanged — only errors and metadata-profile deviations gate `--strict`.

- `dedupe`, reference-import duplicate checks, and integrity preprint routing
  now share `pynakes.identity` extraction and comparison. The former
  `dedupe.WorkIdentity` name is replaced by `identity.WorkIdentifier`; no
  deprecated alias is retained during alpha.
- The explicit formatting policies replace the former `--tabular`,
  `--sort-fields`, and `--preserve-field-order` compatibility flags. This
  alpha-stage interface intentionally carries no deprecated aliases.
- `format` runs lint before staging and refuses repeated fields, which the
  semantic field mapping cannot rewrite losslessly. It now fails with a
  structured `FormatLintError` rather than silently keeping only the final
  repeated assignment.
- Project invariants now live in the architecture guide; DEVPLAN contains only
  release scope and completion criteria.
- Pinax metadata is consistently namespaced: use `pinax-files-dir` and
  `pinax-fetch-policy`. The former `files-dir` and `fetch-policy` keys are no
  longer recognized.
- Normalization profile metadata is consistently namespaced: use
  `normalize-protected-terms`, `normalize-journal-table`, and
  `normalize-ltwa-table`. The former unprefixed keys are no longer recognized.
- Atomic writes with backups now stage a copied `.bak` while leaving the
  destination in place until the final replacement, and clean up the prepared
  destination after handled replacement failures.
- Project and automation documentation now describes concrete command behavior
  instead of presenting “agent-safe” or “deterministic execution” as product
  guarantees; capabilities report explicit network access rather than a broad
  `safe_by_default` claim.
- Reference imports now pass provider responses through a shared
  `ReferenceMetadata` record and an explicit provider registry. Metadata
  services and repositories now live directly under `providers.metadata` and
  `providers.repositories`; the former flat provider modules were removed.
- DOI, arXiv, Nature, and APS URL recognition now uses an ordered declarative
  resolver table, providing the extension point for the broader v0.6 import
  paths without adding one module per publisher URL pattern.

### Fixed

- `groups update-group --expanded` had no effect, because the option's own
  default made an explicit `--expanded` indistinguishable from omitting it. A
  group collapsed through the CLI could never be re-expanded through it.
- `groups update-group --parent ""`, `--color ""`, and `--description ""`
  silently did nothing instead of clearing the property, since an empty string
  was treated as "not supplied" — while `move-group --parent ""` has always
  meant "move to root". All three now distinguish an omitted option from an
  explicit empty one.
- `groups update-group` invoked with no options reported a successful update.
  It now reports no modification and leaves the file byte-identical.
- DataCite creators supplied only as `givenName`/`familyName`, with no combined
  `name`, were dropped from the author list.
- OpenAlex records typed `article` — its own spelling of Crossref's
  `journal-article` — became `@misc`. The shared type map now also covers
  `article`, `book`, `monograph`, `edited-book`, `reference-book`, `book-part`,
  `book-section`, and `proceedings`; types whose BibTeX and BibLaTeX names
  differ still fall back to `misc` rather than guessing per dialect.

- **`asset fetch` can always name its library.** The whole-library form (no
  citation key) had no way to say *which* `.bib` when siblings shared the
  directory: the first positional is the citation key, so `asset fetch refs.bib`
  fell through to auto-detection and failed with "Multiple *.bib files found;
  specify one as an argument" — while the user had just specified one. It now
  accepts `--file` for that form (the same option `ref add` already uses when its
  key argument is omitted), reports a pointed error when a `.bib` path is passed
  where the citation key goes, and treats a blank key as "every entry" instead of
  looking up the empty key. `asset check` was never affected — it takes libraries
  as variadic positionals.

### Removed

- **Breaking:** `groups list-entries --strict` is renamed `--exact`, and its
  JSON key `strict` is renamed `exact`. Elsewhere `--strict` gates the exit
  code on findings, but here it selected exact-versus-descendant matching and
  never affected the exit code. The `list_entries_in_group_tree` keyword
  argument is renamed to match. No alias is kept.

## [0.5.1] - 2026-07-21

### Added

- Publish to PyPI via trusted publishing (OIDC) on tagged releases, alongside
  the existing GitHub Release attachment.

### Fixed

- **`init --pinax --from other.bib`** on an already-initialized library no
  longer silently ignores `--from`: it now merges in the template's
  maintenance-profile keys (`dialect`, `key-pattern`, `normalize-keys`,
  `sort-order`, etc.) that this library doesn't already have, aliasing-aware
  (a native `dialect` counts as set even if the template only supplies JabRef's
  `databaseType`). Keys the library already has are left untouched.

## [0.5.0] - 2026-07-21

First public alpha. Adds the optional **Pinax** corpus layer
(a `.bib` plus the materials it points to, addressed by citation key),
pynakes-native metadata with JabRef as opt-in interop, a canonical `format`
command, a native hierarchical group tree, and a resource-oriented command
tree. This remains an alpha: backward compatibility for the Python API, CLI
syntax, and JSON envelopes is not guaranteed until v1.0.

### Added

New commands and command families:

- **`format`** — deterministic, idempotent, layout-only whole-file rewrite with
  pynakes' preferred field ordering, indentation, trailing commas, and blank
  lines between entries. Preserves value expressions (bare macros,
  quoted/braced atoms, `#` concatenation) and retained source text;
  `--preserve-field-order` keeps custom fields in source order. `--check` exits
  1 when a file needs formatting (CI gate), `--stdout` prints without writing,
  `--recursive` walks a tree, and `format - --stdout` reads stdin.
- **`ref` family** — `ref add`, `ref import`, `ref show`, `ref edit`,
  `ref remove`. `ref import <identifier>` resolves DOI/arXiv metadata (with
  `--fetch` to also pull Pinax materials); `ref add` creates a manual entry.
  `ref show` / `ref edit` read and transactionally patch a single unique key
  (duplicate keys return a conflict rather than guessing). An under-specified
  invocation — `ref add` without a key, `ref edit` without change options —
  prompts interactively for the type and required fields (unsupplied ones only)
  using the library's lint rules. Interactive mode requires a terminal and
  errors under `--json` or headless stdin.
- **`tex` family** — manage the TeX sources that cite the library (the
  `tex-sources` metadata key): `list`, `add`, `remove`, `clear`, and `scan`
  (report/tag cited entries; formerly the `used` command).
- **`asset` family** — `asset fetch` downloads Pinax materials; `asset check`
  validates linked files and Pinax manifest state, with `--fix` to reconcile
  drift.
- **`corpus` family** — `corpus combine` / `split` / `batch`. `corpus split
  --minimal` emits a standalone one-entry snippet without the source library's
  metadata blocks or materials.
- **`groups list-entries <name>`** — query group-tree membership (descendant
  propagation by default, `--strict` for JabRef exact-match).
- **`metadata remove <key>`** deletes a single metadata key (auto-detecting the
  namespace, or `--namespace` to disambiguate); **`metadata adopt-jabref`** opts
  a native library into JabRef projection.

Pinax corpus layer (opt-in materials on disk, addressed by citation key):

- Offline `FileStore` foundation: `files-dir` metadata, deterministic material
  paths, presence scans, orphan/drift detection, provenance manifests, and
  Pinax-aware `corpus combine` / `split`.
- arXiv preprint download (PDF plus safe source-archive extraction) and
  open-access published-PDF download via OpenAlex, with a CrossRef fallback and
  bundled URL-construction overrides for major publishers.
- Institutionally entitled published PDFs (`asset fetch --published --access
  institutional`, using access already provided by your network, VPN, or proxy)
  and supplementary PDFs (`--supplement`). Downloads validate PDF magic bytes,
  treat authentication HTML as a skip, and record access context in provenance.
- A single `fetch-policy` metadata key (`preprint`, `published`, `source`,
  `bestpdf`; default `bestpdf`) replaces the old boolean flags, with
  per-invocation overrides `--preprint` / `--published` / `--source` /
  `--supplement` / `--bestpdf`.
- Self-documenting dot-separated material filenames: `<key>.published.pdf`,
  `<key>.preprint.pdf`, `<key>.source/`, plus recognized `.supplement.pdf` and
  `.erratum.pdf`.
- `dedupe merge` reconciles duplicate keys' materials onto the surviving key,
  preserving provenance rows and respecting `--dry-run`.
- `asset fetch` streams downloads with human progress (kept off JSON stdout) and
  reports the `files-dir` path; `ref add --fetch` and `ref import --fetch`
  import-then-fetch.

Metadata and groups:

- **pynakes-native metadata by default.** A fresh `init` seeds native `dialect`
  and `key-pattern` keys in `pynakes-meta` and emits no `jabref-meta`; `--jabref`
  (or `metadata adopt-jabref`) opts into a JabRef projection, after which aliased
  native keys are mirrored into their `jabref-meta` counterparts so JabRef never
  sees a stale value. Introduces a canonical metadata schema
  (`core` / `schema` / `jabref`) read through fallback-aware accessors, and
  `metadata set` value validation for known keys.
- **Native hierarchical group tree.** A `group-tree` key in `pynakes-meta`
  stores a hierarchy with full JabRef group-type parity (Explicit, Keyword,
  Search), bidirectionally projected to and from JabRef's `grouping` block and
  the flat `groups:` format. Keyword and Search groups are evaluated dynamically
  at query time. CRUD via `groups tree` / `add-group` / `remove-group` /
  `rename-group` / `move-group` / `update-group`; large trees are written across
  continuation lines.

Normalize, keys, and formatting:

- **Entry sorting in `normalize`** compatible with JabRef's `saveOrderConfig`,
  with a repeatable `--sort-by` override (e.g. `--sort-by author --sort-by
  year:desc`) and BibTeX-compatible crossref-parent ordering.
- **`normalize` adopts JabRef metadata as native keys** and can regenerate every
  citation key when `normalize-keys: true` / `--keys on` is set, renaming any
  Pinax materials to match.
- **Eight more JabRef v5.15 `saveActions` formatters**, plus additional
  JabRef-compatible citation-key markers (`authorlast`, `authIniN`, `authorIni`,
  `authorsN`); marker casing (`[auth]` / `[Auth]` / `[AUTH]`) now controls the
  output case.
- **CSV export** via `convert --to csv` (export-only; CSV does not round-trip).

Interop, CLI, and API:

- Resource-grouped `--help` panels and a matching `capabilities.command_groups`
  field.
- Citekey and `.bib`-file shell completion.
- Optional `file` argument with single-`.bib` auto-detection on every
  single-file command.
- `--backup` on all write commands, opt-in and off by default (writes are
  already atomic and re-parse-validated).
- `BibEntry.resolve()` / `BibFile.resolve()` shorthands for the read-only
  BibLaTeX inheritance view.

### Changed

- **Command tree reorganized into resource sub-apps.** Whole-library transforms
  stay flat (`normalize`, `convert`, `dedupe`, `lint`, `verify`, `enrich`,
  `search`, `inspect`); operations on a resource move under a noun:
  `add` / `import` / `remove` → `ref …`, `sources` / `used` → `tex …` /
  `tex scan`, `fetch` / `files check` → `asset fetch` / `asset check`,
  `combine` / `split` / `batch` → `corpus …`. The JSON envelope, exit codes, and
  per-command flags are unchanged.
- **`init` is pynakes-native by default** — native keys in `pynakes-meta`, no
  `jabref-meta` unless `--jabref`. `init` is also excluded from library
  auto-detection so omitting its path can't clobber an existing local `.bib`.
- **Metadata namespace routing is file-context-aware.** A JabRef-native key is
  written to `jabref-meta` only when the file is already JabRef-tracked;
  otherwise it stays in `pynakes-meta`.
- **`ref add` / `ref edit` interactivity is driven by the invocation, not a
  flag.** The `--interactive` / `-i` flag is removed: interactive mode triggers
  when the invocation is under-specified (`ref add` without a key, `ref edit`
  without change options). It now requires a terminal — under `--json` or
  headless stdin it errors with `InvalidInput` instead of blocking on a prompt.
- **`ref add` warns when the new entry is missing required fields.** A
  non-interactive `ref add KEY` still creates a bare stub, but now reports a
  warning (in the human output and the JSON `warnings` array) naming the
  required fields absent for the entry type, using the same rules as lint and
  interactive prompting.
- **`search` ranks results by match strength by default** (`key` > `title` >
  `author` > other fields > `groups` / `abstract`, file order as tiebreak);
  `--no-rank` restores raw file order.
- **Published-PDF resolution filters repository-hosted URLs** — arXiv, PMC, and
  institutional repositories are no longer misidentified as the version of
  record — and pre-validates candidate URLs with a HEAD request.
- **`enrich --published` promotes already-linked preprints** — an arXiv entry
  with both DOI and journal metadata becomes `@article` while keeping its
  `eprint` and related preprint fields.
- Provider transport consolidated under `providers/`, and `_fetch_text` uses
  httpx by default.
- The source distribution now includes the complete test suite, conformance
  corpus, fixtures, and opt-in agent-evaluation harness for downstream testing.
- Parser-conformance baseline pinned to TeX Live 2026 (BibTeX 0.99d, BibLaTeX
  3.21, Biber 2.21); `combine --dedupe` treats differing raw spelling as a
  conflict even when parsed fields match; required-field linting is
  dialect-aware.

### Fixed

- **`ref remove` no longer doubles the blank line** where an entry was deleted;
  the removal now consumes one adjacent separator when another block follows.
- **`fields rename` / `move` / `append` / `clear` match field names
  case-insensitively**, so a mixed-case name (e.g. `ArXiv`) no longer silently
  matches nothing.
- **Human-readable past-tense verbs for commands not ending in `e`.** Success
  lines read "Added", "Converted", "Repaired", "Linked" instead of "Addd",
  "Convertd", "Repaird", "Linkd".
- **Braced field values with a literal `%`** (e.g. `100% yield`) now parse and
  round-trip instead of being mistaken for line comments.
- **Metadata and `format` placement.** `pynakes-meta` stays at the top and
  `jabref-meta` at the file end; multiline group trees and colon-bearing group
  names survive `format` and reparsing; canonical formatting is idempotent and
  preserves retained source constructs (duplicate `@string`,
  malformed-but-round-trippable blocks, non-block text).
- **Citation-key title markers convert leading TeX math to text** — `\phi`,
  `\varphi`, `\Phi` contribute `Phi`; math delimiters and wrappers like
  `\ensuremath{...}` no longer leak into generated keys.
- **Usage errors keep the JSON contract.** Omitting a `.bib` that can't be
  auto-detected on a multi-positional command (`ref remove`, `fields rename`, …)
  now reports `InvalidInput` — or a reframed `{"status":"error",…}` (exit 1) —
  under `--json`, instead of a raw Click usage error. Without `--json`, humans
  still get Click's usage text and exit code 2.
- **Structured error reporting.** `keys check --json` includes duplicate-key
  findings with `severity`; `verify --online` reports `provider_error`
  separately from `doi_unresolved`; DOI errors name the provider; duplicate-key
  reports include entry indices; duplicate-key parser logging is lowered to
  `INFO` so it no longer appears alongside JSON on stderr.
- **arXiv and publisher fetch edge cases.** PDF-only arXiv submissions land in
  `skipped` (not `failed`) while preserving a PDF fetched in the same call;
  non-PDF publisher responses are skipped instead of saved as `.pdf`;
  `corpus split` no longer crashes routing an entry to a materials-less
  destination; a symlinked `.bib` anchors `files-dir` at the link path.
- Single-library auto-detection ignores RevTeX `*Notes.bib` auxiliaries; bare
  check commands and `keys repair` auto-detect the lone local `.bib`.
- `normalize --dry-run --diff --json` keeps valid BibTeX for a final braced
  field with no trailing comma and reports modified entries even when duplicate
  keys are present.
- `keys generate KEY FILE` regenerates a single key by default (`--all` for the
  whole library) and updates matching citations in linked TeX sources.
- List-valued metadata uses a shared convention — writers emit comma-separated
  values, readers still accept legacy semicolons — and `tex-sources` is merged
  across the JabRef and pynakes namespaces.
- Declare Click as a direct runtime dependency for CLI discovery and shell
  completion, fixing clean CI installs with newer Typer releases.
- **Group-tree CRUD persists metadata-only changes.** `groups add-group` (and
  `remove`/`rename`/`move`/`update-group`) reported success while writing nothing
  when the change touched only the `group-tree` metadata with no entry edit: the
  engine staged metadata mutations for the surgical renderer only on
  `metadata set`, so group-tree edits made straight to the model were never
  emitted (`modified: false` despite `metadata_changed: 1`). Metadata rendering
  is now derived from the pristine source snapshot, so all supported metadata
  mutations persist without operation-specific staging.
- **Surgical edits preserve the identity of byte-identical blocks.** Rendering
  previously found an entry by its raw text and replaced the first match, so
  editing the second of two identical duplicate-key entries could modify the
  first physical entry while the structured plan reported the second. The
  engine now snapshots exact source spans and applies validated offset edits;
  entry removals and metadata replacements use the same positional mechanism.
- **`is_dirty` reflects actual staged work.** It is now derived from rendered
  output plus deferred Pinax transactions instead of merely recording that a
  mutating command ran, so setting metadata to its existing value no longer
  makes `reload()` require `force=True` when nothing would be discarded.
- **`corpus combine --out X` where `X` is also an input no longer aborts.** A
  self-combine previously raised a `SameFileError` copying a Pinax material onto
  itself; `copy_materials_from` now skips a copy whose source and destination
  resolve to the same file. A self-combine also keeps the library's own
  `files-dir` instead of silently renaming it to the `--out` basename, and a
  non-self combine that changes the derived `files-dir` emits a warning.
- **`keys rename`/`generate` succeed on a library with no TeX sources.** Renaming
  a key when none are configured (no argument and no `tex-sources` metadata) is
  now a zero-update success with a warning rather than a `NoTeXSources` error — a
  fresh library has no manuscript linked yet. Explicitly passing sources that
  resolve to no `.tex` files remains an error.
- **`groups add-entry` keeps the group-tree in sync.** Adding an entry to a group
  absent from an existing `group-tree` previously wrote only the entry's
  `groups={}` field, leaving an orphan membership invisible to `groups tree`,
  `groups list`, and JabRef. When a tree exists the group is now registered as a
  node so the views agree; flat, tree-less libraries keep entry-field-only groups.

## [0.4.0] - 2026-06-26
Complete single-file BibTeX/BibLaTeX maintenance engine
with parser conformance later pinned for the public alpha to TeX Live 2026
(BibTeX 0.99d, BibLaTeX 3.21, Biber 2.21).

### Parser and round-trip fidelity

- Custom BibTeX/BibLaTeX parser with byte-for-byte round-trip fidelity; atomic,
  re-parse-validated writes; surgical minimal-diff editing.
- Handles `{…}`/`(…)` entry delimiters, nested/quoted values, escaped characters,
  multiline fields, `@string` macros (with concatenation and case-insensitive
  lookup), `@preamble`, and `@comment` blocks.
- `@string`, `#` concatenation, and BibLaTeX inheritance (`crossref`, `xdata`,
  `xref`, sets) resolved for field consumers while the original source remains
  available for round-trip writes. `BibFile.resolved_fields()` follows biber's
  default data-model inheritance (own > xdata > crossref; `xref`/sets opaque).
- Arbitrary BibLaTeX entry types (`@online`, `@set`, `@xdata`, …) and custom
  data-model fields pass through without a closed schema.
- Versioned conformance corpus pinned to TeX Live 2026; differential tests against
  `bibtex 0.99d` and `biber --tool`; property-based tests (Hypothesis) for
  parenthesis-delimited entries and all modifying operations.

### Commands

- **`init`** — create a new library with a metadata profile (`--type`,
  `--key-pattern`); `--from <file>` copies another library's maintenance
  conventions (dialect, key pattern, `saveActions`, journal/lint settings). Atomic
  write; refuses to overwrite unless `--force`.
- **`inspect`** — structured read of entries, strings, preamble, and comments;
  `--resolved` includes each entry's inherited field view.
- **`lint`** — required-field validation, key-pattern and journal-style checks,
  undefined BibTeX string references, cross-entry consistency findings (`--strict`
  for CI gating; multi-file aggregate envelope).
- **`keys generate|check|rename|repair`** — JabRef-compatible key generation
  (honors `keypatterndefault` and per-type metadata); passing a key regenerates a
  single entry, while `--all` regenerates the whole library.
- **`fields rename|move|append|clear|protect-title`** — surgical field edits with
  optional `--where` predicate filtering.
- **`groups list|add-entry|remove-entry`** — manage JabRef group membership.
- **`asset check`** — validate linked-file references.
- **`normalize`** — `saveActions`-driven formatter pipeline; DOI canonicalization;
  month macro normalization; author normalization; journal abbreviation/expansion
  (`--journal-style abbreviated|full`). Consolidates metadata with
  `pynakes-meta` at the top and `jabref-meta` at the file end.
- **`convert`** — BibTeX↔BibLaTeX dialect conversion; export to CSL-JSON, RIS,
  MODS, or EndNote tagged text (`--to csl-json|ris|mods|endnote`); import from
  those interchange formats (`--from csl-json|ris|mods|endnote`).
- **`add`** — import a reference by DOI, arXiv identifier, or journal article URL
  (nature.com articles, APS journals). Auto-detects identifier type; inserts before
  trailing metadata. Only metadata is fetched — no PDFs downloaded.
- **`search`** — free-text and field-scoped library search with `--where`
  filtering, field restriction, limits, and JSON output.
- **`used`** — detect/tag/export entries cited in LaTeX `.tex`/`.aux` sources;
  `--out cited.bib` extracts a cited-only subset. Falls back to `tex-sources`
  metadata.
- **`dedupe check|merge`** — detect and conservatively merge duplicate works.
- **`verify`** / **`enrich`** — opt-in `--online` lookups against authoritative
  metadata; `--published` checks (verify) or promotes (enrich) preprints to their
  published version.
- **`metadata list|set`** — inspect and update `jabref-meta`/`pynakes-meta`
  library settings.
- **`combine`** — union several `.bib` files into one; `--dedupe` collapses
  identical same-key entries, exits 2 on conflicts.
- **`split`** — route entries into multiple outputs by predicate (`--where`
  expression, `*`, `used`/`unused`, `group "Name"`); first-match or `--copy`.
- **`batch`** — transactional multi-operation edits: one preview, one commit;
  nothing written if any step fails.

### JabRef compatibility

- Full `saveActions` formatter suite (all JabRef v5.15 formatters).
- JabRef v5.15 metadata vocabulary fully classified; `jabref-meta` and
  `pynakes-meta` namespaces merged (pynakes overrides jabref).
- `.pre-commit-hooks.yaml` — `pynakes-lint`, `pynakes-keys-check`,
  `pynakes-files-check`, `pynakes-dedupe-check`.

### Agent and CI surface

- Stable JSON envelope + exit codes (0/1/2) on every command; `--dry-run`,
  `--diff`, `--json`; structured `plan` objects on every modifying command.
- `capabilities --json` — self-describing per-command schemas, error-code catalog,
  and predicate/search-query grammars.
- Single-library auto-discovery: when the current directory has exactly one `.bib`
  file, the library path can be omitted.
