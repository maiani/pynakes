# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- Document the optional Pinax corpus mode while preserving the plain `.bib`
  maintenance engine as the base identity.

## [0.4.0] - 2026-06-26
Complete single-file BibTeX/BibLaTeX maintenance engine
with parser conformance verified against TeX Live 2025 (BibTeX 0.99d, BibLaTeX 3.20,
Biber 2.20).

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
- Versioned conformance corpus pinned to TeX Live 2025; differential tests against
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
  (honors `keypatterndefault` and per-type metadata); `--key OLD` regenerates a
  single entry.
- **`fields rename|move|append|clear|protect-title`** — surgical field edits with
  optional `--where` predicate filtering.
- **`groups list|add-entry|remove-entry`** — manage JabRef group membership.
- **`files check`** — validate linked-file references.
- **`normalize`** — `saveActions`-driven formatter pipeline; DOI canonicalization;
  month macro normalization; author normalization; journal abbreviation/expansion
  (`--journal-style abbreviated|full`). Consolidates JabRef metadata to file end.
- **`convert`** — BibTeX↔BibLaTeX dialect conversion; export to CSL-JSON or RIS
  (`--to csl-json|ris`); import from CSL-JSON or RIS (`--from csl-json|ris`).
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
