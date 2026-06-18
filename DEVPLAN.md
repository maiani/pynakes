# pynakes development plan

Breakdown of v0.1 implementation into phases with clear milestones and dependencies.

## Overview

**Goal**: Ship a stable v0.1 with core functionality, safe operations, and comprehensive tests.

**Target scope**: 12 working features covering library organization, metadata repair, format normalization, and agent-safe operation.

**Phases**: 4 sequential phases; each phase is a buildable, testable milestone.

---

## Phase 1: Foundation (Weeks 1-2)

**Goal**: Set up the project and establish core I/O with round-trip preservation.

### Tasks

#### 1.1 Project setup
- [ ] Initialize `pyproject.toml` with dependencies (`typer`, `rich`)
- [ ] Set up `src/pynakes/` layout
- [ ] Configure `pytest` and `ruff`
- [ ] Initialize `__init__.py`, `__main__.py`, `cli.py`
- [x] Write README (done)
- [x] Write ARCHITECTURE.md (done)
- [x] Write DEVPLAN.md (done)
- [x] Add LICENSE file (MIT)
- [ ] Add CHANGELOG.md with unreleased section

**Success criteria:**
- `pip install -e .` works
- `pynakes --help` runs and shows top-level commands
- `ruff check .` passes

#### 1.2 Data model (`model.py`)
- [ ] Define `BibEntry` dataclass
- [ ] Define `BibLibrary` dataclass
- [ ] Add `__repr__` for debugging
- [ ] Type hints throughout

**Fields:**

```python
@dataclass
class BibEntry:
    key: str
    type: str
    fields: dict[str, str]
    raw_content: Optional[str] = None
    raw_comments: list[str] = field(default_factory=list)
    jabref_metadata: dict[str, str] = field(default_factory=dict)
    modified: bool = False

@dataclass
class BibLibrary:
    entries: dict[str, BibEntry]
    strings: dict[str, str]
    preamble: list[str]
    raw_comments: list[str]
    encoding: str = "utf-8"
    line_ending: str = "\n"
```

**Success criteria:**
- All fields present and type-hinted
- Can instantiate and modify
- Round-trip to JSON works

#### 1.3 Parser (`bibtex_parser.py`)
- [ ] Implement `parse_bib(text: str) -> BibLibrary`
- [ ] Parse entry headers (`@type{key,`)
- [ ] Extract fields (key = value pairs)
- [ ] Preserve raw_content for each entry
- [ ] Detect JabRef metadata from `@comment` lines
- [ ] Detect encoding (UTF-8, with fallback)
- [ ] Detect line ending (`\n` vs `\r\n`)
- [ ] Handle @string and @preamble
- [ ] Raise `ParseError` with line numbers on failure

**Success criteria:**
- Parses all fixture files without error
- Preserves unknown fields
- Extracts JabRef metadata correctly
- Round-trip parse → inspect matches original structure

#### 1.4 Writer (`bibtex_writer.py`)
- [ ] Implement `write_bib(lib: BibLibrary) -> str`
- [ ] Write entries: use raw_content for unmodified, reconstruct for modified
- [ ] Write comments, preambles, strings
- [ ] Respect line_ending setting
- [ ] Proper field value escaping

**Success criteria:**
- Unmodified entries write back identically (zero diff)
- Modified entries are reconstructed with proper formatting
- Respects encoding and line endings

#### 1.5 I/O orchestration (`io.py`)
- [ ] Implement `load_bib(path: str) -> BibLibrary`
- [ ] Implement `save_bib(lib: BibLibrary, path: str, backup=True, atomic=True) -> SaveResult`
- [ ] Detect encoding on read
- [ ] Atomic write: temp file → validate → rename
- [ ] Backup creation (`.bak` file)
- [ ] Error handling with context (file, line, reason)

**Success criteria:**
- Files load and save atomically
- Backups are created automatically
- Round-trip `load → save` preserves content
- Errors reported with file:line context

#### 1.6 Test fixtures and basic tests
- [ ] Create fixtures: `simple.bib`, `jabref_groups.bib`, `biblatex_sample.bib`, `duplicate_entries.bib`, `linked_files.bib`
- [ ] Write `test_model.py` (instantiation, field access)
- [ ] Write `test_bibtex_parser.py` (parsing, JabRef metadata, encoding detection)
- [ ] Write `test_bibtex_writer.py` (round-trip, formatting preservation)
- [ ] Write `test_io.py` (load, save, atomic write, backup)

**Success criteria:**
- `pytest` runs all tests and passes
- Coverage >95% for core I/O modules
- Round-trip tests pass for all fixtures

### Phase 1 completion check

```bash
pytest tests/test_model.py tests/test_bibtex_parser.py tests/test_bibtex_writer.py tests/test_io.py
ruff check src/pynakes/model.py src/pynakes/bibtex_parser.py src/pynakes/bibtex_writer.py src/pynakes/io.py
pynakes inspect tests/fixtures/simple.bib
```

**Go/No-go**: All tests pass, `ruff` clean, `inspect` command works.

---

## Phase 2: Core operations (Weeks 2-3)

**Goal**: Implement group management, key handling, and field operations.

**Dependency**: Phase 1 complete.

### Tasks

#### 2.1 Group management (`groups.py`)
- [ ] Implement `list_groups(lib: BibLibrary) -> list[str]`
- [ ] Implement `add_to_group(lib: BibLibrary, key: str, group: str) -> BibLibrary`
- [ ] Implement `remove_from_group(lib: BibLibrary, key: str, group: str) -> BibLibrary`
- [ ] Implement `list_entries_in_group(lib: BibLibrary, group: str) -> list[str]`
- [ ] Parse `groups` field (semicolon-delimited)
- [ ] Preserve JabRef group metadata comments

**Success criteria:**
- Can list, add, remove groups
- Groups field is correctly parsed and modified
- JabRef metadata is preserved
- No data loss on round-trip

#### 2.2 Citation keys (`keys.py`)
- [ ] Implement `detect_duplicate_keys(lib: BibLibrary) -> list[tuple[str, str]]`
- [ ] Implement `generate_key(entry: BibEntry) -> str` (AuthorYearTitle pattern)
- [ ] Implement `has_duplicate_keys(lib: BibLibrary) -> bool`
- [ ] Implement `repair_duplicate_keys(lib: BibLibrary) -> (BibLibrary, list[str])` (rename strategy)

**Generation pattern**: `[First author last name][4-digit year][first significant title word]`

Example: `Smith2020BigData`

**Success criteria:**
- Duplicate detection works
- Key generation is deterministic and readable
- Repair appends a suffix (e.g., `Smith2020_2`)
- Tests pass with various author/year/title formats

#### 2.3 Field operations (`fields.py`)
- [ ] Implement `rename_field(lib: BibLibrary, old: str, new: str, where: QueryFilter = None) -> BibLibrary`
- [ ] Implement `move_field(lib: BibLibrary, old: str, new: str, where: QueryFilter = None) -> BibLibrary`
- [ ] Implement `append_field(lib: BibLibrary, field: str, value: str, where: QueryFilter = None) -> BibLibrary`
- [ ] Implement `clear_field(lib: BibLibrary, field: str, where: QueryFilter = None) -> BibLibrary`
- [ ] Support simple query filters (`QueryFilter` = `Optional[Callable[[BibEntry], bool]]`)

**Success criteria:**
- Field operations work on single and multiple entries
- Query filters allow selective operations
- No data corruption on field edits
- Test with various field names and values

#### 2.4 Linting (`lint.py`)
- [ ] Implement `lint(lib: BibLibrary) -> list[Lint Issue]`
- [ ] Check for duplicate keys
- [ ] Check for missing required fields (article, book, inproceedings, thesis)
- [ ] Check for malformed DOI (basic regex)
- [ ] Check for missing DOI (warning, not error)
- [ ] Check for broken groups field formatting

**Required fields by type:**
- `article`: author, title, journal, year
- `book`: author/editor, title, publisher, year
- `inproceedings`: author, title, booktitle, year
- `thesis` (phdthesis, mastersthesis): author, title, school, year

**Success criteria:**
- Lint identifies all issue types
- No false positives
- Issues include entry key and detailed reason
- Tests pass with various entry types

#### 2.5 CLI commands (Phase 2 additions to `cli.py`)
- [ ] Add `pynakes inspect <file>`
- [ ] Add `pynakes groups list <file>`
- [ ] Add `pynakes groups add-entry <file> <key> <group> [--dry-run]`
- [ ] Add `pynakes groups remove-entry <file> <key> <group> [--dry-run]`
- [ ] Add `pynakes keys check <file>`
- [ ] Add `pynakes keys generate <file> [--dry-run]`
- [ ] Add `pynakes keys repair <file> [--dry-run]`
- [ ] Add `pynakes fields rename <file> <old> <new> [--dry-run]`
- [ ] Add `pynakes fields append <file> <field> <value> [--where <query>] [--dry-run]`
- [ ] Add `pynakes lint <file>`

**Features:**
- `--dry-run` flag shows changes without modifying file
- `--diff` flag shows unified diff
- `--json` flag returns JSON output
- Clear error messages with context

**Success criteria:**
- All commands work end-to-end
- `--help` is accurate
- Dry-run commands modify nothing
- Errors are clear and actionable

#### 2.6 Diff and output (`diff.py`)
- [ ] Implement `unified_diff(original: str, modified: str) -> str`
- [ ] Implement `json_output(status: str, action: str, file: str, modified: bool, details: dict) -> dict`
- [ ] Use standard Python `difflib` for diffs

**Success criteria:**
- Diffs are readable and match expectations
- JSON output is valid and complete
- Both human and JSON formats work

#### 2.7 Tests for Phase 2
- [ ] `test_groups.py`: list, add, remove, JabRef compatibility
- [ ] `test_keys.py`: generation, duplicate detection, repair
- [ ] `test_fields.py`: rename, move, append, clear with queries
- [ ] `test_lint.py`: all lint issue types, no false positives
- [ ] `test_cli.py`: smoke tests for all Phase 2 commands

**Success criteria:**
- All tests pass
- Coverage >90% for operation modules
- All fixtures pass linting

### Phase 2 completion check

```bash
pytest tests/test_groups.py tests/test_keys.py tests/test_fields.py tests/test_lint.py tests/test_cli.py
pynakes groups list tests/fixtures/jabref_groups.bib
pynakes lint tests/fixtures/simple.bib --json
pynakes keys repair tests/fixtures/duplicate_entries.bib --dry-run --diff
```

**Go/No-go**: All commands work, tests pass, diffs are readable.

---

## Phase 3: Format normalization and advanced output (Weeks 3-4)

**Goal**: Implement BibTeX ↔ BibLaTeX conversion, journal abbreviation, and structured output.

**Dependency**: Phase 2 complete.

### Tasks

#### 3.1 BibTeX to BibLaTeX conversion (`convert.py`)
- [ ] Implement `convert_to_biblatex(lib: BibLibrary) -> BibLibrary`
- [ ] Field mappings:
  - `journal` → `journaltitle`
  - `address` → `location`
  - `school` → `institution`
  - `year` + `month` → `date` (if `date` absent)
- [ ] Entry type mappings:
  - `@phdthesis` → `@thesis` with `type = {phdthesis}`
  - `@mastersthesis` → `@thesis` with `type = {mathesis}`
- [ ] Preserve unknown fields
- [ ] Preserve groups and comments

**Success criteria:**
- Conversions are correct and complete
- Unknown fields are untouched
- No data loss on conversion
- Round-trip parse → convert → write works

#### 3.2 Journal abbreviation (`journals.py`)
- [ ] Implement `abbreviate_journals(lib: BibLibrary) -> BibLibrary`
- [ ] Implement `expand_journals(lib: BibLibrary) -> BibLibrary`
- [ ] Built-in abbreviation table (small, common journals):
  - `Physical Review B` ↔ `Phys. Rev. B`
  - `Physical Review Letters` ↔ `Phys. Rev. Lett.`
  - `Journal of Money, Credit and Banking` ↔ `J. Money Credit Bank.`
  - `American Economic Review` ↔ `Am. Econ. Rev.`
  - (Add ~10-15 more common economics/physics journals)
- [ ] Work on both `journal` and `journaltitle` fields
- [ ] Detect inconsistent journal naming (warn if no match found)

**Success criteria:**
- Abbreviations are correct
- Expansions reverse abbreviations
- Warnings for unknown journals
- Tests cover common journals

#### 3.3 Capabilities metadata (`capabilities.py`)
- [ ] Implement `get_capabilities() -> dict`
- [ ] Return structure:
  ```json
  {
    "tool": "pynakes",
    "version": "0.1",
    "safe_by_default": true,
    "supports_dry_run": true,
    "supports_json_output": true,
    "exit_codes": {...},
    "capabilities": [...],
    "commands": {...}
  }
  ```

**Success criteria:**
- Output is accurate and complete
- Matches declared features in Phase 1-3
- Can be parsed by agents

#### 3.4 Safe diff and JSON for all operations
- [ ] Update all Phase 2 operations to support `--dry-run`, `--diff`, `--json`
- [ ] Ensure JSON output is consistent across all commands
- [ ] Test with all operation types

**Success criteria:**
- All commands respect `--dry-run`, `--diff`, `--json`
- No side effects during dry-run
- JSON is valid and parseable

#### 3.5 CLI commands (Phase 3 additions)
- [ ] Add `pynakes capabilities --json`
- [ ] Add `pynakes convert <file> --to biblatex [--dry-run] [--diff]`
- [ ] Add `pynakes journals abbreviate <file> [--dry-run]`
- [ ] Add `pynakes journals expand <file> [--dry-run]`
- [ ] Add `pynakes journals check <file>`
- [ ] Update all Phase 2 commands to support `--json`

**Success criteria:**
- All commands work
- JSON output is consistent
- Help text is clear

#### 3.6 Tests for Phase 3
- [ ] `test_convert.py`: BibTeX to BibLaTeX mappings, field preservation
- [ ] `test_journals.py`: abbreviation, expansion, detection of inconsistent names
- [ ] `test_capabilities.py`: structure and accuracy of capabilities output
- [ ] Integration tests: dry-run + diff + JSON for all Phase 2-3 operations

**Success criteria:**
- All tests pass
- Coverage >85% for format operations
- End-to-end tests exercise all code paths

### Phase 3 completion check

```bash
pytest tests/test_convert.py tests/test_journals.py tests/test_capabilities.py
pynakes convert tests/fixtures/biblatex_sample.bib --to biblatex --dry-run --diff
pynakes journals abbreviate tests/fixtures/simple.bib --dry-run --json
pynakes capabilities --json | python -m json.tool
```

**Go/No-go**: Conversion and journal operations work, JSON output is valid.

---

## Phase 4: Polish and testing (Week 4)

**Goal**: Comprehensive testing, documentation, and release readiness.

**Dependency**: Phase 3 complete.

### Tasks

#### 4.1 Comprehensive testing
- [ ] Add property-based tests (hypothesis) for parser robustness
- [ ] Add stress tests (large files, many entries)
- [ ] Add error recovery tests (malformed input, permission errors)
- [ ] Add end-to-end workflow tests (multi-operation sequences)
- [ ] Ensure coverage >90% across all modules

**Success criteria:**
- `pytest --cov` shows >90% coverage
- All edge cases tested
- No unexpected failures on fuzzing

#### 4.2 Error handling improvements
- [ ] Ensure all error messages are clear and actionable
- [ ] Add file:line context to all parse errors
- [ ] Add suggestions for common issues
- [ ] Test error paths thoroughly

**Success criteria:**
- Error messages are helpful
- Exit codes are correct (0 = success, 1 = error, 2 = conflict)
- User can fix issues based on error message

#### 4.3 Documentation
- [ ] Ensure README is accurate and complete
- [ ] Ensure ARCHITECTURE.md covers all design decisions
- [ ] Ensure AGENTS.md has clear examples
- [ ] Add docstrings to all public functions
- [ ] Add type hints throughout

**Success criteria:**
- README examples all work
- ARCHITECTURE can be followed by new contributors
- AGENTS.md examples are accurate
- All public functions have docstrings

#### 4.4 Code quality
- [ ] Run `ruff check .` and fix all issues
- [ ] Run `ruff format .` for consistent formatting
- [ ] Remove any debug code or TODOs
- [ ] Review code for clarity and simplicity

**Success criteria:**
- `ruff check .` passes with no errors
- `ruff format .` makes no changes
- Code is readable and maintainable

#### 4.5 Final integration tests
- [ ] Test all CLI commands with real files
- [ ] Test all fixture files work end-to-end
- [ ] Test dry-run vs actual execution matches
- [ ] Test error handling with malformed input

**Success criteria:**
- All CLI commands work
- Dry-run output matches actual execution
- Errors are handled gracefully

#### 4.6 Release checklist
- [ ] Update `pyproject.toml` with version 0.1.0
- [ ] Update README with "Current status" section
- [ ] Update CHANGELOG.md with v0.1.0 release notes
- [ ] Verify `pip install -e .` works from scratch
- [ ] Verify all tests pass
- [ ] Verify `ruff check .` and `ruff format .` pass

**Success criteria:**
- Package installs cleanly
- Tests pass on fresh install
- Code quality checks pass
- Documentation is complete

### Phase 4 completion check

```bash
pip install -e . --force-reinstall
pytest --cov=src/pynakes tests/
ruff check src/ tests/
ruff format --check src/ tests/
pynakes --help
pynakes capabilities --json
pynakes inspect tests/fixtures/simple.bib
```

**Go/No-go**: All checks pass, coverage >90%, release ready.

---

## Milestones and schedule

| Phase | Milestone | Duration | Go/No-go date |
|-------|-----------|----------|---------------|
| 1 | Foundation (I/O, model, parser) | 2 weeks | Day 14 |
| 2 | Core operations (groups, keys, fields, lint) | 1 week | Day 21 |
| 3 | Format normalization (convert, journals, capabilities) | 1 week | Day 28 |
| 4 | Testing, docs, release | 1 week | Day 35 |

**Total**: ~1 month (4 weeks) to v0.1.0.

---

## Testing coverage targets

| Module | Target | Phase |
|--------|--------|-------|
| model.py | 95% | 1 |
| bibtex_parser.py | 95% | 1 |
| bibtex_writer.py | 95% | 1 |
| io.py | 95% | 1 |
| groups.py | 90% | 2 |
| keys.py | 90% | 2 |
| fields.py | 90% | 2 |
| lint.py | 90% | 2 |
| convert.py | 85% | 3 |
| journals.py | 85% | 3 |
| cli.py | 80% | 2-4 |
| **Overall** | **>90%** | 4 |

---

## Known risks and mitigations

### Risk: Parser edge cases
**Mitigation**: Property-based testing (hypothesis) on parser in Phase 4. Start with conservative parser that rejects malformed input rather than guessing.

### Risk: Round-trip fidelity
**Mitigation**: Extensive round-trip tests in Phase 1. Store `raw_content` for unmodified entries to guarantee zero-diff on write-back.

### Risk: BibTeX format variations
**Mitigation**: Test with diverse fixtures (JabRef, hand-written, generated). Preserve unknown fields aggressively.

### Risk: CLI UX
**Mitigation**: Early smoke tests (Phase 2). Ask for feedback on command names and output format before Phase 3.

### Risk: Over-scope
**Mitigation**: Phase gates. Do not merge features not in the current phase. Defer v0.2 features (config, profiles, advanced search).

---

## Success criteria for v0.1

✅ All 12 core features implemented and tested  
✅ >90% test coverage  
✅ `ruff check` and `ruff format` pass  
✅ README and ARCHITECTURE complete  
✅ All CLI commands work and have help text  
✅ Dry-run, diff, and JSON output on all modifying commands  
✅ Atomic writes with backup  
✅ Clear error handling with exit codes  
✅ No breaking changes planned for v0.2  

---

## Next steps after v0.1

### v0.1.1 (quick wins, ~1 week)
- DOI import integration
- Deduplication and merge
- ~~AUX extraction~~ — **done early** as `pynakes used` (cite detection across
  `.tex`/`.aux`, subset export, group/keyword tagging). See CHANGELOG.

### v0.2 (feature expansion, ~2 weeks)
- Configuration profiles
- User-provided journal tables
- Title capitalization protection
- Linked-file validation

### v0.3+ (long-term)
- MCP server (`pynakes-mcp`)
- Advanced query DSL
- Batch operations from files
- Cross-library linking
