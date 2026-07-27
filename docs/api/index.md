# API Reference

Python API for programmatic usage of `pynakes`.

The package exposes a first-class application API; callers do not need to invoke
the CLI or decode its JSON envelopes. Most operations mutate a `BibFile` in
place and return counts or operation-specific results. For transactional file
editing, use `Bibliography`. The supported Python API and semantic-versioning
promise are defined in [Public API and compatibility](../guides/public-api.md).

!!! tip "Looking for signatures, classes, and return types?"
    The complete symbol reference — every public class, function, exception,
    and constant — is generated from the source docstrings on the
    [Module Reference](reference.md) page, so it never drifts from the code.
    This page is a task-oriented tour of the same API.

## Recommended application workflow

Common lifecycle and model names are available from the package root:

```python
from pynakes import Bibliography, CanonicalLayout, ExternalModificationError

bib = Bibliography.open("refs.bib")

issues = bib.lint()
bib.format(
    CanonicalLayout(
        field_order="preferred",
        entry_order="preserve",
        wrap_values="stable",
        line_width=100,
    )
)

print(bib.change_plan())  # structured semantic summary
print(bib.diff())         # exact textual patch

try:
    result = bib.commit(backup=True)
except ExternalModificationError:
    # The file changed after it was opened. Reload or reconcile; do not guess.
    raise
```

Nothing is written until `commit()`. An application can call `reset()` to
discard staged work or use `preview()` to obtain the complete prospective
output. `commit()` revalidates and writes atomically.

For an in-memory transform with no filesystem binding:

```python
from pynakes import Bibliography

bib = Bibliography.from_text("@misc{Example, title={An Example}}\n")
bib.set_field("year", "2020", "key = Example")
result_text = bib.preview()
```

### Embedding in an MCP or service process

Use `Bibliography` as the per-resource state boundary and call its methods
directly. This keeps transport concerns outside the bibliography engine:

- expose operation return objects or their `to_dict()` methods where available;
- use `change_plan()` for semantic review and `diff()` for exact text review;
- map domain exceptions to protocol errors rather than parsing CLI messages;
- retain the open-to-commit fingerprint check for concurrent file changes;
- invoke network-backed methods only when the tool call explicitly authorizes
  online access.

The CLI and an MCP server can therefore remain thin adapters over the same
in-process operations.

## Work-matching evidence

Pynakes represents what is known about two records without claiming a universal
bibliographic identity:

```python
from pynakes import compare_work_evidence, evidence_from_entry

left = evidence_from_entry(bib.entries["Lovelace1843"])
right = evidence_from_entry(bib.entries["Lovelace1843Copy"])
match = compare_work_evidence(left, right)

print(match.status)   # exact, probable, conflict, or unknown
print(match.reasons)  # inspectable evidence for the decision
```

Matching normalized identifiers produce `exact`; incompatible identifiers of
the same kind produce `conflict`. Title, year, and shared-author similarity can
produce only `probable`. A title fingerprint is candidate evidence, never an
identity. ORCID is deliberately excluded because it identifies a contributor,
and preprint/publication relationships remain a separate concern.

## Data Models

### BibEntry

```python
from pynakes import BibEntry

entry = BibEntry(
    key="Smith2020",
    type="article",
    fields={
        "author": "John Smith",
        "title": "A Great Paper",
        "journal": "Journal of Examples",
        "year": "2020",
    },
)
```

### BibFile

```python
from pynakes import BibFile, EntryStore

lib = BibFile(entries=EntryStore([entry]))
print(len(lib.entries))
```

`BibFile.entries` is an `EntryStore`, not a plain dict. It preserves
duplicate citation keys while exposing dict-like access to the first matching
entry.

`BibFile.jabref_metadata_blocks` holds the `jabref-meta` namespace;
`BibFile.pynakes_metadata_blocks` holds the `pynakes-meta` superset.
`BibFile.jabref_metadata`, `BibFile.pynakes_metadata`, and `BibFile.metadata`
are fresh derived mappings for read access; update metadata through
`pynakes.metadata.set_metadata`, not by mutating those dicts. `BibFile.metadata`
is the effective merged view (pynakes overrides jabref), and
`BibFile.metadata_blocks` returns both namespaces in source order. Each block
preserves its raw comment text, namespace, known/unknown classification, and
category.

The key entry points are `model.BibEntry`, `model.BibFile`, `model.EntryStore`,
and `engine.Bibliography`; see their generated entries in the
[Module Reference](reference.md) for field-by-field detail.

## Result and Analysis Objects

Operation reports describe what an in-place operation did; they do not contain a
replacement `BibFile`. Where present, `to_dict()` is the JSON-friendly form used
by the CLI. The full set of report objects (per domain) and their fields are in
the [Module Reference](reference.md) — for example `NormalizeResult`,
`JournalResult`, `DedupeMergeReport`, `VerifyReport`, `UsageReport`, and
`LintIssue`.

Domain exceptions communicate recoverable failure categories: `ParseError` for
invalid BibTeX; DOI import errors; `DuplicateMetadataError`; a
`DedupeConflictError` containing `MergeConflict` values; `MetadataFetchError`;
and `ExternalModificationError` for a concurrent bibliography commit.

## I/O

```python
from pynakes import load_bib, save_bib

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
from pynakes import Bibliography, ExternalModificationError

coll = Bibliography.open("refs.bib")
issues = coll.lint()
renames = coll.repair_keys()
report = coll.normalize()

print(coll.diff())
result = coll.commit()
```

`Bibliography` owns the load → stage → preview → commit lifecycle for one `.bib` file.
It keeps the file as the source of truth: staged operations mutate the in-memory
library only, `preview()` returns the would-be file text, `diff()` returns a
unified diff, and `commit()` writes atomically through the same validation path
as the CLI. `reset()` discards staged edits and `reload(force=True)` re-reads
from disk.

`commit()` checks a size/mtime/content fingerprint captured at `open`; if the
file changed underneath, it raises `ExternalModificationError` instead of
silently overwriting external edits. Call `externally_changed()` to poll the
same check before committing.

`is_dirty` is derived from actual preview output plus pending Pinax filesystem
transactions, so a semantic no-op does not block `reload()`.

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
  journal = {Journal of Examples},
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
unknown key requires `allow_unknown=True`. `MetadataBlock.value` is the parsed
payload as stored in the comment, while `normalized_value` strips JabRef's
trailing semicolon for display and semantic comparisons.

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

## Reference Import (DOI / arXiv)

```python
from pynakes.engine import Bibliography

coll = Bibliography.open("refs.bib")
kind, entry = coll.import_reference(
    "arXiv:2301.00001",  # or a DOI / DOI URL / arXiv URL
    key_source="generated",
)
print(kind)  # "arxiv" or "doi"
print(coll.diff())
```

`import_reference()` auto-detects the identifier type, fetches metadata only (no
PDFs), and — for arXiv — emits `@online` for BibLaTeX libraries and `@misc` for
BibTeX ones per `databaseType`. `Bibliography.import_doi()` remains as the
DOI-specific entry point.

For lower-level workflows, `pynakes.importer.prepare_imported_reference`,
`pynakes.importer.prepare_imported_entry`, and `pynakes.importer.render_entry`
are available. The staged append lets `diff()`/`commit()` handle preservation
and atomic writes.

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

`WorkIdentifier` is one normalized piece of evidence (such as a DOI or arXiv
identifier) used to explain a `DuplicateCluster`; it is not a universal entity
identifier. A merge reports the selected primary record as `ClusterMerge`; a
conflicting field/type is a `MergeConflict`, never an automatic loss of data.
Integrity report objects keep provider findings separate from `FieldUpdate`
records, so callers can distinguish an observation from an applied enrichment.

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
from pynakes.importer import DuplicateReferenceError, ReferenceImportError

try:
    lib = load_bib("invalid.bib")
except ParseError as exc:
    print(exc.message)

try:
    prepare_imported_reference(lib, "10.5555/example")
except DuplicateReferenceError as exc:
    print(exc.keys)
except ReferenceImportError as exc:
    print(str(exc))
```

## Next Steps

- [Public API and compatibility](../guides/public-api.md)
- [Usage Guide](../guides/usage.md)
- [Examples](../examples/index.md)
- [Architecture](../guides/architecture.md)
