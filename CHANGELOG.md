# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`keys rename` and `keys generate` now respect `--backup` for `.tex` files.**
  Previously the `.tex` source rewrite always created a `.bak` (via
  `save_plain_text`'s default) regardless of the `--backup` flag; now `.tex`
  backup is controlled by `--backup` like the `.bib` side.

### Added

- **`asset fetch` now shows human progress for long downloads.** The CLI uses
  Rich progress rendering for non-JSON `asset fetch` runs and keeps progress off
  JSON stdout. Binary material downloads now stream through `httpx`, with byte
  progress for arXiv PDFs/source archives and open-access published PDFs while
  preserving the existing injectable fetch seams for tests and library callers.

- **pynakes-native metadata by default; JabRef as opt-in interop.** A fresh
  `pynakes init` library now seeds native `dialect` and `key-pattern` keys in
  `pynakes-meta` and emits no `jabref-meta` at all; the new `init --jabref` flag
  (or `metadata adopt-jabref`) opts into the JabRef projection. Adds native
  `key-pattern`/`key-pattern-<entrytype>` keys aliasing JabRef's
  `keypatterndefault`/`keypattern_<entrytype>` (read native-first via
  `library_key_pattern`). On a JabRef-tracked file, changing an aliased native
  key (`dialect`, `sort-order`, `key-pattern`) is **mirrored** into its
  `jabref-meta` counterpart so JabRef never sees a stale value (reported in
  `metadata set`'s `mirrored` field); `metadata list` now warns when an aliased
  pair disagrees. `saveActions`-absorb and a symmetric "go-native" strip are
  noted as not-yet-implemented.

- **Canonical metadata schema with a JabRef compatibility adapter.** Split
  `metadata.py` into a `pynakes.metadata` package (`core`, `schema`, `jabref`)
  so domain code (`normalize`, `lint`, `integrity`, the engine) reads pynakes'
  own concepts through fallback-aware accessors instead of JabRef's literal
  keys. Adds native `dialect` and `sort-order` `pynakes-meta` keys, aliasing
  JabRef's `databaseType`/`saveOrderConfig` (read native-first, JabRef second);
  `library_dialect` replaces `library_database_type` (kept as a back-compat
  alias). Documents the boundary in a new
  [JabRef compatibility guide](docs/guides/jabref-compatibility.md). Purely
  additive/internal: existing `.bib` files, the CLI/JSON contract, and
  `jabref-meta` behavior are unchanged.

- **Step 9: Open-access published PDFs.** `asset fetch` now resolves DOIs to
  open-access published PDFs via OpenAlex and downloads them as `<citekey>.pdf`
  when `fetch-published: true` is set in `pynakes-meta`. New injection points
  `published_url_fetcher` / `published_pdf_fetcher` make it testable without
  network. Requires `fetch-published: true` (default `false`). Includes
  deterministic on-disk caching of OpenAlex responses. (#9)

- **Step 11: DOI → arXiv backfill.** `enrich --published --online` now resolves
  DOI-backed published entries through OpenAlex, falling back to Semantic
  Scholar when OpenAlex lacks an arXiv location, and backfills arXiv `eprint`
  metadata when a link is present. The update is dialect-aware (`eprinttype` for
  BibLaTeX, `archiveprefix` for BibTeX), uses deterministic provider-response
  caching, and remains testable without network through injectable fetchers.

- **Agent beta eval has a broader task catalog.** The manual beta-test
  supervisor now chooses from concrete discovery, dry-run/diff, metadata,
  Pinax, structured-error, online provider, cache, and DOI → arXiv → Pinax
  source-recovery workflows instead of a thin generic prompt list.

### Fixed

- `normalize --dry-run --diff --json` now keeps valid BibTeX when normalizing a
  final braced field such as a DOI with no trailing comma, and its structured
  `plan` reports modified entries even when the bibliography already contains
  duplicate citation keys.
- `keys check --json` now includes duplicate-key findings in an `issues` array
  with `severity: error`, matching the severity-bearing shape agents already
  get from `lint --json` while preserving the existing duplicate summary fields.
- `verify --online --json` now reports provider/network failures as
  `provider_error` issues instead of folding them into `doi_unresolved`, so
  automated users can distinguish external lookup failures from DOI metadata
  problems without parsing the message text.
- `keys generate` now treats single-key regeneration as the default:
  `keys generate KEY FILE` derives the new key from entry metadata, while
  whole-library regeneration is explicit via `--all`. The old `--key` selector
  was removed. Shell completion no longer leaks an `InvalidInput` traceback
  while completing the key-first form in a directory with multiple `.bib` files.
  Generated renames now also update matching citations in linked `tex-sources`
  TeX files, making `generate` an automated metadata-derived `rename`.
- List-valued metadata now has a shared convention: commands write comma-separated
  values, while readers still accept legacy semicolon-separated values. Linked
  `tex-sources` values are merged across JabRef and pynakes metadata namespaces
  when read, and `tex add/remove/clear` canonicalize the setting back into
  `pynakes-meta` so stale namespace differences do not hide linked files.
- `--backup` is now exposed on the remaining write-capable surfaces:
  `init --force --backup` backs up an overwritten `.bib`, and
  `asset check --fix --backup` backs up the Pinax manifest before reconciling
  drift.

- Pinax `files-dir` resolution now anchors a symlinked `.bib` at the link path
  passed to `pynakes`, so `asset fetch` stores materials next to the linked
  bibliography instead of next to the link target.

- **PDF-only arXiv e-prints no longer count as a source-fetch failure.** When the
  e-print endpoint returns a PDF instead of a TeX/source archive (a PDF-only
  submission), `asset fetch` now records the entry under `skipped` with reason
  `no arXiv source archive (PDF-only submission)` instead of `failed`, matching
  the documented "graceful gaps" contract. A PDF fetched in the same call is
  preserved (it was previously discarded when the source step raised). A genuinely
  corrupt archive still lands in `failed`. New `ArxivSourceUnavailableError`
  (subclass of `ArxivFetchError`) distinguishes the two cases.

- **Usage errors under Typer 0.26+ now produce structured JSON with `--json`.**
  Typer 0.26 vendors its own exception hierarchy (`typer._click.exceptions`
  separate from `click.exceptions`).  `AutoBibGroup.invoke` and
  `AutoBibGroup.main` now catch both `click.UsageError` and
  `typer._click.exceptions.UsageError` so that missing-argument errors are
  still reframed as `{"status":"error",...}` under `--json` (exit 1) on newer
  Typer versions.

### Changed

- **`pynakes init` is now pynakes-native by default.** Previously a new library
  was seeded with JabRef-native `databaseType`/`keypatterndefault` blocks in
  `jabref-meta`, making every fresh file JabRef-tracked from birth. It now seeds
  the native `dialect`/`key-pattern` keys in `pynakes-meta` and emits no
  `jabref-meta` unless `--jabref` is passed. `--type`/`--key-pattern` now set the
  native keys. Existing files are unaffected; the `metadata` JSON contract is
  unchanged.

- **Provider transport consolidated into `providers/`.** External-service
  transport and response parsing now live with their provider client: byte
  fetching is a single `providers/_http.fetch_bytes` (replacing the duplicate
  `importer._fetch_url`); DOI content negotiation is `providers/doi.fetch_bibtex`;
  arXiv Atom fetch/parse, the `ArxivRecord` type, and PDF/source downloads are in
  `providers/arxiv`; and OpenAlex gains `oa_pdf_url_for_doi`. `integrity` now uses
  the shared `providers/_http.cache_path` instead of a private copy. `importer`,
  `fetch`, and `integrity` keep their public functions as thin wrappers that
  delegate to providers and translate `ProviderFetchError` into domain errors;
  the CLI, JSON envelope, exit codes, and behavior are unchanged.

- **Command tree reorganized into resource sub-apps.** Commands are now grouped
  by the resource they act on, following one rule: whole-library transforms stay
  flat (`normalize`, `convert`, `dedupe`, `lint`, `verify`, `enrich`, `search`,
  `inspect`), while operations on a many-of-a-kind resource live under a noun.
  Renamed paths:
  - `add` / `import` / `remove` → `ref add` / `ref import` / `ref remove`
  - `sources` (linked TeX files) → `tex`; `used` → `tex scan`
  - `fetch` → `asset fetch`; `files check` → `asset check`
  - `combine` / `split` / `batch` → `corpus combine` / `corpus split` / `corpus batch`

  The renamed `tex`/`asset` nouns also encode direction — TeX sources cite *into*
  the library, Pinax materials are what entries point *out* to — retiring the
  overloaded "source" term. The JSON envelope, exit codes, and per-command flags
  are unchanged.

- **`pynakes --help` now lists each sub-app's subcommands inline** (e.g.
  `ref → add, import, remove`), colored for clarity, so the grouped surface stays
  discoverable at a glance.

### Added

- **`tex` command family.** `pynakes tex` manages the list of TeX source files
  that cite the library (stored as the `tex-sources` metadata key). Subcommands:
  `list` (show linked sources), `add` (link one or more paths), `remove` (unlink
  paths), `clear` (unlink all), and `scan` (report/tag entries cited in those
  sources). More discoverable than the generic `metadata set tex-sources` — path
  arguments are positional, the bib file is specified via `--file` or
  auto-detected.

- **`ref import` and manual `ref add`.** DOI/arXiv metadata resolution lives
  under `pynakes ref import <identifier> [file]`, while `pynakes ref add <key>
  [file] --field name=value ...` creates a manually specified entry.
  `ref import --fetch` keeps the import-then-fetch Pinax workflow.

- **Dedupe material merge for Pinax libraries.** `pynakes dedupe merge` now
  reconciles duplicate keys' Pinax materials onto the surviving citation key,
  preserving moved provenance manifest rows and respecting `--dry-run`. It
  reports a dedupe conflict instead of overwriting an existing survivor material
  kind or ambiguous manifest state.

- **Manual agent beta-test evaluation harness.** Added an opt-in real-agent
  runner under `tests/agent_eval` that has a supervisor generate task scenarios
  and a fresh beta-tester agent drive `pynakes` from the published CLI/docs
  surface. Normal pytest uses a deterministic fake provider; real `codex` runs
  are manual via `PYNAKES_RUN_AGENT_EVAL=1` and can include online DOI/arXiv
  workflows with `--include-online`.

- **`--help` and `capabilities` group commands by nature.** The top-level
  `pynakes --help` now organizes commands into panels — *Inspect & validate*,
  *Edit references*, *Materials (pinax)*, *Corpus (multiple files)*, *Create* —
  instead of one flat list. `capabilities` gains a `command_groups` field
  mirroring the same grouping. The taxonomy lives in one place
  (`capabilities.COMMAND_GROUPS`), shared by both surfaces.

- **`metadata adopt-jabref` — opt-in JabRef metadata tracking.** pynakes-native
  libraries now keep their settings in `pynakes-meta` by default; `jabref-meta`
  is no longer injected into a file that never had it. Run `adopt-jabref` to
  establish a JabRef projection: it relocates any JabRef-native keys stranded in
  `pynakes-meta` into `jabref-meta` and anchors a `databaseType` block, so the
  file works in JabRef without losing its pynakes settings. From then on the
  library is *JabRef-tracked* and JabRef-native keys are written to `jabref-meta`
  automatically. Running it again once tracked is a no-op. The JSON envelope
  reports `moved_keys`, `database_type_added`, and `was_tracked`.

- **Entry sorting in `normalize`, compatible with JabRef's `saveOrderConfig`.**
  When a library carries JabRef's `@Comment{jabref-meta: saveOrderConfig:...}`
  with order type `specified`, `normalize` now reorders entries to match it —
  the same multi-criterion `field;descending` model JabRef writes from its
  "Save sort order" settings (order types `original`/`table` keep the current
  order). A new repeatable `--sort-by` option overrides it for one run:
  `--sort-by author --sort-by year:desc` sorts by author ascending then year
  descending; `citationkey` (or `key`) sorts by citation key; `year` sorts
  numerically; `--sort-by original` keeps the current order. Reported in the
  JSON envelope as `operations.sorted_entries`.

### Changed

- **Metadata namespace routing is now file-context-aware (interop, not parity).**
  `set_metadata` previously routed every JabRef-native key (e.g. `databaseType`)
  into `jabref-meta` by owner, regardless of the file. It now routes a
  JabRef-native key to `jabref-meta` only when the file is already JabRef-tracked
  (carries `jabref-meta` blocks); otherwise it — like every pynakes-owned key —
  stays in `pynakes-meta`. An existing JabRef library keeps its convention
  unchanged; a pynakes-native file stays free of `jabref-meta` until you run
  `metadata adopt-jabref`. New `library_is_jabref_tracked()` and `remove_metadata()`
  helpers support this.

### Fixed

- **Usage errors no longer break the JSON contract.** When the library
  argument was omitted and could not be auto-detected (no local `.bib`, or more
  than one), commands with additional positionals (e.g. `ref remove`, `fields
  rename`, `groups add-entry`) leaked a raw Click "Missing argument" usage error
  to stderr with exit code 2, bypassing the `--json` envelope. Such commands now
  report the real cause (`InvalidInput`: "No/Multiple *.bib files found") and any
  residual usage error is reframed as a structured `{"status":"error",...}`
  envelope with exit code 1 under `--json`. Without `--json`, humans still get
  Click's usage text and exit code 2. Relatedly, `init` is now excluded from
  library auto-detection: it creates a library, so omitting its path no longer
  substitutes (and risks clobbering) an existing local `.bib` — it reports the
  missing argument instead.
- Declare Click as a direct runtime dependency for CLI discovery and shell
  completion support, fixing clean CI installs with newer Typer releases.

### Fixed (agent beta eval issues)

- **Agent beta eval accepts nondeterministic task labels.** The supervisor can
  now emit task kinds such as `check`, `repair`, `import`, or `online` without
  the harness rejecting the run before the beta tester starts. The schema still
  validates task shape and online/offline gating.
- **Online command docs match the current CLI.** The LLM integration guide and
  generated Pinax agent rules now describe `ref import`, `asset fetch`,
  `verify --online`, and `enrich --online` as the network-backed paths, while
  `ref add` is documented as manual local entry creation. The guide also includes
  a concise `.bib` plus TeX citation validation recipe using `tex scan`.
- **Import dry-run failures now say no file was written.** When
  `import --dry-run --json` fails during DOI/arXiv lookup, the error response
  includes `dry_run: true`, `modified: false`, and a no-write message so agents
  can distinguish provider failure from an applied change.
- **Search argument order in docs now matches the live CLI.** The synopsis and
  examples in `docs/guides/llm-integration.md` and `docs/guides/usage.md` had
  `pynakes search <file> <query>` but the CLI expects `pynakes search <query>
  [file]`. Docs have been updated to match the CLI.
- **Duplicate-key log noise in JSON mode.** The parser emitted duplicate-key
  diagnostics at `WARNING` level, appearing on stderr alongside JSON output.
  Lowered to `INFO` level so it no longer shows in normal terminal output.
  Duplicate keys remain structurally available via `lint`, `inspect`, and
  `keys check`.
- **Verify/enrich DOI error messages now name the provider.** When a DOI lookup
  fails, the error now explicitly reads `via doi.org content negotiation` so
  users can tell where the lookup went and whether a retry might help.
- **Verify reports "all lookups failed" when nothing was verified.** Both human
  and JSON output now include an explicit note when `checked=0` and errors are
  present, rather than silently reporting "verified 0 DOI-backed entries".
- **Duplicate-key reports include entry indices.** Added
  `EntryStore.duplicate_key_instances()` returning `{key: [indices]}`. Lint,
  `inspect`, `keys check`, and Pinax error messages now show entry position
  (e.g. `#0, #3`) so users can identify which physical entry a message refers to.

## [0.5.0] - 2026-06-28

### Added

- **`remove` command** (`pynakes remove <bib> <citekey>...`). Removes entries
  by citation key through the standard lifecycle. In a pinax, removes the
  entry's materials from `files-dir` by default (`--keep-files` opts out).
  Dry-run correctly skips all filesystem side effects.
- **Citekey shell completion.** Register Click shell-completion callbacks on
  `remove`, `fetch`, `keys rename`, `groups add-entry`, and `groups
  remove-entry`. The `.bib`-file completer also shows citekeys alongside the
  filename when a single `.bib` is auto-detectable. Usable via
  `eval "$(pynakes --show-completion bash)"` / `zsh` / `fish`.
- **`--backup` flag on all write commands.** Added to `add`, `dedupe_merge`,
  `fetch`, all `fields` subcommands, `groups`, `keys`, `metadata set`, `used`,
  and `integrity enrich`. The `remove` command had its declared `--backup`
  param wired through (was silently ignored).
- **Optional `file` argument on all single-file commands.** Every command that
  takes a `.bib` file argument now auto-detects a single `.bib` in the current
  directory when omitted — matching the behavior previously available only on
  `add`, `convert`, `fetch`, `inspect`, `enrich`, `normalize`, `remove`, and
  `search`.
- **Output emission consolidation.** Migrated `used`, `combine`, and `split`
  from manual `typer.echo(_json.dumps(...))` to the canonical `_emit()` helper.

- Add `BibEntry.resolve(lookup)` and `BibFile.resolve(entry)` as ergonomic
  shorthands for the existing read-only BibLaTeX inheritance view.
- Add the offline Pinax `FileStore` foundation: recognized `files-dir` metadata,
  deterministic material paths, presence scans, orphan detection, and
  `Bibliography.files`.
- Add the Pinax arXiv download core with injectable PDF/source fetchers, safe
  source archive extraction, and atomic preprint material writes.
- Complete the core Pinax layer: `inspect --json` material annotations,
  `files check` Pinax presence/orphan/drift reporting plus `--fix`, provenance
  manifests with canonical preprint selection, Pinax-aware `combine`/`split`,
  and coordinated material moves for key edits.
- Add `pynakes add --fetch`, which imports a reference and then downloads the
  new entry's configured Pinax arXiv materials.

### Changed

- Move the documented parser-conformance baseline for the v0.5 alpha to TeX
  Live 2026 (BibTeX 0.99d, BibLaTeX 3.21, Biber 2.21).
- Treat differing raw BibTeX spelling as a `combine --dedupe` conflict even
  when parsed fields match, preserving round-trip intent.
- Derive subset, split, and merge output libraries through `BibFile.derive()`,
  preserving library-level raw string declarations consistently.
- Make required-field linting dialect-aware: BibTeX keeps the traditional rule
  set, while BibLaTeX libraries use the default BibLaTeX data-model entry types
  and aliases.
- Fall back to a full rewrite when an engine operation edits an unsnapshotted
  raw entry, avoiding an empty staged diff.
- Remove the unused per-entry `BibEntry.jabref_metadata` field; JabRef and
  pynakes metadata remain library-level state on `BibFile`.
- Derive `BibFile.jabref_metadata`, `BibFile.pynakes_metadata`, and
  `BibFile.metadata` from metadata blocks instead of storing separate mutable
  dicts.
- Make lint profile and DOI checks read inherited field views consistently, and
  align source-tree fallback version reporting.

### Fixed

- `remove --dry-run` no longer removes Pinax materials from disk; it only
  previews what would be removed (regression introduced in the initial `remove`
  implementation).
- Tighten broad exception handling in DOI metadata fetching, file writes, and
  Pinax filesystem rollback paths.
- Fix small reviewer-flagged edge cases in lint field-view handling, search
  field filters, title-protection heuristics, `html_to_latex`, and batch
  operation dispatch.

### Internal

- Consolidate duplicated utilities: `_metadata_value`, `_metadata_list`, and
  `_metadata_bool` moved from `lint.py` and `normalize.py` into `metadata.py`
  as public helpers; callers import from there.
- Fix `save_text` backup-rename ordering: the original file is now only renamed
  to `.bak` after the temp file has been written and validated, so a crash or
  validation failure can never lose the original.
- Merge `save_plain_text` into `save_text` as a `validate=False` default;
  `save_plain_text` is kept as a thin alias pending removal.

### Documentation

- Mark v0.5 as a public alpha and document that backward compatibility is not
  guaranteed for the Python API, CLI syntax, or JSON envelopes until v1.0.
- Document the optional Pinax corpus mode while preserving the plain `.bib`
  maintenance engine as the base identity.
- Clarify that `MetadataBlock.normalized_value` is a display/semantic view,
  while `MetadataBlock.value` and `raw` preserve the parsed/source forms.
- Document that parsed `BibEntry.fields` are semantic values after BibTeX string
  interpolation, with original expressions preserved in `raw_content`.

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
- **`files check`** — validate linked-file references.
- **`normalize`** — `saveActions`-driven formatter pipeline; DOI canonicalization;
  month macro normalization; author normalization; journal abbreviation/expansion
  (`--journal-style abbreviated|full`). Consolidates JabRef metadata to file end.
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
