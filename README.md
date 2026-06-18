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

### Lint your library

```bash
# Human-readable output
pynakes lint refs.bib

# Structured output
pynakes lint refs.bib --json
```

### Convert BibTeX to BibLaTeX (preview only)

```bash
pynakes convert refs.bib --to biblatex --dry-run --diff
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
- **Reports conflicts**: When an operation cannot safely decide between options (e.g., merging two entries with conflicting authors), it reports the conflict and exits with code 2 rather than guessing.

## Current status

> **v0.1 is in active development.** The package is not yet usable; the items
> below are the v0.1 targets. See [DEVPLAN.md](DEVPLAN.md) for the phased build
> plan and [ARCHITECTURE.md](ARCHITECTURE.md) for the design. This list is the
> source of truth for what "done" means — check items off as they land.

### Planned for v0.1

- [ ] Core data model (`BibEntry`, `BibLibrary`)
- [ ] Read/write with round-trip preservation
- [ ] Parse `groups` field; list groups; add/remove entries to groups
- [ ] Detect duplicate citation keys
- [ ] Generate citation keys (simple: `AuthorYearTitle` pattern)
- [ ] Field operations: rename, move, append, clear
- [ ] Lint: duplicate keys, missing DOI, malformed DOI, missing required fields
- [ ] Conservative BibTeX → BibLaTeX conversion
- [ ] Journal abbreviation (built-in table)
- [ ] Dry-run, diff, and JSON output
- [ ] Atomic writes and backups
- [ ] CLI scaffold with all command groups

### Deferred to later versions

- [ ] DOI import (command structure ready; network call stubbed)
- [ ] Deduplication and merge (algorithms designed; not integrated)
- [ ] AUX/TeX-based sublibrary extraction (command ready)
- [ ] Linked-file checking and repair
- [ ] Advanced search/query DSL
- [ ] Configuration profiles
- [ ] User-provided journal abbreviation tables
- [ ] Title capitalization protection

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
- DOI import integration (network calls)
- Deduplication and merge
- AUX extraction

### v0.2
- Configuration profiles
- User-provided abbreviation tables
- Title capitalization protection
- Linked-file validation

### Future (v0.3+)
- MCP server (`pynakes-mcp`) for Claude and other agents
- Advanced search/query DSL
- Batch operations from files
- Cross-library linking

## For scripted and LLM-assisted workflows

`pynakes` is designed to be safe for programmatic use:

- **Structured output**: `--json` returns machine-readable results with status, warnings, and errors.
- **Dry-run by default for exploration**: Use `--dry-run` to preview any operation.
- **Capabilities introspection**: `pynakes capabilities --json` lists supported operations.
- **Atomic operations**: Each command is idempotent and composable; you can chain operations safely.
- **Clear error codes**: Exit code 0 = success; 1 = error; 2 = conflict (safe to retry with user input).

Example: using `pynakes` with Claude via MCP (future):

```python
# Claude can call pynakes operations atomically
claude.invoke_tool("pynakes.groups.add_entry", {
  "file": "refs.bib",
  "entry_key": "Andolfatto2021",
  "group": "CBDC / Banking",
  "dry_run": True
})
# Returns: {"would_modify": True, "diff": "...", "warnings": [...]}

# Then Claude can ask the user to confirm
# Or apply it directly if already authorized
claude.invoke_tool("pynakes.groups.add_entry", {
  "file": "refs.bib",
  "entry_key": "Andolfatto2021",
  "group": "CBDC / Banking",
  "dry_run": False
})
```

## Not affiliated with JabRef

`pynakes` is compatible with JabRef-format `.bib` files and preserves JabRef-specific metadata (groups, special fields). It is **not** affiliated with, endorsed by, or derived from JabRef. It is a separate, standalone tool.

## Development

Run tests:

```bash
pytest
```

Lint and format:

```bash
ruff check .
ruff format .
```

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Please:

1. Open an issue to discuss the feature or bug.
2. Write tests for any new functionality.
3. Keep changes focused and reviewable.
4. Ensure `pytest` and `ruff` pass.
