# Architecture

This page introduces the design of pynakes. The repository-root `ARCHITECTURE.md` is the canonical contributor document; the [API reference](../api/index.md) gives direct Python examples.

## Design in one sentence

pynakes treats a .bib file as the source of truth and provides a conservative in-memory model plus surgical editing and atomic write paths around it.

~~~text
CLI / programmatic caller
            |
            v
     Collection lifecycle facade
            |
            v
 domain operations and reports
            |
            v
 model + editing + parser/writer + I/O
            |
            v
          .bib file
~~~

The layers have distinct responsibilities:

- The parser turns source text into an in-memory model without rejecting duplicate keys or unfamiliar fields.
- Domain modules mutate that model in place and return counts or report objects.
- The editing layer keeps a mutation localized to the changed field/key whenever raw source text is available.
- Collection stages operations, produces previews/diffs, detects external changes, and commits safely.
- The CLI handles arguments plus the stable JSON and exit-code contract.

## Core concepts

| Concept | Class | What it represents |
| --- | --- | --- |
| Bibliographic entry | BibEntry | One record, its fields, and its original raw entry text. |
| Duplicate-tolerant collection | EntryStore | Source-ordered entries. Dict-like access returns the first matching citation key, while get_all() and duplicate_keys() retain visibility of every duplicate. |
| Parsed file | BibFile | Entries plus comments, strings, preambles, JabRef metadata, encoding, and line-ending style for one .bib file. |
| JabRef metadata | JabRefMetadataBlock | One raw-aware top-level jabref-meta comment block. |
| Collection (working unit) | Collection | The staged handle for one `.bib` file — a slice of references on one aspect of a topic: open, stage, preview/diff, commit, reset, and reload. |
| Library (corpus, planned) | Library (planned) | A directory/repository of Collections — the lifelong corpus. Does not exist yet (Beyond 1.0). |
| Catalogue (index, planned) | Catalogue (planned) | A derived, rebuildable search index over the Library. The Collections stay the source of truth. Does not exist yet (Beyond 1.0). |

### Why EntryStore is not a dictionary

A real bibliography can contain duplicate citation keys. Replacing that state with a normal dictionary silently loses an entry, which prevents the linter and key-repair operation from doing their job. EntryStore preserves every entry in source order and only provides first-match lookup as a convenience.

### How preservation works

Parsed entries retain raw_content. Editing helpers update both the fields mapping and that raw text, so a field change normally affects only the relevant text span. Collection splices those changed entry blocks into the pristine file text, retaining unrelated entries, comments, blank lines, and formatting.

The lower-level writer also emits an unmodified entry's raw text verbatim, but direct whole-library serialization may reassemble top-level constructs. Use Collection when the goal is the smallest practical file diff.

## Collection lifecycle

~~~python
from pynakes.engine import Collection

collection = Collection.open("refs.bib")
collection.rename_field("journal", "journaltitle")

print(collection.diff())       # no file write
result = collection.commit()   # validated atomic write and backup
~~~

Collection stores a snapshot and a size/mtime/content fingerprint when it opens a path. A commit refuses to overwrite a file changed externally, raising ExternalModificationError unless the caller explicitly passes force=True. reset() discards staged work; reload() obtains current disk state and refuses to discard a dirty buffer unless forced.

## Module ownership

| Module | Owns |
| --- | --- |
| groups.py | JabRef group fields |
| keys.py | Citation-key creation, validation, repair, and rename |
| fields.py | Field edits, simple filters, title capitalization |
| authors.py | Person-list parsing and normalization |
| doi.py | DOI parsing, canonicalization, and import preparation |
| metadata.py | jabref-meta + pynakes-meta parsing and safe updates |
| journals.py | Exact and LTWA-style journal title resolution |
| normalize.py | Composed title/author/journal/DOI normalization policy |
| convert.py | Conservative BibTeX/BibLaTeX conversion |
| files.py | JabRef linked-file parsing and validation |
| usage.py | AUX/TeX citation analysis and subset/tagging operations |
| lint.py | Local validation findings |
| dedupe.py | Duplicate-work clustering and conflict-first merges |
| integrity.py | Opt-in metadata verification, enrichment, and preprint checks |

The detailed [API reference](../api/index.md#result-and-analysis-objects) maps each public report class to its domain concept.

## Safety and automation

All modifying CLI commands use a consistent output envelope and support dry-run/diff review. They exit 0 on success, 1 on errors, and 2 on conflicts that need a decision. The [LLM integration guide](llm-integration.md) defines that machine contract.

Network access is not implicit. DOI import performs a requested lookup; integrity commands require --online for provider checks and support cached responses.

## Boundaries

pynakes intentionally does not own a database, GUI, cloud sync, PDF extraction, or LLM calls. An MCP server is a downstream transport option: the CLI already supplies the safe machine-readable interface.

- [API reference](../api/index.md)
- [Usage guide](usage.md)
- The repository-root `ARCHITECTURE.md` and `DEVPLAN.md` contain contributor-level design and roadmap detail.
