# Architecture

The design reference for pynakes contributors and maintainers. For task-oriented
usage see the [Usage guide](usage.md); for direct Python use see the
[API reference](../api/index.md).

## Purpose and constraints

pynakes is a headless maintenance engine for BibTeX, BibLaTeX, and
JabRef-compatible .bib files. It makes small, reviewable changes without
discarding information a reference manager or a human placed in the file.
It is also the deterministic execution layer beneath agentic bibliography
workflows: an agent decides what should change, while pynakes exposes bounded
operations that inspect, validate, preview, and apply the change.

1. **Preserve before normalizing.** Unknown fields, duplicate citation keys,
   comments, JabRef metadata, line endings, and source encodings remain data,
   not parser errors.
2. **Make minimal edits.** Entry mutations go through `editing.py`, which changes
   the relevant raw field/key text while keeping the rest of the entry intact.
3. **Be explicit about uncertainty.** Dedupe, metadata enrichment, and DOI import
   report conflicts instead of silently selecting a value.
4. **Keep the file authoritative.** In-memory state is a derived working view;
   there is no database or persistent sidecar state of record.
5. **Remain deterministic by default.** Network access is explicit (with
   `--online` where supported) and provider responses can be cached.

## Domain vocabulary and core concepts

The model has three nested concepts: **entry** < **bibliography** < future
**library**. A Pinax is not a fourth model layer; it is an optional mode of one
Bibliography when `pynakes-meta` declares a `files-dir`.

| Concept | Implemented class | Meaning |
| --- | --- | --- |
| Entry | BibEntry | One bibliographic record plus the raw entry text needed to preserve its layout. |
| Entry collection | EntryStore | Ordered, duplicate-key-tolerant container for a file's entries. Dict-like lookup returns the first match; explicit methods expose all duplicates. |
| File model | BibFile | Semantic content of one parsed .bib file: entries, declarations, comments, structured JabRef metadata, encoding, and line-ending style. |
| Metadata block | MetadataBlock | One top-level metadata comment — `@comment{jabref-meta: ...}` or pynakes' superset `@comment{pynakes-meta: ...}` (tagged by `namespace`) — represented both structurally and as raw text. |
| Bibliography (working unit) | Bibliography | A staged, reconciled handle over one `.bib` file — "a slice of references covering one aspect of a topic". Supports operations, preview, diff, commit, reset, reload, and external-change detection. |
| Pinax mode | FileStore + fetch primitives | Optional mode of one Bibliography together with its `files-dir` of citation-key-addressed materials. Plain bibliographies have no Pinax behavior. Includes agent inspection, file checks/fixes, arXiv material fetch, provenance manifests, set-operation copying, and coordinated key-edit material moves. |
| Library (corpus) | — (planned) | A directory of pinakes/bibliographies, enabling cross-file search, dedup, and identity resolution across the full research corpus. Not implemented yet (see [Beyond 1.0](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md)). |
| Catalogue (index) | — (planned) | A derived, rebuildable search index over the Library (e.g. SQLite FTS). Never a competing source of truth; the Bibliographies are. Not implemented yet. |

### BibEntry: record plus preservation state

`BibEntry.fields` is intentionally an unrestricted `dict[str, str]`: standard,
BibLaTeX, JabRef, and user-defined fields all belong in the same model. An entry
also carries `raw_content`, its original source block. For a parsed entry,
`editing.py` synchronizes `fields` and `raw_content` so a single field edit has a
single-field diff. Entries created only in memory have no raw source and are
marked modified; the writer reconstructs them when necessary.

### EntryStore: a safe alternative to a dict

A plain `dict[str, BibEntry]` cannot represent a broken but common bibliography
state: two entries with the same citation key. EntryStore stores entries in
source order and accepts duplicates. It offers familiar `keys()`, `values()`,
`items()`, `get()`, and `[]` access, with **first match wins** semantics. Code
that needs lossless behavior uses `values()`, `get_all(key)`, or
`duplicate_keys()`.

This distinction is load-bearing: parsing duplicate keys must not discard an
entry, while key repair and linting must see every occurrence.

### BibFile: one file's semantic view

BibFile owns the set of entries and top-level BibTeX constructs: `@string`
definitions, `@preamble` blocks, comments, and metadata. Metadata lives in two
namespace block lists — `jabref_metadata_blocks` for `jabref-meta` and
`pynakes_metadata_blocks` for the `pynakes-meta` superset. The flat
`jabref_metadata`, `pynakes_metadata`, and merged `metadata` mappings are fresh
derived views; update metadata through `metadata.set_metadata`, not by mutating
those dicts. Its `encoding` and `line_ending` record the source representation
for safe I/O.

Metadata has two independent axes. The parsed **namespace** records where a
block came from (`jabref-meta` or `pynakes-meta`), preserving source structure.
The key **owner** records who understands the setting: JabRef-native keys route
to `jabref-meta` by default for compatibility; pynakes-owned and unknown keys
route to `pynakes-meta`, where pynakes can extend JabRef without polluting
JabRef's namespace. The key **category** is only a domain label for inspection
and validation messages (`library`, `save`, `normalization`, `pinax`, …). See
the [JabRef compatibility guide](jabref-compatibility.md) for the full
namespace/owner/routing model and pynakes' native keys (`dialect`,
`sort-order`) that alias a JabRef equivalent.
For values, `MetadataBlock.raw` is the exact source comment, `value` is the
parsed payload with JabRef's trailing semicolon preserved when present, and
`normalized_value` is the stripped display/semantic view used in reports.

The BibFile is mutable by design. Operations change it in place and return a
count or domain report; they do not return a replacement BibFile.

### Bibliography: lifecycle and optimistic concurrency

Bibliography is the engine facade for one .bib file. It binds the mutable BibFile
to pristine text, entry snapshots, and a file fingerprint. A bibliography is a
*derived editing buffer*, not a second source of truth.

~~~text
open / from_text / from_bibfile
             |
             v
  stage operation methods (in memory only)
             |
      +------+------+
      |             |
      v             v
 preview()/diff()  reset() -> restore pristine state
      |
      v
 commit() -> check fingerprint -> validate/write atomically -> refresh snapshot
~~~

`commit()` rejects an externally modified bound file with
`ExternalModificationError` unless `force=True` is selected deliberately.
`externally_changed()` exposes the same check to long-lived consumers; `reload()`
refuses to discard dirty staged state without `force=True`.

`FileFingerprint` is the observed state used by that optimistic-concurrency
check; `CommitResult` reports whether a commit wrote, its staged diff, and the
number of changed entries.

#### State model: a thin handle over a file-derived buffer

The lifecycle above follows directly from constraints #4 (the file is the source
of truth) and #5 (determinism):

- **Bibliography is a thin stateful *handle*** bundling `{path, lib, pristine
  snapshot, fingerprint, is_dirty}`. Its in-memory state is a derived buffer over
  the file, never an authoritative model.
- **Rendering and diffing are derived from explicit snapshots.** Bibliography
  retains pristine text and per-entry snapshots, then derives preview text and a
  diff from its staged library.
- **Litmus test for any state:** *if I delete it and re-read from disk, do I lose
  anything?* No → a safe derived buffer. Yes → a second source of truth, which is
  not allowed.

The same object serves both consumer shapes: the CLI uses it transactionally
(`open → op → commit`); a long-lived application may hold it open across edits.
In both cases the buffer stays derived and `commit()` reconciles with the live
file.

#### External-change detection

Several actors can edit the same file — the application, the user's text editor,
and an agent — so the engine treats the file as truth and the buffer as derived,
reconciling like an editor reloading a changed file:

- **Clean buffer + file changed on disk → reload cleanly.** Nothing is staged, so
  the buffer can mirror the new disk content.
- **Dirty buffer + file changed on disk → conflict, never silent clobber.** The
  consumer is notified and decides; the engine does not auto-resolve.
- **`commit()` while the disk changed since open → `ExternalModificationError`**
  (unless forced), so a save can't overwrite an external edit blindly.

The engine exposes only the *pull* primitives this needs — `fingerprint` /
`externally_changed()`, `reload(force=False)`, and `is_dirty`. A push-style
filesystem watcher is intentionally **not** in core: it is a background thread
(non-deterministic, dependency-bearing, and a UX concern), so the watch loop is a
consumer's job. If a push helper ever earns its place it would ship as an opt-in
extra, never required by core.

## Layers and dependency direction

~~~text
CLI / external callers
          |
          v
Bibliography lifecycle facade (engine.py)
          |
          v
Domain operations (groups, keys, fields, dedupe, integrity, ...)
          |
          v
Editing + model + parser/writer + I/O
          |
          v
                         .bib file
~~~

The CLI is intentionally thin: it opens a Bibliography, invokes an operation,
previews or commits it, and emits the structured output envelope. Domain modules
depend on the model and editing helpers, not on CLI behavior. Bibliography
delegates to those modules rather than duplicating transformation rules — which
is also the proof the boundary is correct: a downstream consumer can drive the
same `open → op → diff/commit` flow the CLI does.

## Parsing, preservation, and writing

### Parsing

`bibtex_parser.parse_bib(text)` is a custom parser. It constructs
BibFile/BibEntry instances, keeps duplicate keys, captures each entry's raw text,
collects top-level comments and declarations, detects line endings, and parses
JabRef metadata blocks. It deliberately does not use a general BibTeX dependency:
round-trip control is more important than normalizing an input into another
library's data model.

Parsing is conservative, not a formatter. Field values are represented as
strings, unknown entry fields survive, and malformed structural input raises
`ParseError` with source context.

### Parser conformance baseline

The parser-conformance target is pinned to **TeX Live 2026** (BibTeX **0.99d**,
BibLaTeX **3.21**, and Biber **2.21** as the BibLaTeX input-validation oracle).
The versioned corpus and CI validation remain a release gate; pynakes should not
claim broader standards compatibility than this pinned baseline exercises.

### Surgical edits

`editing.py` is the only mutation boundary for entry fields, entry keys, and
entry types. Its raw-text functions make localized changes; its entry-level
helpers also update `BibEntry.fields` and modification state. Operation modules
must use these helpers instead of assigning `raw_content` directly or rebuilding
entries.

`splice_into_text()` applies known raw-entry replacements to the original file
text. Bibliography uses it so untouched text between entries remains stable during
a normal staged commit.

### Writing and I/O

`bibtex_writer.write_bib()` serializes a BibFile. Unmodified entries with
`raw_content` are emitted verbatim; modified or source-less entries are
reconstructed with their insertion field order. This is an **entry-level**
round-trip guarantee. Direct whole-library serialization can reassemble top-level
constructs, so callers wanting the smallest possible file diff should use
Bibliography.

`io.load_bib()` detects UTF-8 or Latin-1 from bytes before parsing. `save_bib()`
and `save_text()` support backup creation, temporary-file writes, re-parse
validation for BibTeX text, and replacement of the destination. They return
`SaveResult` rather than exposing ordinary write failures as raw tracebacks to
the CLI.

## Domain modules

| Module | Concept it owns |
| --- | --- |
| groups.py | JabRef-compatible flat membership stored in an entry groups field. |
| group_tree.py | Hierarchical group model, native pipe-delimited format, CRUD operations, and tree-aware entry queries. JabRef group parsers/serializers live in `metadata/jabref.py`. |
| keys.py | Citation-key generation, validation, duplicate detection/repair, and key renames. |
| fields.py | Generic field changes, simple predicates, and title capitalization protection. |
| authors.py | BibTeX name-list splitting, last-name extraction, and conservative/JabRef-style normalization. |
| importer.py | Reference import: identifier resolution (DOI/arXiv), DOI canonicalization, arXiv normalization/Atom parsing, and entry preparation. It is the DOI and arXiv identifier authority. |
| filestore.py | Pinax material paths, presence scanning, orphan/drift detection and repair, provenance manifests, material copying, and atomic writes inside a configured `files-dir`. |
| fetch.py | arXiv material URL construction, injectable PDF/source byte fetchers, safe source archive extraction, and FileStore installation. |
| metadata/ (core.py, schema.py, jabref.py) | Structured top-level metadata, layered by dependency direction: `core` is the namespace-neutral comment engine (parse/format/set/remove/consolidate); `schema` is pynakes' own canonical key registry and native reads, JabRef-unaware; `jabref` is the compatibility adapter — JabRef's key tables and value grammars, the JabRef group parsers/serializers (`parse_jabref_grouping`, `format_jabref_grouping`, `parse_jabref_groups_lines`), owner/namespace arbitration, and fallback-aware accessors (`library_dialect`, `library_sort_order`). Domain code depends on `schema`'s concepts through `jabref`'s accessors, never on JabRef's literal keys. See the [JabRef compatibility guide](jabref-compatibility.md). |
| journals.py | Exact title/ISSN mapping plus LTWA-style journal abbreviation/expansion. |
| normalize.py | Policy orchestration over title, author, journal, and DOI operations. |
| convert.py | Conservative BibTeX/BibLaTeX convention conversion. |
| files.py | Parsing and resolution/validation of BibLaTeX linked-file descriptors. |
| usage.py | LaTeX/AUX citation extraction, library-usage analysis, tagging, and subset projection. |
| lint.py | Local structural/semantic findings such as missing required fields, malformed DOI, groups, and duplicate keys. BibLaTeX required-field rules cite the official CTAN BibLaTeX manual, section 2.1 entry types and aliases, as their source of truth. |
| dedupe.py | Duplicate-work clustering and conflict-first merge planning. |
| integrity.py | Opt-in provider-backed verification, conservative enrichment, and preprint publication checks. |
| diff.py | Unified diff generation. |
| cli.py, cli_common.py, cli_commands/ | Thin Typer application assembly, shared JSON/error/check plumbing, and one command module per command family. |
| capabilities.py | Machine-readable declaration of the implemented CLI surface. |

### Result and report objects

Report dataclasses make mutable operations inspectable without hiding their
effects. They provide `to_dict()` where structured output is needed. The
[API reference](../api/index.md#result-and-analysis-objects) documents each
class's behavior.

| Area | Classes | Concept |
| --- | --- | --- |
| Normalization/conversion/journals | NormalizeOptions, NormalizeResult, ConvertResult, JournalMapping, JournalSources, JournalResult | Configured policy, source layers, applied transformations, and warnings. |
| Dedupe | WorkIdentity, DuplicateCluster, MergeConflict, ClusterMerge, DedupeMergeReport | Evidence that records describe one work, conservative merge outcomes, and unresolved ambiguity. |
| Integrity | IntegrityIssue, VerifyReport, FieldUpdate, EnrichReport, PublishedCandidate, PublishedReport | Remote-check findings and intentionally applied metadata changes. |
| File/usage/lint | LinkedFile, FileCheckReport, UsageReport, LintIssue | Read-only analysis findings and summaries. |
| Metadata/I/O | MetadataUpdate, SaveResult | A precise raw metadata replacement and a write outcome with backup/error context. |

## Errors, conflicts, and CLI contract

There is no artificial global exception hierarchy. Each domain exposes a specific
exception where callers need structured recovery:

| Condition | Exception / outcome |
| --- | --- |
| Structurally malformed BibTeX | ParseError |
| Reference import failure, duplicate DOI/arXiv, explicit key conflict | ReferenceImportError (DOIImportError/ArxivImportError), DuplicateReferenceError (DuplicateDOIError/DuplicateArxivError), CitationKeyConflictError |
| Unrecognized identifier passed to `ref import` | UnsupportedIdentifierError |
| Unsupported JabRef key pattern | UnsupportedCitationKeyPatternError |
| Duplicate/ambiguous metadata block | DuplicateMetadataError |
| Ambiguous duplicate-work merge | DedupeConflictError with MergeConflict values |
| Failed provider lookup or parse | MetadataFetchError |
| Concurrent file modification during a bibliography commit | ExternalModificationError |

The CLI converts expected failures into the documented JSON/error envelope:
success is exit code 0, errors exit 1, and conflicts exit 2 with options where an
interactive choice is possible. Modifying command responses share `status`,
`action`, `file`, `dry_run`, `modified`, `modified_entries`, and `warnings`;
`--diff` adds a unified diff. The complete contract is in the
[LLM integration guide](llm-integration.md).

## Network boundary

Only DOI/arXiv import, integrity workflows, and the Pinax arXiv download
primitives contact providers in the current implementation. Integrity workflows
require an explicit `online=True`/`--online` opt-in and support deterministic
caching; Pinax downloads require the explicit `asset fetch` command or `ref import --fetch`.
Plain `.bib` maintenance never fetches materials. Network parsing lives in
`importer.py`, `integrity.py`, and `fetch.py`; tests mock or fixture this
boundary so the normal suite never relies on external availability.

## Testing and change discipline

Tests cover model behavior, parser/writer fidelity, operation modules, the
Bibliography lifecycle, CLI JSON/exit contracts, and regression fixtures. The
critical tests are parse → edit → write → parse paths and staged bibliography
diffs: they guard preservation, not merely semantic field values.

Every behavioral change must add tests and update CHANGELOG.md. Before a change
is complete, run:

~~~bash
pytest
ruff check src tests
ruff format --check src tests
~~~

## Deliberate non-goals and future boundaries

The core does not own a database of record, GUI, cloud sync, PDF extraction,
arbitrary shell execution, or LLM API calls. An MCP server is similarly a
downstream transport concern: the CLI already provides a machine-readable, safe
agent interface.

The next structural extensions are planned in dependency order: optional Pinax
mode (one `Bibliography` + its `files-dir` of materials), `Library` (a directory
of pinakes/bibliographies with cross-file search and identity resolution), and
`Catalogue` (a derived, rebuildable index over the Library). None of these are
part of the current implementation — see
[DEVPLAN.md](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md) for the roadmap.

- [API reference](../api/index.md)
- [Usage guide](usage.md)
- [Philosophy](../vision.md) and [DEVPLAN](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md) for design and roadmap.
