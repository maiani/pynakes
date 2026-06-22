# pynakes

**A headless, round-trip-faithful maintenance toolkit for BibTeX, BibLaTeX, and JabRef-compatible `.bib` libraries.**

`pynakes` makes small, explicit, reviewable changes to bibliography files — without reformatting, reordering, or corrupting the metadata a human or reference manager curated. It is built for researchers, scripts, CI pipelines, and LLM-assisted workflows.

Named after the *Pinakes*, Callimachus's catalog of the Library of Alexandria — antiquity's first bibliography.

## Why pynakes

- **Round-trip fidelity.** An entry you don't touch is written back byte-for-byte. pynakes never normalizes whitespace, reorders fields, or re-quotes values behind your back — so diffs stay tiny and reviewable.
- **JabRef-compatible — and a superset.** It reads JabRef's own metadata and `saveActions`, normalizing the way JabRef would; it adds the `pynakes-meta` namespace only where JabRef has no equivalent.
- **Reviewable by design.** Every modifying command previews as a unified diff (`--dry-run --diff`) before anything is written, then writes atomically with a `.bak` backup.
- **Conservative.** Conversions, deduplication, and enrichment report conflicts and exit `2` rather than guessing.
- **Built for agents and CI.** Stable JSON output and exit codes, machine-readable `capabilities`, and `--strict` / pre-commit gates that lint a bibliography like source code.

## Installation

For local development:

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev]"
```

For end users (future):

```bash
pip install pynakes
```

## Quick start

### List entries and groups

```bash
pynakes inspect refs.bib
pynakes groups list refs.bib
```

### Inspect or update JabRef library metadata

```bash
pynakes inspect refs.bib --json
pynakes metadata list refs.bib --json

# Preview setting a known jabref-meta block
pynakes metadata set refs.bib databaseType biblatex --dry-run --diff

# Apply it
pynakes metadata set refs.bib databaseType biblatex
```

### Make a safe change with preview

```bash
# Preview the change (no file modified)
pynakes fields rename refs.bib journal journaltitle --dry-run --diff

# Apply it
pynakes fields rename refs.bib journal journaltitle
```

### Add an entry to a group

```bash
# See what would change
pynakes groups add-entry refs.bib SomeKey2024 "Economics" --dry-run --diff

# Apply it
pynakes groups add-entry refs.bib SomeKey2024 "Economics"
```

### Rename a citation key safely

```bash
# Preview the .bib key edit plus citation updates in TeX sources
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/ --dry-run --diff

# Apply it after reviewing the diff
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/
```

### Import a reference by DOI

```bash
# Preview the imported BibTeX entry
pynakes doi import refs.bib 10.5555/example --dry-run --diff

# Use the provider's citation key instead of generating one
pynakes doi import refs.bib 10.5555/example --key-source provider

# Force an explicit citation key
pynakes doi import refs.bib 10.5555/example --key Example2024

# Apply it
pynakes doi import refs.bib 10.5555/example
```

### Lint your library

```bash
# Human-readable output
pynakes lint refs.bib

# Structured output
pynakes lint refs.bib --json
```

### Gate a repository (pre-commit / CI)

```bash
# Fail the build if any .bib has errors (duplicate/empty keys, missing fields).
# The read-only checks accept multiple files and a --strict exit gate.
pynakes lint refs.bib chapters/*.bib --strict
```

pynakes ships a `.pre-commit-hooks.yaml`, so a paper repo can keep its
bibliography clean automatically. See **[Git workflows: pre-commit & CI](docs/guides/git-workflows.md)**.

### Detect and merge duplicate works

```bash
# Report duplicate clusters by DOI/arXiv/other IDs and fuzzy title matching
pynakes dedupe check refs.bib --json

# Preview a conservative merge
pynakes dedupe merge refs.bib --dry-run --diff

# Apply it after reviewing conflicts/diff
pynakes dedupe merge refs.bib
```

### Verify and enrich references

```bash
# Local DOI checks only
pynakes verify refs.bib --json

# Opt in to provider metadata, cached beside the .bib file
pynakes verify refs.bib --online --strict --json

# Fill missing DOI/date/journal fields conservatively
pynakes enrich refs.bib --online --dry-run --diff

# Check arXiv preprints for published DOI/journal metadata
pynakes published refs.bib --online --json
pynakes published refs.bib --online --apply --dry-run --diff
```

### Normalize your library

```bash
# Preview the standard maintenance pass
pynakes normalize refs.bib --dry-run --diff

# Apply title protection, author/editor normalization, DOI normalization,
# exact journal mappings, and LTWA-style journal abbreviation
pynakes normalize refs.bib

# Override the library metadata/default journal behavior
pynakes normalize refs.bib --journal-style none

# Keep author names in their current order and only normalize separators
pynakes normalize refs.bib --author-style conservative

# Prefer a local exact journal table and/or LTWA word table
pynakes normalize refs.bib --journal-table journals.csv --ltwa-table ltwa.csv
```

Journal tables are CSV/TSV files with `title`, `abbreviation`, and optional
`issn` columns. LTWA tables use `Word` and `Abbreviation` columns, matching the
ISSN LTWA export shape.

### Protect title capitalization

```bash
# Protect acronyms and mixed-case terms in title fields
pynakes fields protect-title refs.bib --dry-run --diff

# Protect a title-like field and an explicit term
pynakes fields protect-title refs.bib --field booktitle --term Proceedings
```

### Check linked files

```bash
# Validate JabRef file fields
pynakes files check refs.bib
pynakes files check refs.bib --json

# Resolve relative links against an additional attachment directory
pynakes files check refs.bib --root ~/papers
```

## Safety model

Every operation that modifies a file:

1. **Validates before writing**: Checks for parse errors, conflicts, and missing required fields.
2. **Supports dry-run**: `--dry-run` shows what would change without modifying the file.
3. **Supports diff**: `--diff` shows a unified diff of the changes.
4. **Supports JSON output**: `--json` returns structured output for programmatic use.
5. **Atomically writes**: Writes to a temporary file, validates, then renames the original to a backup and moves the temp file into place. If anything fails, the original file is untouched.

Additionally:

- **Preserves user data**: Unknown fields, comments, file formatting, and JabRef metadata are preserved during round-trip parsing and writing.
- **Backups on write**: When a file is modified, a `.bak` file is created automatically (configurable; can be disabled).
- **Reports conflicts**: When an operation cannot safely decide between options (e.g., importing an already-present DOI), it reports the conflict and exits with code 2 rather than guessing.

## Current status

> **pynakes is feature-complete as a single-file engine and approaching 1.0.** The
> full maintenance workflow — including dedupe/merge, integrity/enrichment, the
> JabRef `jabref-meta` + `pynakes-meta` superset with `saveActions` parity, and
> pre-commit/CI gating — runs from the CLI, dogfooding the in-process `Collection`
> lifecycle (open, stage, preview/diff, commit, reset, reload, external-change
> detection). Remaining 1.0 work — full JabRef author-name normalization parity,
> public-API pinning, and the PyPI release — is tracked in [DEVPLAN.md](DEVPLAN.md);
> [docs/guides/architecture.md](docs/guides/architecture.md) covers the design.
> Not yet published to PyPI.

### Implemented

- [x] Core data model (`BibEntry`, `BibFile`, duplicate-preserving entry collection)
- [x] BibTeX read/write with round-trip preservation for unmodified entries
- [x] JabRef-compatible `groups` parsing plus list/add/remove commands
- [x] Duplicate citation-key detection and repair
- [x] Deterministic citation-key generation (`AuthorYearTitle` pattern)
- [x] Consistent citation-key rename across one `.bib` file and selected `.tex` sources
- [x] JabRef citation-key pattern metadata support (`keypatterndefault`, `keypattern_<entrytype>`)
- [x] Dual metadata namespaces: `jabref-meta` plus the `pynakes-meta` superset — parsed, merged (pynakes wins), preserved, and updated by `metadata set` with automatic namespace routing
- [x] JabRef `saveActions` parity: `normalize`'s author/DOI defaults and the `normalize_date`/`normalize_month`/`normalize_page_numbers` formatters follow the file's configured save actions
- [x] Field operations: rename, move, append, clear, with simple `--where` filters
- [x] Title capitalization protection for acronyms, mixed-case terms, and explicit terms
- [x] Top-level `normalize` command for title protection, JabRef-style author/editor list normalization, DOI normalization, exact journal mappings, and LTWA-style journal abbreviation/expansion
- [x] Lint: duplicate keys, missing DOI, malformed DOI, malformed groups, missing required fields
- [x] DOI import via DOI resolver BibTeX content negotiation
- [x] BibTeX ↔ BibLaTeX conversion (`convert`), preserving unknown fields, groups, and comments
- [x] Journal title abbreviation/expansion (`journals abbreviate|expand|check`) with exact, user, and LTWA-style sources
- [x] Machine-readable capability introspection (`capabilities --json`) matching the agent contract
- [x] AUX/TeX citation analysis, unused/missing reporting, group/keyword tagging, and subset export
- [x] Linked-file validation (`files check`) for JabRef `file` fields, with `.bib` directory, `--root`, and `fileDirectory*` resolution
- [x] `Collection` engine API for staged edits, previews/diffs, atomic commits, reset/reload, and external modification detection
- [x] Deduplication and conservative merge workflows (`dedupe check|merge`)
- [x] Integrity/enrichment workflows (`verify`, `published`, `enrich`) with opt-in cached provider lookups
- [x] Git-workflow gating: multi-file `--strict` checks (`lint`, `keys check`, `files check`, `dedupe check`, `verify`) and a `.pre-commit-hooks.yaml`
- [x] Dry-run, unified diff, and JSON output for modifying commands
- [x] Atomic writes, validation-before-write, and `.bak` backups
- [x] CLI commands for the implemented operations

### Still planned (toward 1.0 — see [DEVPLAN.md](DEVPLAN.md))

- [ ] Full JabRef author-name (`AuthorList`) normalization parity
- [ ] Remaining JabRef `saveActions` formatters (encoding/case conversions)
- [ ] Public-API pinning + 1.0 PyPI release
- [ ] Linked-file repair and provider-specific DOI search fallbacks

Beyond 1.0: a multi-file `Library`/`Catalogue` corpus engine and CSL-JSON/RIS interop.

### Out of scope

- GUI, browser extension, word processor integration
- Full PDF metadata extraction
- Reference manager replacement
- Web app or cloud sync
- Database storage
- Arbitrary shell execution
- LLM API calls inside the package

## Roadmap

The detailed, current plan lives in **[DEVPLAN.md](DEVPLAN.md)**. In short, pynakes
is heading to **1.0**: complete JabRef feature parity, a pinned public API, and a
PyPI release. The multi-file `Library`/`Catalogue` corpus engine and CSL-JSON/RIS
interop come after 1.0.

pynakes' agent interface is the **CLI itself** (capabilities introspection, JSON
output, dry-run, stable exit codes — see below). An MCP server is a *downstream*
concern — a companion built on the pinned API, or part of a corpus-management app —
not a planned part of the core engine.

## For scripted and LLM-assisted workflows

`pynakes` is designed to be safe for programmatic use:

- **Structured output**: `--json` returns machine-readable results with status, warnings, and errors.
- **Dry-run by default for exploration**: Use `--dry-run` to preview any operation.
- **Capabilities introspection**: `pynakes capabilities --json` describes supported operations.
- **Atomic operations**: Each command is idempotent and composable; you can chain operations safely.
- **Clear error codes**: Exit code 0 = success; 1 = error; 2 = conflict (safe to retry with user input).

See the **[LLM Integration guide](docs/guides/llm-integration.md)** for the full
command surface, the JSON envelope, and recommended workflows.

Example: an agent drives `pynakes` by calling the CLI as a tool — preview,
then apply:

```bash
# 1. Preview the change and show the diff to the user.
pynakes groups add-entry refs.bib Andolfatto2021 "CBDC / Banking" --dry-run --diff --json
# → {"status": "success", "modified": true, "diff": "...", "warnings": [...]}

# 2. Once authorized, re-run without --dry-run to apply it.
pynakes groups add-entry refs.bib Andolfatto2021 "CBDC / Banking" --json
```

## Development

Install with development tools:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Lint and format:

```bash
ruff check src tests
ruff format src tests
```

Install local pre-commit hooks:

```bash
pre-commit install
pre-commit run --all-files
```

GitHub Actions runs `ruff check`, `ruff format --check`, and `pytest` on
Python 3.11, 3.12, and 3.13 for pushes and pull requests.

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Please:

1. Open an issue to discuss the feature or bug.
2. Write tests for any new functionality.
3. Keep changes focused and reviewable.
4. Ensure `pytest` and `ruff` pass.
