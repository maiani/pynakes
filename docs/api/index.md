# API Reference

Python API for programmatic usage of `pynakes`.

The command-line interface is the primary supported surface, but the operation
modules are also usable directly. Most operations mutate a `BibFile` in place
and return counts or operation-specific results.

The Python API is the implementation boundary used by the CLI. Its object model
and behavior are documented here; stable versioned API pinning remains planned,
so consumers should avoid private names (those beginning with `_`).

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

### BibFile

```python
from pynakes.model import BibFile, EntryStore

lib = BibFile(entries=EntryStore([entry]))
print(len(lib.entries))
```

`BibFile.entries` is an `EntryStore`, not a plain dict. It preserves
duplicate citation keys while exposing dict-like access to the first matching
entry.

`BibFile.jabref_metadata` / `.jabref_metadata_blocks` hold the `jabref-meta`
namespace; `BibFile.pynakes_metadata` / `.pynakes_metadata_blocks` hold the
`pynakes-meta` superset. `BibFile.metadata` is the effective merged view
(pynakes overrides jabref) that operations read, and `BibFile.metadata_blocks`
returns both namespaces in source order. Each block preserves its raw comment
text, namespace, known/unknown classification, and category.

### Core model concepts

| Class | Concept | Important behavior |
| --- | --- | --- |
| `BibEntry` | One record plus source-preservation state | `fields` accepts standard and custom fields alike; `raw_content` lets an untouched source entry be emitted verbatim. |
| `EntryStore` | Lossless collection of a file's entries | Maintains source order and duplicate keys. `get()`/`[]` use first-match lookup; `values()`, `get_all()`, and `duplicate_keys()` are duplicate-aware. |
| `BibFile` | Parsed semantic view of one `.bib` file | Holds entries, top-level declarations/comments, JabRef blocks, encoding, and line ending. |
| `JabRefMetadataBlock` | One structured top-level `jabref-meta` comment | Keeps the raw comment alongside parsed key/value/category data. |
| `Collection` | The working unit: a staged handle over one `.bib` file | Provides the lifecycle around a `BibFile`, not a second persistent source of truth. |

## Result and Analysis Objects

Operation reports describe what an in-place operation did; they do not contain a
replacement `BibFile`. Where present, `to_dict()` is the JSON-friendly form used
by the CLI.

| Domain | Classes | Concept |
| --- | --- | --- |
| Engine and I/O | `FileFingerprint`, `CommitResult`, `SaveResult` | External-change state, staged-commit outcome, and backup/write outcome. |
| Normalization and conversion | `NormalizeOptions`, `NormalizeResult`, `ConvertResult` | Policy overrides, per-domain change counts, and conservative conversion warnings. |
| Journals | `JournalMapping`, `JournalSources`, `JournalResult` | One exact mapping, the precedence-ordered lookup sources, and normalization outcome. |
| Dedupe | `WorkIdentity`, `DuplicateCluster`, `MergeConflict`, `ClusterMerge`, `DedupeMergeReport` | Evidence records describe the same work, merge decisions, and ambiguity that blocks guessing. |
| Integrity | `IntegrityIssue`, `VerifyReport`, `FieldUpdate`, `EnrichReport`, `PublishedCandidate`, `PublishedReport` | Provider-backed findings and the explicitly applied metadata changes. |
| Files, usage, and lint | `LinkedFile`, `FileCheckReport`, `UsageReport`, `LintIssue` | Read-only analysis items and summaries. |
| JabRef metadata | `JabRefMetadataUpdate` | The exact raw comment replacement/insertion needed for a minimal-diff update. |

Domain exceptions communicate recoverable failure categories: `ParseError` for
invalid BibTeX; DOI import errors; `DuplicateJabRefMetadataError`; a
`DedupeConflictError` containing `MergeConflict` values; `MetadataFetchError`;
and `ExternalModificationError` for a concurrent collection commit.

## I/O

```python
from pynakes.io import load_bib, save_bib

lib = load_bib("refs.bib")
result = save_bib(lib, "refs.bib", backup=True, atomic=True)
if not result.success:
    raise OSError(result.error)
```

`SaveResult` records the destination, optional `.bak` path, and controlled
error information. `load_bib` records the detected file encoding on the
returned library.

## Engine Facade

```python
from pynakes.engine import ExternalModificationError, Collection

coll = Collection.open("refs.bib")
issues = coll.lint()
renames = coll.repair_keys()
report = coll.normalize()

print(coll.diff())
result = coll.commit()
```

`Collection` owns the load → stage → preview → commit lifecycle for one `.bib` file.
It keeps the file as the source of truth: staged operations mutate the in-memory
library only, `preview()` returns the would-be file text, `diff()` returns a
unified diff, and `commit()` writes atomically through the same validation path
as the CLI. `reset()` discards staged edits and `reload(force=True)` re-reads
from disk.

`commit()` checks a size/mtime/content fingerprint captured at `open`; if the
file changed underneath, it raises `ExternalModificationError` instead of
silently overwriting external edits. Call `externally_changed()` to poll the
same check before committing.

`FileFingerprint` is that optimistic-concurrency snapshot. A
`CommitResult` contains the pre-commit staged diff, whether content was
written, and the changed-entry count.

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
    rename_key,
    repair_duplicate_keys,
)
from pynakes.usage import rename_citation_key_in_tex

entry = lib.entries["Smith2020"]
key = generate_key(entry, lib)
duplicates = duplicate_key_counts(lib)
renames = regenerate_keys(lib)
changed = rename_key(lib, "Smith2020", "Smith2020ML")
repairs = repair_duplicate_keys(lib)

source_text, occurrences = rename_citation_key_in_tex(
    source_text,
    "Smith2020",
    "Smith2020ML",
)
```

`generate_key(entry, lib)` honors JabRef citation-key metadata in the library
when present.

## JabRef Metadata

```python
from pynakes.metadata import set_metadata

for block in lib.jabref_metadata_blocks:
    print(block.key, block.normalized_value, block.category, block.known)

update = set_metadata(lib, "databaseType", "biblatex")
print(update.old_raw, update.new_raw)
```

Known metadata keys include JabRef database/save/group/file/selector/key-pattern
blocks such as `databaseType`, `saveOrderConfig`, `saveActions`, `groupstree`,
`fileDirectory*`, `selector_*`, `VersionDBStructure`, `keypatterndefault`, and
`keypattern_<entrytype>`. Unknown blocks are parsed and preserved; setting an
unknown key requires `allow_unknown=True`.

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
from pynakes.engine import Collection

coll = Collection.open("refs.bib")
entry = coll.import_doi(
    "10.5555/example",
    key_source="generated",
)
print(coll.diff())
```

For lower-level workflows, `pynakes.doi.prepare_imported_entry` and
`pynakes.doi.render_entry` remain available. `Collection.import_doi()` stages the
append and lets `diff()`/`commit()` handle preservation and atomic writes.

## Linked Files

```python
from pynakes.files import check_linked_files, parse_linked_files

linked = parse_linked_files(lib)
report = check_linked_files(lib, "refs.bib", roots=["~/papers"])

for issue in report.issues:
    print(issue.entry_key, issue.path, issue.status)
```

`check_linked_files` resolves relative JabRef `file` links against the
bibliography directory, explicit roots, and JabRef `fileDirectory*` metadata.
It reports `ok`, `missing`, `wrong_type`, and `unresolved`.

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

`JournalMapping` represents an exact full-title/abbreviation association;
`JournalSources` is the precedence-ordered index used for lookups; and
`JournalResult` records changed, resolved, and unresolved titles.

## Dedupe and Integrity

```python
from pynakes.dedupe import find_duplicate_clusters, merge_duplicates
from pynakes.integrity import verify_library

clusters = find_duplicate_clusters(lib)
merge_report = merge_duplicates(lib, clusters)  # raises DedupeConflictError if ambiguous
verification = verify_library(lib, online=False)
```

`WorkIdentity` is a stable identifier (such as a DOI or arXiv identifier) used
to explain a `DuplicateCluster`. A merge reports the selected primary record as
`ClusterMerge`; a conflicting field/type is a `MergeConflict`, never an
automatic loss of data. Integrity report objects keep provider findings separate
from `FieldUpdate` records, so callers can distinguish an observation from an
applied enrichment.

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
