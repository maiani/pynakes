# API Reference

Python API for programmatic usage of `pynakes`.

The command-line interface is the primary supported surface, but the operation
modules are also usable directly. Most operations mutate a `BibLibrary` in place
and return counts or operation-specific results.

## Data Models

### BibEntry

```python
from pynakes.model import BibEntry

entry = BibEntry(
    key="Smith2020",
    type="article",
    fields={
        "author": "John Smith",
        "title": "A Great Paper",
        "journal": "Nature",
        "year": "2020",
    },
)
```

### BibLibrary

```python
from pynakes.model import BibLibrary, EntryCollection

lib = BibLibrary(entries=EntryCollection([entry]))
print(len(lib.entries))
```

`BibLibrary.entries` is an `EntryCollection`, not a plain dict. It preserves
duplicate citation keys while exposing dict-like access to the first matching
entry.

## I/O

```python
from pynakes.io import load_bib, save_bib

lib = load_bib("refs.bib")
save_bib(lib, "refs.bib", backup=True, atomic=True)
```

## Parser and Writer

```python
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib

lib = parse_bib("""
@article{Smith2020,
  author = {John Smith},
  title = {A Great Paper},
  journal = {Nature},
  year = {2020}
}
""")

text = write_bib(lib)
```

## Groups

```python
from pynakes.groups import add_to_group, list_entries_in_group, list_groups, remove_from_group

groups = list_groups(lib)
changed = add_to_group(lib, "Smith2020", "AI")
members = list_entries_in_group(lib, "AI")
changed = remove_from_group(lib, "Smith2020", "AI")
```

## Citation Keys

```python
from pynakes.keys import (
    duplicate_key_counts,
    generate_key,
    regenerate_keys,
    repair_duplicate_keys,
)

entry = lib.entries["Smith2020"]
key = generate_key(entry, lib)
duplicates = duplicate_key_counts(lib)
renames = regenerate_keys(lib)
repairs = repair_duplicate_keys(lib)
```

`generate_key(entry, lib)` honors JabRef citation-key metadata in the library
when present.

## Fields

```python
from pynakes.fields import (
    append_field,
    clear_field,
    move_field,
    parse_query,
    protect_title_capitalization,
    rename_field,
)

rename_field(lib, "journal", "journaltitle")
append_field(lib, "keywords", "AI", where=parse_query('title contains "learning"'))
clear_field(lib, "abstract", where=parse_query("type = article"))
protect_title_capitalization(lib, terms=["OpenAI"])
move_field(lib, "school", "institution")
```

## DOI Import

```python
from pynakes.doi import prepare_imported_entry, render_entry

entry = prepare_imported_entry(
    lib,
    "10.5555/example",
    key_source="generated",
)

entry_text = render_entry(entry, lib.line_ending)
```

The CLI handles appending the rendered entry to the original file. Library code
can use `prepare_imported_entry` when composing a custom workflow.

## Normalization

```python
from pynakes.normalize import NormalizeOptions, normalize_library

report = normalize_library(
    lib,
    NormalizeOptions(
        author_style="jabref",
        journal_style="abbreviated",
    ),
)

print(report.operations)
print(report.warnings)
```

Author styles:

- `jabref`: convert person names to JabRef-style comma form
- `conservative`: normalize separators and whitespace only
- `none`: skip author/editor normalization

## Journals

```python
from pynakes.journals import (
    abbreviate_title_with_ltwa,
    load_sources,
    normalize_journals,
)

sources = load_sources(journal_table="journals.csv", ltwa_table="ltwa.csv")
result = normalize_journals(lib, "abbreviated", sources)
generated = abbreviate_title_with_ltwa("Journal of Polymer Science", sources)
```

`normalize_journals` resolves abbreviations in this order:

1. user exact title/ISSN table
2. bundled exact mappings
3. LTWA-style word abbreviation generation
4. unknown warning

## Usage Analysis

```python
from pynakes.usage import analyze_usage, collect_cited_keys, subset_library

cited, include_all, sources = collect_cited_keys(["paper.tex", "paper.aux"])
report = analyze_usage(lib, cited, include_all=include_all, sources=sources)
sub = subset_library(lib, report.used)
```

## Lint

```python
from pynakes.lint import lint

issues = lint(lib)
for issue in issues:
    print(issue.to_dict())
```

## Diffs

```python
from pynakes.diff import generate_diff

diff = generate_diff(original_text, new_text, "refs.bib")
```

## Typical Workflow

```python
from pathlib import Path

from pynakes.bibtex_writer import write_bib
from pynakes.diff import generate_diff
from pynakes.io import load_bib, save_bib
from pynakes.normalize import normalize_library

path = Path("refs.bib")
original = path.read_text(encoding="utf-8")
lib = load_bib(str(path))

report = normalize_library(lib)
new_text = write_bib(lib)
print(report.operations)
print(generate_diff(original, new_text, path.name))

save_bib(lib, str(path))
```

## Error Handling

```python
from pynakes.bibtex_parser import ParseError
from pynakes.doi import DuplicateDOIError, DOIImportError

try:
    lib = load_bib("invalid.bib")
except ParseError as exc:
    print(exc.message)

try:
    prepare_imported_entry(lib, "10.5555/example")
except DuplicateDOIError as exc:
    print(exc.keys)
except DOIImportError as exc:
    print(str(exc))
```

## Next Steps

- [Usage Guide](../guides/usage.md)
- [Examples](../examples/index.md)
- [Architecture](../guides/architecture.md)
