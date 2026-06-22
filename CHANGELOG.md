# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **JabRef-parity field formatters + golden-vector test suite**: new
  `pynakes.formatters` implements `normalize_date` (→ ISO `yyyy-mm-dd`/`yyyy-mm`),
  `normalize_month` (→ `#mmm#`), and `normalize_page_numbers` (→ `start--end`)
  to match JabRef exactly. `normalize` applies them per the file's `saveActions`
  field map. `tests/test_jabref_parity.py` locks behavior with input→expected
  vectors lifted from JabRef's own formatter tests (JabRef, MIT License);
  remaining `normalize_names` AuthorList-parser parity is captured as `xfail`
  vectors and tracked in DEVPLAN as a 1.0 gap.
- **JabRef `saveActions` drive `normalize` defaults (feature-parity step toward
  1.0)**: `normalize` now reads JabRef's own `saveActions` field-formatter
  configuration so a JabRef-configured library normalizes consistently — when
  `saveActions` is enabled, `normalize_names` on a name field enables author
  normalization and `clean_up_doi`/`short_doi` on `doi` enables DOI cleanup;
  if those formatters are absent, pynakes defers and leaves the field alone.
  Explicit CLI flags and `pynakes-meta` keys still override. New
  `metadata.parse_save_actions` / `SaveActions` / `library_save_actions`. Also
  recognizes the `saveOrder` and `blgFilePath` JabRef metadata keys. The
  remaining parity gaps (date/month/page normalization, encoding formatters) are
  tracked in DEVPLAN as the 1.0 gate.
- **`pynakes-meta` metadata namespace (superset of `jabref-meta`)**: pynakes now
  reads and writes a second, structurally identical top-level comment,
  `@comment{pynakes-meta: key:value;}`, for settings JabRef cannot represent.
  Parsing scans both namespaces; `BibFile` exposes `pynakes_metadata(_blocks)`
  alongside `jabref_metadata(_blocks)` plus a merged `metadata` property
  (pynakes overrides jabref on conflict) and `metadata_blocks` (both, in source
  order) — the view `lint`, `normalize`, and key generation read. `metadata set`
  routes a key automatically for maximum JabRef compatibility (JabRef-native
  keys → `jabref-meta`, everything else → `pynakes-meta`), overridable with
  `--namespace jabref|pynakes`; unknown keys are accepted into `pynakes-meta`
  but still require `--allow-unknown` for `jabref-meta`. `inspect`/`metadata
  list` report both namespaces. The `jabref.py` module is renamed `metadata.py`.
- **Git-workflow gating**: the read-only checks `lint`, `keys check`,
  `files check`, and `dedupe check` gained a `--strict` flag (exit `1` on a
  finding) — joining the existing `verify --strict` — so any of them can gate a
  build. All five gate checks now accept **multiple `.bib` files**: a single
  file keeps its byte-stable per-file JSON envelope, while multiple files emit
  an aggregate `{status, action, strict, files, summary}` envelope (an
  unreadable file becomes a per-file error object and always fails the run).
  Capabilities advertises this via `supports_multiple_files` and `gate_commands`.
- **pre-commit integration**: a `.pre-commit-hooks.yaml` ships
  `pynakes-lint`, `pynakes-keys-check`, `pynakes-files-check`, and
  `pynakes-dedupe-check` hooks. A new [Git Workflows](docs/guides/git-workflows.md)
  guide documents pre-commit and GitHub Actions recipes.
- **Integrity and enrichment workflows**: new `pynakes.integrity` API and
  top-level `verify`, `published`, and `enrich` commands. Provider metadata
  access is opt-in via `--online`, cached deterministically, and covered by
  fixture-stubbed tests. `verify --strict` is CI-friendly, `enrich` only fills
  missing fields, and `published --apply` can add arXiv-published DOI/journal
  metadata while preserving the preprint pointer.
- **Deduplication and merge**: new `pynakes.dedupe` API and
  `pynakes dedupe check|merge` CLI detect duplicate works by normalized stable
  identifiers (DOI, arXiv, PMID, PMCID, ISBN) and conservative fuzzy
  title+author+year matching. `merge` keeps the first entry, copies missing or
  safely richer data, unions delimited fields, removes duplicate entry blocks,
  supports `--dry-run`/`--diff`/`--json`, and exits 2 with field-level conflict
  reports instead of guessing on ambiguous values.
- **`Collection` engine API**: `pynakes.engine.Collection` now owns the one-file
  load → stage → preview/diff → commit lifecycle. It wraps one `BibFile`,
  exposes read-only views and delegated operation methods, stages DOI imports
  and JabRef metadata updates, writes atomically through the validated text I/O
  path, supports `reset()`/`reload()`, and raises `ExternalModificationError`
  when a file changed underneath before commit.
- **Consistent citation-key rename**: new `pynakes keys rename <file> <old>
  <new> <tex-source>...` updates one unique key in the `.bib` file and matching
  TeX citation commands across supplied `.tex` files/directories, with
  `--dry-run`/`--diff`/`--json`, target-key conflict detection, and backups for
  changed source files.
- **Linked-file validation**: new `pynakes files check` command and
  `pynakes.files` API parse JabRef `file` descriptors, including multiple
  semicolon-delimited attachments and directory links. Relative paths resolve
  against the `.bib` directory, repeated `--root` directories, and JabRef
  `fileDirectory*` metadata. Reports `ok`, `missing`, `wrong_type`, and
  `unresolved` statuses without modifying the library.
- **Structured JabRef library metadata support**: top-level `jabref-meta` blocks
  are now parsed into ordered metadata records while preserving raw comments for
  round-trip fidelity. `inspect --json` exposes both flat metadata values and
  structured blocks. New `pynakes metadata list` and `pynakes metadata set`
  commands inspect/update known JabRef metadata keys; unknown keys are preserved
  and require `--allow-unknown` to write, while duplicate matching blocks return
  a conflict instead of guessing.
- **Phase 4 test hardening.** Added `hypothesis` as a dev dependency and a new
  property-based suite (`tests/test_property.py`) asserting parse→write→parse
  preserves every key/type/field, that unmodified entries write back verbatim,
  and that the parser never raises anything but `ParseError` on arbitrary input.
  New `tests/test_stress.py` (large libraries, mass key-repair),
  `tests/test_error_recovery.py` (parse errors with line numbers, latin-1
  fallback, atomic-write backup restoration), `tests/test_workflows.py`
  (end-to-end CLI sequences, dry-run/actual parity, the structured-error/exit-code
  contract), and `tests/test_editing.py` (direct unit tests of the surgical
  raw-text primitives). Overall coverage is now 93%.

### Fixed
- **Empty-citation-key entries are no longer silently dropped.** The parser
  required at least one key character (`@article{,` was discarded from the
  model while surviving on disk via surgical writes), hiding the most-broken
  entry from `inspect`/`lint`. Such entries are now parsed with an empty key,
  round-trip byte-for-byte, are reported by `lint` as an `empty_key` error, and
  get a real key from `keys generate`.
- **Unified diffs are no longer double-spaced.** `generate_diff` joined
  newline-terminated lines with an extra `\n`, doubling every line in the
  `diff` field of every modifying command; output is now a standard unified
  diff.
- **`lint` no longer gives non-BibTeX input a clean bill of health.** A file
  that parses to zero entries (wrong file or junk content) now emits a
  `no_entries` warning instead of reporting `0 issues`.

### Changed
- **Renamed the core nouns for a coherent library metaphor.** The single-`.bib`
  engine handle `Volume` is now **`Collection`** (the working unit — "a slice of
  references covering one aspect of a topic"); a future directory of Collections
  is the **`Library`** (the corpus) and its derived search index is the
  **`Catalogue`** (Phase 7). Supporting model renames cleared the resulting
  collisions: `BibLibrary` → `BibFile` (it models one file, not a library) and
  `EntryCollection` → `EntryStore` (freeing "Collection" for the concept layer).
  `VolumeCommitResult` → `CommitResult` and `Collection.from_library` →
  `Collection.from_bibfile`. CLI behavior and the JSON envelope are unchanged.
- **`--where` filters can now target an entry by citation key** (`key == "..."`)
  and by `key exists`, alongside the existing `type` and field conditions. This
  makes the manual resolution suggested by `dedupe merge` executable through the
  CLI. The `--where` grammar is now documented in the LLM integration guide.
- Clarified the `unknown_journal` warning message (now "No abbreviation table
  entry for journal '…'; left unchanged") so it no longer reads as a failure to
  produce output.
- CLI modifying commands now dogfood `Collection` for dry-run diffs and writes while
  preserving the existing JSON envelope and command behavior.
- **Consolidated CLI boilerplate and removed dead code** (no behavior change):
  a shared `_preview_or_commit()` helper replaces the repeated dry-run/commit
  branching in `_finish_mod`, `keys rename`, and `used`; the `doi import`
  citation-key conflict now routes through the existing `_emit_conflict` helper;
  the `used` command reuses the `_entries()` pluralizer; and the unused
  `_parse_jabref_metadata` wrapper in `bibtex_parser.py` was deleted.
- **Consolidated journal duplication** (follow-up to the earlier audit):
  `load_journal_table` and `load_ltwa_table` now share a single `_sniff_rows`
  CSV/TSV reader, and the `unknown_journal` warning shape lives once in
  `journals.unknown_journal_warnings`, used by both the `journals` CLI commands
  and the `normalize` routine (previously duplicated in `cli.py` and
  `normalize.py`).

### Added
- **`journals`** sub-app: dedicated `pynakes journals abbreviate`/`expand`
  (both honoring `--dry-run`/`--diff`/`--json` and accepting `--journal-table`
  /`--ltwa-table`) plus a read-only `pynakes journals check [--json]` that
  reports, per distinct journal title, whether it resolves via an exact
  mapping, LTWA generation, or is unknown. Backed by a new public
  `journals.classify_journal`.
- **`convert`** (`convert.py`): BibTeX ↔ BibLaTeX conversion in both directions
  via `pynakes convert <file> --to biblatex|bibtex [--dry-run] [--diff]
  [--json]`. Maps fields (`journal`↔`journaltitle`, `address`↔`location`,
  `school`↔`institution`), thesis types (`@phdthesis`/`@mastersthesis` ↔
  `@thesis` + `type`), and combines/splits `year`+`month` ↔ ISO `date`. Edits
  are surgical (minimal diff); unknown fields, groups, and comments are
  preserved; existing target fields are never clobbered (a warning is reported
  instead), and values that cannot be safely translated are left untouched with
  a warning.
- **`capabilities`** (`capabilities.py`): machine-readable description of
  supported operations and commands, kept in sync with the actual CLI.
  `pynakes capabilities [--json]`.

### Changed
- **Split the two "agents" audiences.** `AGENTS.md` (and its `CLAUDE.md`
  symlink) is now a contributor guide for coding agents working *on* the repo
  (layout, checks, invariants). The runtime guide for LLMs *using* the CLI
  moved to `docs/guides/llm-integration.md` (added to the docs nav), where its
  stale command surface was corrected (`keys generate` signature, `used
  --group`, capabilities now implemented; removed a nonexistent `groups
  entries`). README/FAQ/DEVPLAN pointers updated.
- **Unified JSON envelope across all commands**: every modifying command now
  emits the same keys — `status, action, file, dry_run, modified,
  modified_entries, warnings` — plus command-specific fields and an optional
  `diff`. The `used` command no longer uses `input_path`/`would_modify_file`
  (now `file` + `modified`), and `warnings` is always present. Documented in
  AGENTS.md and guarded by tests.
- **Structured error handling across all CLI commands**: a missing/unreadable
  file, malformed BibTeX, or invalid argument is now reported as a structured
  `{"status":"error",...}` object on stdout (honoring `--json`) with exit code
  1, instead of a Python traceback. Deliberate conflicts (e.g. duplicate DOI)
  still exit 2 with options. This honors the documented agent contract.
- **Consolidated duplication** found in an audit:
  - Author-name parsing now lives only in `authors.py` (`split_name_list`,
    `last_name`); `keys.py` delegates to it instead of re-deriving last names.
  - `unique_key` is defined once in `keys.py`; `doi.py` imports it.
  - `lint.py` validates DOIs via `doi.normalize_doi` rather than a private
    regex, so "what is a valid DOI" has a single definition.
  - CLI modifying commands share `_finish_mod`/`_safe` helpers, cutting
    repeated commit/emit/error scaffolding.

### Added (Phase 2 core operations)
- **Phase 2 core operations** and their CLI commands:
  - **`groups`** (`groups.py`): `list_groups`, `list_entries_in_group`,
    `add_to_group`, `remove_from_group`. CLI: `pynakes groups list`,
    `groups add-entry`, `groups remove-entry`.
  - **`keys`** (`keys.py`): deterministic `AuthorYearTitle` key generation,
    duplicate detection, and duplicate repair (numeric `_2` suffixes that avoid
    existing keys). CLI: `pynakes keys check`, `keys generate`, `keys repair`.
  - **`fields`** (`fields.py`): `rename`, `move` (non-clobbering), `append`
    (de-duplicating), and `clear`, each with an optional `--where` query filter
    (`FIELD contains "x"`, `FIELD = "x"`, `FIELD exists`, plus `type`). CLI:
    `pynakes fields rename|move|append|clear`.
  - **`lint`** (`lint.py`): duplicate keys, missing required fields (per entry
    type, tolerating BibTeX/BibLaTeX variants like journal/journaltitle and
    year/date), malformed/missing DOI, and malformed JabRef `groups`. CLI:
    `pynakes lint`.
  - **`inspect`** (CLI): structure, encoding, line ending, duplicate keys, and
    lint issues, with `--json`.
  - All modifying commands support `--dry-run`, `--diff`, and `--json`, with
    `.bak` backups and atomic, re-parse-validated writes.
- **`editing.py`** — shared surgical raw-text editing primitives
  (`set_raw_field`, `remove_raw_field`, `rename_raw_field`, `set_raw_key`,
  `splice_into_text`) and entry-level helpers that keep an entry's `fields`
  dict and `raw_content` in sync. Edits touch only the changed field/key, so
  diffs stay minimal and all other formatting is byte-preserved. The `used`
  tagging code and all Phase 2 operations build on this single implementation.
- **`pynakes used`** — detect which entries are cited across a collection of
  `.tex`/`.aux` files (or directories, scanned recursively). Reports
  used/unused/missing keys; handles the natbib & biblatex `\cite` families,
  bracketed optional args, TeX comments, and `\nocite{*}`. Supports:
  `--out` (export a subset `.bib` of cited entries), `--group`/`--keyword`
  (tag used entries in place), and `--dry-run`/`--diff`/`--json`.
  In-place tagging edits entry text surgically and splices it into the original
  file, so the diff shows only the added field — all other formatting (blank
  lines, brace-protected capitalization, field order) is preserved byte-for-byte.
- `io.save_text()` for writing pre-serialized BibTeX (used by surgical edits),
  sharing the atomic-write + backup + re-parse-validation guarantees of `save_bib`.
- Project initialization and CLI command scaffold (`inspect`, `groups`, `keys`,
  `fields`, `lint`, `capabilities` — currently stubs).
- `pyproject.toml` with dependencies and metadata; pytest + ruff configuration.
- **Phase 1 foundation**: data model (`BibEntry`, `BibFile`), custom BibTeX
  parser and writer with round-trip preservation, atomic file I/O with backups,
  and unified-diff utilities.
- `EntryStore`: an ordered, duplicate-key-tolerant container backing
  `BibFile.entries`, with `get_all()` and `duplicate_keys()` helpers. Enables
  the planned duplicate-key detection/repair features.
- Regression tests for round-trip fidelity (capitalization braces, field order,
  CRLF line endings, empty field values, latin-1 detection).

### Changed
- `BibFile.entries` is now an `EntryStore` rather than a `dict`; it keeps
  a dict-like read API (first match wins) while preserving duplicate keys.
- Parser no longer raises on duplicate citation keys; it preserves them and logs
  a warning, leaving detection/repair to the linter.
- Encoding is now detected from raw file bytes in `io.py` (UTF-8 → latin-1) and
  recorded on the library, instead of the previous no-op detection on a `str`.

### Fixed
- **Data corruption**: writer no longer doubles braces (`{DNA}` → `{{DNA}}`),
  which had corrupted capitalization-protection braces on every modified-entry
  write.
- **Field reordering**: reconstructed entries preserve original field order
  instead of sorting alphabetically.
- **Line endings**: `\r\n` files are read via bytes (no universal-newline
  translation) and written with the library's line ending, so CRLF survives a
  round-trip.
- Empty field values (e.g. `note = {}`) are preserved instead of being dropped.
- Removed dead `jabref_metadata` extraction that was collected then discarded;
  it is now attached to `BibFile`.

### Security

## [0.1.0] - (Planned)

Initial release with core functionality:
- BibTeX parser and writer with round-trip preservation
- Group management
- Citation key generation and repair
- Field operations
- Linting and validation
- Format conversion (BibTeX ↔ BibLaTeX)
- Journal abbreviation/expansion
- Comprehensive CLI with dry-run and JSON output
