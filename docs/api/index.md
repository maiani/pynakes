# API Reference

Python API for programmatic usage of pynakes.

> **Status — v0.1 in development.** The core library (`model`, `bibtex_parser`,
> `bibtex_writer`, `io`, `diff`) is implemented; operation modules (groups,
> keys, fields, lint, convert, journals) are planned. Note `BibLibrary.entries`
> is an `EntryCollection` (duplicate-key tolerant), not a plain dict — see
> `ARCHITECTURE.md`.

## Core Data Models

### BibEntry

Represents a single BibTeX entry.

```python
from pynakes.model import BibEntry

entry = BibEntry(
    key="Smith2020",
    type="article",
    fields={
        "author": "John Smith",
        "title": "A Great Paper",
        "journal": "Nature",
        "year": "2020"
    }
)

# Access fields
print(entry.key)        # "Smith2020"
print(entry.type)       # "article"
print(entry.fields["author"])  # "John Smith"

# Modify
entry.fields["doi"] = "10.1234/example"
entry.modified = True
```

### BibLibrary

Represents a complete BibTeX library.

```python
from pynakes.model import BibLibrary

lib = BibLibrary(
    entries={"Smith2020": entry},
    strings={"IEEE": "IEEE Transactions"},
    encoding="utf-8"
)

# Access
print(len(lib.entries))  # 1
print(lib.strings["IEEE"])  # "IEEE Transactions"
```

## I/O Functions

### load_bib

Load a BibTeX file.

```python
from pynakes.io import load_bib

lib = load_bib("refs.bib")
print(f"Loaded {len(lib.entries)} entries")
```

### save_bib

Save a library to a file.

```python
from pynakes.io import save_bib

save_bib(lib, "output.bib", backup=True, atomic=True)
# Creates output.bib with automatic .bak backup
```

## Parser

### parse_bib

Parse BibTeX text.

```python
from pynakes.bibtex_parser import parse_bib

text = """
@article{Smith2020,
  author = {John Smith},
  title = {A Great Paper},
  journal = {Nature},
  year = {2020}
}
"""

lib = parse_bib(text)
```

## Writer

### write_bib

Serialize library to BibTeX text.

```python
from pynakes.bibtex_writer import write_bib

text = write_bib(lib)
print(text)
```

## Operations (Phase 2+)

### groups

Manage entry groups.

```python
from pynakes.groups import (
    list_groups,
    add_to_group,
    remove_from_group,
)

# List groups
groups = list_groups(lib)

# Add entry to group
lib = add_to_group(lib, "Smith2020", "AI-Papers")

# Remove from group
lib = remove_from_group(lib, "Smith2020", "AI-Papers")
```

### keys

Manage citation keys.

```python
from pynakes.keys import (
    generate_key,
    detect_duplicate_keys,
    repair_duplicate_keys,
)

# Generate a key for an entry
entry = lib.entries["Smith2020"]
key = generate_key(entry)  # "Smith2020BigData"

# Find duplicates
duplicates = detect_duplicate_keys(lib)

# Repair
lib, renamed = repair_duplicate_keys(lib)
```

### fields

Edit fields.

```python
from pynakes.fields import (
    rename_field,
    append_field,
    clear_field,
)

# Rename a field
lib = rename_field(lib, "journal", "journaltitle")

# Append to a field
lib = append_field(lib, "keywords", "AI")

# Clear a field
lib = clear_field(lib, "abstract")
```

### lint

Validate entries.

```python
from pynakes.lint import lint

issues = lint(lib)
for issue in issues:
    print(f"{issue.type}: {issue.message}")
```

### convert

Format conversion.

```python
from pynakes.convert import convert_to_biblatex

lib = convert_to_biblatex(lib)
```

### journals

Journal name operations.

```python
from pynakes.journals import (
    abbreviate_journals,
    expand_journals,
)

lib = abbreviate_journals(lib)
lib = expand_journals(lib)
```

## Diff Utilities

### unified_diff

Generate a unified diff.

```python
from pynakes.diff import unified_diff

original = write_bib(lib)
modified = write_bib(lib_modified)
diff = unified_diff(original, modified)
print(diff)
```

## Typical Workflow

```python
from pynakes.io import load_bib, save_bib
from pynakes.keys import repair_duplicate_keys
from pynakes.lint import lint

# 1. Load
lib = load_bib("refs.bib")

# 2. Inspect
issues = lint(lib)
print(f"Found {len(issues)} issues")

# 3. Repair
lib, result = repair_duplicate_keys(lib)
print(f"Renamed {len(result.renamed)} keys")

# 4. Save
save_bib(lib, "refs.bib")
```

## Error Handling

Operations raise specific exceptions:

```python
from pynakes.errors import (
    ParseError,
    ConflictError,
    ValidationError,
)

try:
    lib = load_bib("invalid.bib")
except ParseError as e:
    print(f"Parse error at line {e.line}: {e.message}")

try:
    lib = merge_entries(lib, "Key1", "Key2")
except ConflictError as e:
    print(f"Conflict: {e.options}")
```

## JSON Serialization

All models support JSON serialization via `dataclasses.asdict()`:

```python
from dataclasses import asdict
import json

lib_dict = asdict(lib)
json_str = json.dumps(lib_dict)
lib_restored = json.loads(json_str)
```

## Type Hints

All functions are fully type-hinted:

```python
from typing import Optional
from pynakes.model import BibLibrary, BibEntry

def process_library(
    lib: BibLibrary,
    output_file: Optional[str] = None
) -> BibLibrary:
    """Process a library and optionally save it."""
    # ...
    return lib
```

## Next Steps

- [Usage Guide](../guides/usage.md)
- [Examples](../examples/index.md)
- [Architecture](../guides/architecture.md)
