# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-06-23

First feature-complete pre-release. The full single-file maintenance engine is
in place; this release stabilizes the public API before 1.0.

### Added
- **Complete operation set**: `inspect`, `lint`, `groups`, `keys`
  (generate/check/repair/rename), `fields` (with `--where`), `files check`,
  `normalize`, `convert`, `journals` (abbreviate/expand/check), `doi import`,
  `used`, `dedupe` (check/merge), `verify`, `published`, `enrich`, `merge`,
  `split`, `batch`.
- **`engine.Collection`** — the load → stage → preview/diff → commit lifecycle;
  atomic, re-parse-validated writes; external-change detection; `reset()`/`reload()`.
- **JabRef v5.15 `saveActions` parity**: all formatters (`normalize_names`,
  `normalize_date`, `normalize_month`, `normalize_page_numbers`, `latex_cleanup`,
  `unicode_to_latex`, `latex_to_unicode`, `html_to_latex`, `html_to_unicode`,
  `capitalize`, `lower_case`, `upper_case`, `sentence_case`, `title_case`,
  `ordinals_to_superscript`, `units_to_latex`). Formatter pipelines run in
  configured order; unsupported formatters reported as structured warnings.
  Full pinned-version JabRef metadata vocabulary classified as known. Golden-vector
  test suite anchored to JabRef v5.15 commit `1eb3493f`.
- **Lintable library profiles**: `lint` reads merged `jabref-meta`/`pynakes-meta`
  and flags key-pattern, journal-style, required-field, and title-protection
  deviations; `lint --strict` makes them fail for CI gating. Profile schema
  documented in `docs/guides/library-profile.md`.
- **`pynakes-meta` namespace** for settings JabRef cannot represent; merged view
  (pynakes overrides jabref) consumed by `lint`, `normalize`, and key generation.
  Written as one consolidated `key: value` block.
- **Structured `plan` object** on every modifying command — machine-readable
  staged changes (added/removed/renamed/modified entries with per-field old/new
  values) alongside the textual `diff`. Computed against pre-change state so a
  `--dry-run` plan matches the committed one.
- **Self-describing `capabilities --json`** with `command_schemas` (per-command
  arguments, options, and types derived from the live CLI), `error_codes` catalog,
  and `predicate_grammar` for `fields --where` / `split --to`.
- **`merge` and `split`** projection commands (`pynakes.setops`): `merge` combines
  files (`--dedupe` collapses identical same-key entries, exits 2 on conflicts);
  `split` routes entries into multiple outputs by predicate (`--where` expression,
  `*`, `used`/`unused`, or `group "Name"`), first-match by default or `--copy`.
- **`batch`** — transactional multi-operation edits: a JSON sequence of operations
  applied atomically (one preview, one commit; nothing written if any step fails).
  Operation vocabulary in `capabilities` under `batch_operations`.
- **`--strict` gate flag** on `lint`, `keys check`, `files check`, `dedupe check`,
  `verify`; all accept multiple `.bib` files with an aggregate envelope.
- **`.pre-commit-hooks.yaml`** shipping `pynakes-lint`, `pynakes-keys-check`,
  `pynakes-files-check`, `pynakes-dedupe-check` hooks.
- **`tex-sources` metadata key**: records `.tex` files/directories that cite a
  library; `keys rename` and `used` fall back to it automatically.
- **`normalize` consolidates JabRef metadata** to the file end on save (idempotent,
  toggle with `--metadata-formatting`).
- **Journal tables accept JabRef's headerless CSV format** from
  [abbrv.jabref.org](https://github.com/JabRef/abbrv.jabref.org) directly.
- **`pynakes --version`** flag.
- **Pinned public Python API** documented in `docs/guides/api-stability.md`; semver
  policy stated (breaking changes require a major bump post-1.0).

### Changed
- **`pynakes-meta` written as one consolidated `key: value` block** (both the
  older one-comment-per-key and `key:value;` spellings still read).
- **Dropped pre-release metadata-key aliases**: `pynakes-normalize-*`,
  `pynakes-protected-terms`, `pynakes-journal-table`, `pynakes-ltwa-table`,
  `pynakes-tex-sources`, `required-fields`. Canonical keys only.
- **`convert` requires an explicit `--to biblatex|bibtex`**; no longer infers
  the target from `databaseType`.
- **Backups are opt-in** (`--backup`); writes are already atomic and
  re-parse-validated, so the silent `.bak` was redundant.
- **`metadata set` appends new blocks at the file end** (JabRef canonical
  position) instead of prepending above entries.
- **Metadata types renamed**: `MetadataBlock`, `MetadataUpdate`,
  `DuplicateMetadataError` (previous `JabRef`-prefixed names were never public).
- **`capabilities.VERSION`** derives from installed package metadata; cannot
  drift from `pyproject`.
- **`normalize` does not abbreviate journals by default**; leave journals
  untouched unless a style is configured.
- **`DuplicateMetadata`** error code (was `DuplicateJabRefMetadata`).

### Fixed
- Journal abbreviation no longer mangles already-correct titles (stray spaces,
  dropped section letters) or emits half-abbreviated results for partially-known
  journals (now declines and reports `unknown` unless every significant word resolves).
- Empty-citation-key entries (`@article{,...}`) are now parsed, round-tripped
  byte-for-byte, reported by `lint` as `empty_key`, and repaired by `keys generate`.
- Unified diffs were double-spaced; output is now a standard unified diff.
- `lint` no longer gives zero-entry files (wrong file or junk content) a clean
  bill of health; emits a `no_entries` warning instead.
