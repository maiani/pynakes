# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Changed

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
