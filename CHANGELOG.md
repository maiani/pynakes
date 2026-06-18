# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- **Phase 1 foundation**: data model (`BibEntry`, `BibLibrary`), custom BibTeX
  parser and writer with round-trip preservation, atomic file I/O with backups,
  and unified-diff utilities.
- `EntryCollection`: an ordered, duplicate-key-tolerant container backing
  `BibLibrary.entries`, with `get_all()` and `duplicate_keys()` helpers. Enables
  the planned duplicate-key detection/repair features.
- Regression tests for round-trip fidelity (capitalization braces, field order,
  CRLF line endings, empty field values, latin-1 detection).

### Changed
- `BibLibrary.entries` is now an `EntryCollection` rather than a `dict`; it keeps
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
  it is now attached to `BibLibrary`.

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
