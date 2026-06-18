# Architecture

Design and technical decisions behind pynakes.

> **Canonical source:** `ARCHITECTURE.md` at the repo root is the authoritative
> design document. This page is a docs-site summary; if the two disagree, the
> root file wins. (For example, `BibLibrary.entries` is an `EntryCollection`,
> not a dict.)

## Overview

pynakes is built with **safety**, **composability**, and **agent compatibility** in mind.

```
┌─────────────────────────────────────────────────┐
│ CLI (typer)                                     │
│  - Commands: inspect, lint, groups, keys, etc. │
│  - Flags: --dry-run, --diff, --json            │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ Operations (Domain Logic)                       │
│  - groups.py   (group management)              │
│  - keys.py     (citation keys)                 │
│  - fields.py   (field operations)              │
│  - lint.py      (validation)                   │
│  - doi.py       (DOI import)                   │
│  - normalize.py (maintenance routine)          │
│  - journals.py  (journal abbreviation sources) │
│  - usage.py     (citation usage analysis)      │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ Core (I/O and Data)                             │
│  - model.py         (dataclasses)              │
│  - bibtex_parser.py (parsing)                  │
│  - bibtex_writer.py (writing)                  │
│  - io.py            (file I/O)                 │
│  - diff.py          (diff generation)          │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
               .bib File
```

## Data Model

All data flows through two main dataclasses:

### BibEntry

```python
@dataclass
class BibEntry:
    key: str                                  # Citation key
    type: str                                 # Entry type (article, book, etc.)
    fields: dict[str, str]                    # Field key-value pairs
    raw_content: Optional[str] = None         # Original BibTeX for round-trip fidelity
    raw_comments: list[str] = field(...)      # Comments from the file
    jabref_metadata: dict[str, str] = field(...)  # JabRef metadata
    modified: bool = False                    # Track if entry was modified
```

### BibLibrary

```python
@dataclass
class BibLibrary:
    entries: EntryCollection                 # All entries, duplicate-key tolerant
    strings: dict[str, str] = field(...)     # @string definitions
    preamble: list[str] = field(...)         # @preamble declarations
    raw_comments: list[str] = field(...)     # File-level comments
    encoding: str = "utf-8"                  # File encoding
    line_ending: str = "\n"                  # Line ending style
```

## Design Principles

### 1. Safety First

- **No silent changes** — All mutations preview with `--dry-run` first
- **Atomic writes** — Operations are all-or-nothing
- **Automatic backups** — `.bak` created before any modification
- **Clear conflicts** — Ambiguous operations return options, not guesses

### 2. Round-Trip Fidelity

The parser stores `raw_content` for each entry. When writing:
- **Unmodified entries** use `raw_content` (zero-diff guarantee)
- **Modified entries** are reconstructed from fields

This ensures maximum format preservation and makes debugging easy.

### 3. Composability

Operations are independent:
- Each operation reads from disk, modifies in memory, writes to disk
- Operations can be chained: `lint` → `keys repair` → `normalize` → `verify`
- Agents can dry-run each step before committing

### 4. Agent Compatibility

- **Deterministic** — Same input always produces same output
- **Structured output** — JSON for all operations
- **Clear exit codes** — 0 (success), 1 (error), 2 (conflict)
- **Dry-run always works** — Never modifies files during preview

## Module Breakdown

### Core I/O (Phase 1)

| Module | Responsibility |
|--------|-----------------|
| `model.py` | Dataclass definitions |
| `bibtex_parser.py` | Parse BibTeX text → BibLibrary |
| `bibtex_writer.py` | Serialize BibLibrary → BibTeX text |
| `io.py` | Load/save with atomic writes and backups |
| `diff.py` | Generate and format diffs |

### Operations (Phase 2)

| Module | Responsibility |
|--------|-----------------|
| `groups.py` | Group management (add, remove, list) |
| `keys.py` | Citation key repair and generation |
| `fields.py` | Field operations (rename, move, append, clear) |
| `lint.py` | Validation and issue detection |

### Metadata and Normalization

| Module | Responsibility |
|--------|-----------------|
| `doi.py` | DOI import and DOI normalization helpers |
| `authors.py` | JabRef-style and conservative author/editor normalization |
| `journals.py` | Exact journal mappings and LTWA-style abbreviation |
| `normalize.py` | Daily maintenance orchestration |
| `usage.py` | AUX/TeX citation usage analysis |

### CLI (Phase 2-4)

| Module | Responsibility |
|--------|-----------------|
| `cli.py` | Typer app and command routing |
| `output.py` | JSON and human-readable output formatting |

## Parsing Strategy

The parser is **conservative**: it preserves unknown fields aggressively.

```python
def parse_bib(text: str) -> BibLibrary:
    # 1. Detect encoding and line endings
    # 2. Split into entries, strings, preambles
    # 3. For each entry:
    #    - Extract key and type
    #    - Parse field=value pairs
    #    - Store raw_content for unmodified round-trip
    # 4. Detect JabRef metadata from @comment lines
    # 5. Return BibLibrary with all data
```

### Error Handling

Parse errors include line numbers for context:

```json
{
  "status": "error",
  "error": "ParseError",
  "message": "Malformed entry at line 42: missing closing brace",
  "file": "refs.bib",
  "line": 42
}
```

## Writing Strategy

The writer respects the original formatting:

```python
def write_bib(lib: BibLibrary) -> str:
    for entry in lib.entries.values():
        if entry.raw_content and not entry.modified:
            # Unmodified: use raw content (zero diff)
            output += entry.raw_content
        else:
            # Modified: reconstruct with proper formatting
            output += reconstruct_entry(entry)
    # Add strings, preambles, comments
    return output
```

## Operation Pattern

All operations follow the same pattern:

```python
def operation(lib: BibLibrary, args) -> int:
    # 1. Validate inputs
    # 2. Mutate lib in place using surgical field/key edits
    # 3. Return changed count or operation-specific result
    # CLI handles dry-run, diff, JSON, and writeback
```

This separation lets the CLI handle `--dry-run`, `--diff`, and `--json` consistently.

## CLI Workflow

```python
# Load
lib = load_bib(args.file)

# Snapshot raw entry text for minimal diffs
pre = _snapshot(lib)

# Run operation
result = operation(lib, args)

# Dry-run/write
if args.dry_run:
    changed, diff_text, modified = _commit(file, lib, pre, dry_run=True)
    exit(0)

changed, diff_text, modified = _commit(file, lib, pre, dry_run=False)
```

## Exit Codes

- **0** — Operation successful
- **1** — Error (parse, validation, I/O)
- **2** — Conflict (operation blocked; options returned)

Conflicts are reported in JSON with available options:

```json
{
  "status": "conflict",
  "error": "DuplicateDOI",
  "message": "DOI 10.5555/example already exists",
  "options": [
    {"id": "keep_existing", "description": "Do not import a duplicate reference"},
    {"id": "allow_duplicate", "description": "Retry with --allow-duplicate"}
  ]
}
```

## Testing Strategy

### Unit Tests
- Model instantiation and mutation
- Parser correctness (fixtures)
- Writer round-trip fidelity
- Operation correctness (in-memory)

### Integration Tests
- Full CLI workflows
- Dry-run vs committed execution
- JSON output parsing
- Backup creation

### Coverage Targets
- Core I/O: >95%
- Operations: >90%
- CLI: >80%
- Overall: >90%

## Future Extensions

### v0.2: Configuration Profiles
```python
# profiles.yaml
profiles:
  ieee:
    journal_style: abbreviated
    field_case: title_case
    required_fields: [author, title, journal, year, pages]
```

### v0.3: MCP Server
```python
# pynakes_mcp.py provides tools for Claude SDK
tools = [
  Tool("inspect_bibliography", inspect_bib),
  Tool("normalize_bibliography", normalize_library),
  Tool("repair_keys", repair_keys),
]
```

### v0.4: Advanced Queries
```python
# Query DSL for selective operations
pynakes fields append refs.bib keywords "AI" \
  --where 'type=article AND (title contains "learning" OR abstract contains "neural")'
```

## References

- [Model](../index.md) — Data structures
- [Usage Guide](usage.md) — CLI reference
- [Examples](../examples/index.md) — Practical workflows
