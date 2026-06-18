# pynakes

`pynakes` is a headless bibliography-maintenance toolkit for BibTeX, BibLaTeX, and JabRef-compatible `.bib` libraries.

It is designed for researchers, scripts, and LLM-assisted workflows that need to make small, explicit, reviewable changes to bibliography files without corrupting human-curated metadata.

Named after the ancient Greek *Pinakes*, the bibliographic catalog of the Library of Alexandria.

## Key principles

- **Safe by default**: Never silently destroy data. Preserve unknown fields, custom fields, comments, and file formatting.
- **Explicit operations**: No monolithic "rewrite this file" function. Each operation is atomic, testable, and composable.
- **Inspectable**: All modifying commands support `--dry-run`, `--diff`, and `--json` output for verification before commit.
- **Conservative transformations**: Format conversions and deduplication report conflicts rather than guessing.

## Installation

For local development:

```bash
git clone https://github.com/your/pynakes.git
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

> **v0.1 is feature-complete and in the testing/polish phase (Phase 4).** The
> full BibTeX maintenance workflow is usable: inspect, lint, edit fields/groups,
> repair keys, import by DOI, analyze cited/unused entries, convert between
> BibTeX and BibLaTeX, abbreviate/expand journal titles, and validate JabRef
> linked files. The top-level `normalize` routine provides a daily maintenance
> pass for titles, JabRef-style author/editor lists, DOI fields, and known
> journal titles, and `capabilities` exposes a machine-readable description of
> the tool for agents. Merge-oriented features are still pending. See
> [DEVPLAN.md](DEVPLAN.md) for the phased build plan and
> [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

### Implemented

- [x] Core data model (`BibEntry`, `BibLibrary`, duplicate-preserving entry collection)
- [x] BibTeX read/write with round-trip preservation for unmodified entries
- [x] JabRef-compatible `groups` parsing plus list/add/remove commands
- [x] Duplicate citation-key detection and repair
- [x] Deterministic citation-key generation (`AuthorYearTitle` pattern)
- [x] JabRef citation-key pattern metadata support (`keypatterndefault`, `keypattern_<entrytype>`)
- [x] Full JabRef library metadata support: parse, preserve, inspect, and safely update known `jabref-meta` blocks
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
- [x] Dry-run, unified diff, and JSON output for modifying commands
- [x] Atomic writes, validation-before-write, and `.bak` backups
- [x] CLI commands for the implemented operations

### Still planned

- [ ] Deduplication and merge workflows
- [ ] Linked-file repair
- [ ] Advanced search/query DSL
- [ ] Configuration profiles
- [ ] Provider-specific DOI fallbacks/enrichment (Crossref, DataCite)

### Out of scope

- GUI, browser extension, word processor integration
- Full PDF metadata extraction
- Reference manager replacement
- Web app or cloud sync
- Database storage
- Arbitrary shell execution
- LLM API calls inside the package

## Roadmap

### v0.1.1
- Deduplication and merge
- Provider-specific DOI fallbacks/enrichment

### v0.2
- Conservative BibTeX → BibLaTeX conversion
- Configuration profiles
- User-provided abbreviation tables
- Linked-file repair

### Future (v0.3+)
- MCP server (`pynakes-mcp`) for Claude and other agents
- Advanced search/query DSL
- Batch operations from files
- Cross-library linking

## For scripted and LLM-assisted workflows

`pynakes` is designed to be safe for programmatic use:

- **Structured output**: `--json` returns machine-readable results with status, warnings, and errors.
- **Dry-run by default for exploration**: Use `--dry-run` to preview any operation.
- **Capabilities introspection**: `pynakes capabilities --json` describes supported operations.
- **Atomic operations**: Each command is idempotent and composable; you can chain operations safely.
- **Clear error codes**: Exit code 0 = success; 1 = error; 2 = conflict (safe to retry with user input).

See the **[LLM Integration guide](docs/guides/llm-integration.md)** for the full
command surface, the JSON envelope, and recommended workflows.

Example: using `pynakes` with Claude via MCP (future):

```python
# Claude can call pynakes operations atomically
claude.invoke_tool("pynakes.groups.add_entry", {
  "file": "refs.bib",
  "entry_key": "Andolfatto2021",
  "group": "CBDC / Banking",
  "dry_run": True
})
# Returns: {"status": "success", "modified": True, "diff": "...", "warnings": [...]}

# Then Claude can ask the user to confirm
# Or apply it directly if already authorized
claude.invoke_tool("pynakes.groups.add_entry", {
  "file": "refs.bib",
  "entry_key": "Andolfatto2021",
  "group": "CBDC / Banking",
  "dry_run": False
})
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
