# pynakes architecture

This document describes the internal design of pynakes, intended for contributors and maintainers.

## Design philosophy

**pynakes is a data-preservation tool, not a parser tool.**

The BibTeX format is messy and forgiving; `.bib` files are typically small (<10MB). The value of pynakes is not parsing speed but semantic fidelity: making explicit, reviewable, safe edits while preserving everything the user has written (comments, unknown fields, formatting, JabRef metadata).

This shapes every architectural choice:

- **Round-trip fidelity first**: A parse→edit→write cycle should be invisible to the user (no fields reordered, no comments lost, no reformatting).
- **Explicit over implicit**: Operations are small and atomic. No "rewrite this entire file" functions.
- **Preserve data by default**: Unknown fields, custom fields, comments, and raw formatting are kept, not discarded.
- **Fail safely**: Better to refuse an operation and report a conflict than to silently discard data or guess.

## Core data structures

All operation modules work with these types:

### BibEntry

```python
@dataclass
class BibEntry:
    key: str                          # citation key (e.g. "Smith2020")
    type: str                         # entry type (e.g. "article", "book")
    fields: dict[str, str]            # all fields (standard and custom)
    raw_comments: list[str]           # preserve @comment lines verbatim
    jabref_metadata: dict[str, str]   # extracted key=value from comments
```

**Design notes:**

- No distinction between "standard" and "custom" fields in the `fields` dict. This allows round-trip preservation: if we don't understand a field, we keep it as-is.
- `raw_comments` preserves the original text of JabRef metadata comments so they can be written back exactly.
- `jabref_metadata` is a convenience dict extracted from `raw_comments` for programmatic access (e.g., `jabref_metadata["groups"]`).

### BibLibrary

```python
@dataclass
class BibLibrary:
    entries: dict[str, BibEntry]      # keyed by citation key
    strings: dict[str, str]           # @string constants
    preamble: list[str]               # @preamble blocks
    raw_comments: list[str]           # file-level comments
    encoding: str                     # detected or specified (default: utf-8)
    line_ending: str                  # \n or \r\n, preserved on write
```

**Design notes:**

- `entries` is a dict for O(1) lookup by key; order is preserved in Python 3.7+.
- `raw_comments` at the library level preserve any comments that appear between entries or at the top of the file.
- `encoding` and `line_ending` are explicitly tracked so they can be reproduced on write.

## Layer architecture

### Layer 1: Custom parser (`bibtex_parser.py`)

pynakes implements a minimal custom BibTeX parser. This is intentional:

**Why not use an external library?**

- Round-trip fidelity is critical. External libraries often normalize or lose formatting.
- BibTeX is small and forgiving; the parsing logic is straightforward.
- Custom parser gives full control over preservation guarantees.
- No dependencies means fewer maintenance headaches and API breakages.

**Parser design:**

```python
# bibtex_parser.py

def parse_bib(text: str) -> BibLibrary:
    """Parse BibTeX text, preserving all formatting and comments."""
    entries = {}
    strings = {}
    preambles = []
    comments = []
    
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # @string
        if stripped.lower().startswith('@string'):
            key, value = _extract_string(line)
            strings[key] = value
            i += 1
        
        # @preamble
        elif stripped.lower().startswith('@preamble'):
            preambles.append(line)
            i += 1
        
        # @comment
        elif stripped.lower().startswith('@comment'):
            comments.append(line)
            i += 1
        
        # Entry (@article, @book, etc.)
        elif stripped.startswith('@'):
            raw_lines = [line]
            i += 1
            brace_depth = line.count('{') - line.count('}')
            
            # Collect lines until entry closes
            while i < len(lines) and brace_depth > 0:
                raw_lines.append(lines[i])
                brace_depth += lines[i].count('{') - lines[i].count('}')
                i += 1
            
            # Parse entry
            raw_text = '\n'.join(raw_lines)
            entry_type, key = _extract_entry_header(raw_text)
            fields = _extract_fields(raw_text)
            
            entries[key] = BibEntry(
                key=key,
                type=entry_type,
                fields=fields,
                raw_content=raw_text  # preserve for round-trip
            )
        else:
            i += 1
    
    return BibLibrary(
        entries=entries,
        strings=strings,
        preamble=preambles,
        raw_comments=comments,
        encoding=detect_encoding(text),
        line_ending=detect_line_ending(text)
    )
```

**Key properties:**

- No normalization. Unknown fields are preserved as-is.
- Comments and blank lines are kept.
- Each entry stores `raw_content` so unmodified entries write back identically.
- Field values are stored as strings; no attempt to "parse" them further.
- Parse errors are reported with line numbers and context.

**Writer strategy:**

```python
# bibtex_writer.py

def write_bib(lib: BibLibrary) -> str:
    """Serialize BibLibrary back to BibTeX, minimizing diffs."""
    output = []
    
    # Write comments and preambles
    for comment in lib.raw_comments:
        output.append(comment)
    
    for preamble in lib.preamble:
        output.append(preamble)
    
    # Write strings
    for key, value in lib.strings.items():
        output.append(f'@string{{{key} = {value}}}')
    
    # Write entries
    for key, entry in lib.entries.items():
        if entry.raw_content and not entry.modified:
            # Unmodified entry: write back raw content
            output.append(entry.raw_content)
        else:
            # Modified entry: reconstruct from fields
            output.append(_serialize_entry(entry))
    
    text = '\n'.join(output)
    
    # Restore original line ending
    if lib.line_ending == '\r\n':
        text = text.replace('\n', '\r\n')
    
    return text
```

**Future extensibility:**

If parsing becomes a bottleneck or you need advanced features:

1. Define a `ParserBackend` protocol.
2. Move custom parser behind it.
3. Allow swapping in a different backend (bibtexparser v3, or a faster parser).
4. The rest of pynakes doesn't change.

### Layer 2: Core I/O (`bibtex_parser.py`, `bibtex_writer.py`, `io.py`)

**`bibtex_parser.py`**: Custom BibTeX parser.

- Line-by-line parsing with entry detection via regex.
- Extracts entry type, key, and fields.
- Preserves `raw_content` for each entry (for round-trip fidelity).
- Detects JabRef metadata from comments.
- Handles encoding and line-ending detection.
- Reports parse errors with line numbers and context.

**`bibtex_writer.py`**: Serialization back to BibTeX.

- For unmodified entries: writes back `raw_content` exactly (zero diff).
- For modified entries: reconstructs BibTeX from `fields` dict.
- Preserves `raw_comments`, preambles, and `@string` constants.
- Respects `line_ending` setting (normalizes `\n` / `\r\n`).
- Proper escaping and quoting of field values.

**`io.py`**: Orchestration layer.

```python
def load_bib(path: str) -> BibLibrary:
    """Load a .bib file, returning a BibLibrary."""
    text = read_file(path, encoding='utf-8-sig')  # detect encoding
    lib = bibtex_parser.parse_bib(text)
    return lib
    
def save_bib(lib: BibLibrary, path: str, *, 
             backup: bool = True, 
             atomic: bool = True) -> SaveResult:
    """Save a BibLibrary to file with optional backup and atomic write."""
    # Serialize to text
    text = bibtex_writer.write_bib(lib)
    
    # Validate by re-parsing
    _validate_by_reparsing(text)
    
    # Atomic write: temp → backup + atomic rename
    temp_path = path + '.tmp'
    write_file(temp_path, text, encoding='utf-8')
    
    if backup and path.exists():
        backup_path = path + '.bak'
        path.rename(backup_path)
    
    temp_path.rename(path)  # atomic on POSIX/Windows
    return SaveResult(success=True, backup=backup_path)
```

- Handles file I/O, encoding detection, backup creation.
- Atomic write: write to temp file, validate, then rename.
- Backup: creates `.bak` file before overwriting.
- Error handling: reports I/O errors with context.
- No external parser dependencies.

### Layer 3: Operation modules

Each operation module is small, focused, and testable.

**Implemented:**

- **`editing.py`**: Surgical raw-text field/key edits (single source of truth for
  minimal-diff modifications) plus entry-level helpers.
- **`groups.py`**: Parse and modify the `groups` field, add/remove entries.
- **`keys.py`**: Detect duplicate keys, generate new ones (`AuthorYearTitle` or a
  JabRef citation-key pattern), repair conflicts.
- **`fields.py`**: Rename, move, append, clear fields and protect title
  capitalization, with an optional `--where` query filter.
- **`authors.py`**: Author/editor name-list parsing and normalization (owns
  name splitting and last-name extraction used by key generation).
- **`journals.py`**: Abbreviate/expand journal names (user table, bundled exact
  table, LTWA word generation).
- **`doi.py`**: DOI normalization/validation and metadata import via DOI content
  negotiation (stdlib `urllib`).
- **`normalize.py`**: High-level routine composing title/author/journal/DOI
  normalization.
- **`lint.py`**: Validate entries (duplicate keys, required fields, malformed/
  missing DOI, malformed groups).
- **`usage.py`**: Detect/tag/export entries cited in LaTeX `.tex`/`.aux` sources.
- **`capabilities.py`**: Machine-readable description of supported operations.

**Planned (not yet built):** `dedupe.py` (merge), `convert.py` (BibTeX ↔
BibLaTeX), `search.py` (query DSL), `files.py` (linked-file validation),
`strings.py` (`@string` management).

**Each operation module should:**

- Accept `BibLibrary` as input.
- Mutate the library in place and return a count (or report) of what changed;
  edits go through `editing.py` so unmodified entries stay byte-identical.
- Raise `ConflictError` (or surface options) if the operation cannot safely
  complete.
- Provide a `.dry_run()` variant that returns a diff without modifying.
- Include its own unit tests.

Example:

```python
def rename_field(lib: BibLibrary, 
                old_name: str, 
                new_name: str,
                where: Optional[QueryFilter] = None) -> (BibLibrary, list[str]):
    """Rename a field, optionally filtering by query.
    
    Returns:
        (modified_library, list_of_affected_keys)
    
    Raises:
        ValidationError: if new_name conflicts with existing field.
    """
```

### Layer 4: CLI (`cli.py`)

The CLI is a thin wrapper over operation modules:

```bash
pynakes groups add-entry refs.bib KEY "Group Name" [--dry-run] [--diff] [--json]
pynakes fields rename refs.bib old_field new_field [--where QUERY] [--dry-run] [--diff]
pynakes lint refs.bib [--json] [--strict]
```

- Maps commands to operation functions.
- Handles `--dry-run`, `--diff`, `--json`, `--backup` flags.
- Formats output (human-readable text or JSON).
- Reports errors clearly with exit codes.
- All file I/O goes through `io.py`.

## Error handling

### Exception hierarchy

```python
class PynakesError(Exception):
    """Base exception for all pynakes errors."""

class ParseError(PynakesError):
    """Unrecoverable parse error in a .bib file."""
    file: str
    line: int
    reason: str

class ValidationError(PynakesError):
    """Semantic error detected (missing field, malformed value)."""
    entry_key: Optional[str]
    field: Optional[str]
    reason: str
    severity: Literal["warning", "error"]  # warnings are reported but non-fatal

class ConflictError(PynakesError):
    """Operation cannot safely complete; user input required."""
    reason: str
    options: list[dict]  # list of proposed resolutions

class OperationNotSupported(PynakesError):
    """Feature is scaffolded but not yet implemented."""
    operation: str
```

### Error handling rules

1. **Parse errors** are fatal. Report to stderr with file:line context and exit code 1.
2. **Validation warnings** are reported but do not block the operation. Use `--strict` flag to make warnings fatal.
3. **Conflicts** are reported with exit code 2 and a JSON output explaining the options. The user can then re-run with a disambiguating flag or decide to abort.
4. **Dry-run validation**: A dry-run validates the operation fully but does not write. It can succeed while the actual write fails (e.g., file permissions).
5. **Atomic write failures**: If the write fails after validation, roll back by restoring the backup and report the error atomically.

## Testing strategy

### Test fixtures

Fixtures are committed to the repo under `tests/fixtures/`:

- `simple.bib`: minimal BibTeX with 2–3 entries.
- `jabref_groups.bib`: entries with JabRef group metadata.
- `biblatex_sample.bib`: BibLaTeX-formatted entries.
- `duplicate_entries.bib`: entries that match on DOI, arXiv, or title+author+year.
- `linked_files.bib`: entries with linked file references.
- `with_custom_fields.bib`: entries with user-defined fields.
- `with_comments.bib`: file-level and entry-level comments.

### Test organization

- `test_parser.py`: Backend abstraction and parsing logic.
- `test_model.py`: Data structure behavior.
- `test_io.py`: File load/save, encoding, round-trip preservation.
- `test_groups.py`: Group parsing and modification.
- `test_keys.py`: Key generation and duplicate detection.
- `test_fields.py`: Field operations.
- `test_lint.py`: Validation logic.
- `test_dedupe.py`: Duplicate detection and merge logic.
- `test_convert.py`: BibTeX ↔ BibLaTeX conversion.
- `test_search.py`: Query DSL and filtering.
- `test_cli.py`: CLI integration tests (fixtures, not actual files).

### Coverage targets

- Core I/O (parser, writer, io): 100% (data preservation is critical).
- Operation modules: 95%+ (each operation tested with fixtures).
- CLI: 80%+ (integration tests for main command paths).

### Testing practices

- No network access in tests. DOI fetches are stubbed or mocked.
- Fixtures are small, stable, and version-controlled.
- Each test is independent and can run in isolation.
- Round-trip tests (parse → modify → write → parse) verify that formatting is preserved.

## Configuration (future)

Configuration is not required for v0.1 but the architecture should support it:

**Config file location**: `~/.pynakesrc` (TOML)

**Environment override**: `PYNAKES_CONFIG` env var

**Planned sections** (v0.2+):

```toml
[defaults]
dry_run = false           # default to --dry-run for all commands
backup = true             # create .bak files
output_format = "text"    # or "json"

[profiles]
default = "preserve_all"  # cleanup profile to apply on save
econ = "econ_conventions" # domain-specific profile

[journals]
# Custom journal abbreviation table
abbreviations = "~/.pynakes_journals.toml"

[special_fields]
# Define how to handle special metadata (read status, etc.)
```

## Dependency management

### Direct dependencies (v0.1)

- `typer`: CLI framework (lightweight, well-maintained).
- No parsing library (custom BibTeX parser included).

### Optional dependencies

- `rich`: human-readable CLI output (colors, tables).

DOI metadata import in `doi.py` uses the Python standard library (`urllib`); no
third-party HTTP client is required.

### Why minimal dependencies?

- Reduces maintenance burden and security surface.
- Easier to install and redistribute.
- Clearer ownership of behavior (we control what happens).

## Future architecture points

### ParserBackend abstraction (if needed)

Today, the custom parser is directly embedded. If parsing becomes a bottleneck or you want to experiment with different parser implementations:

1. Define a `ParserBackend` protocol with methods like `parse_string()`, `write_entries()`.
2. Move custom parser behind the interface.
3. Write adapters for alternative parsers (bibtexparser v3, or a faster implementation).
4. The rest of pynakes is unaffected.

This is a *future* optimization, not a requirement for v0.1. Premature abstraction adds complexity without benefit.

### MCP server (`pynakes-mcp`)

A future MCP (Model Context Protocol) server will expose pynakes operations as tools for Claude and other agents:

```json
{
  "tool": "pynakes.groups.add_entry",
  "description": "Add an entry to a group in a BibTeX library.",
  "parameters": {
    "file": "path to .bib file",
    "entry_key": "citation key",
    "group": "group name",
    "dry_run": "boolean"
  }
}
```

The MCP server will:

- Use the same operation modules as the CLI.
- Default to `--dry-run` for safety (Claude must explicitly request write).
- Return structured JSON for all operations.
- Support streaming for large diffs.

### Streaming and large files

Today's design assumes files fit in memory. If very large files become common:

1. Implement streaming parser for read-only operations (lint, search).
2. Keep in-memory model for write operations (files are usually small).
3. Add a `stream=True` flag to lazy-load entries on demand.

### Advanced query DSL

Currently, queries are simple string filters. A future query language could support:

```
author contains "Smith" AND year >= 2020 AND groups contains "CBDC"
doi missing OR doi malformed
read status != "read"
```

Implementation: a small query parser in `search.py` that builds filter functions.

## Code style and conventions

- Type hints throughout (PEP 484).
- Dataclasses for simple data structures; use them for purity.
- Avoid mutation: operations return new objects, not modified in place.
- Prefer explicit over implicit: no magic, no decorators with side effects.
- Short functions, focused modules.
- Comments only for the "why", not the "what" (code should be self-documenting).
- Tests as documentation: a test shows how to use a function.
