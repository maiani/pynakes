# pynakes as a bib-file engine

A design sketch for the library-level API that turns pynakes into a reusable
**bib-file engine** — the deterministic kernel used by the CLI and available to
other in-process consumers such as a daemon or stateful application.

Status: `Collection` is implemented for one `.bib` file. It exposes read-only views,
delegated operation methods, staged previews/diffs, atomic commits, reset/reload,
and external-modification detection. `Library` remains future work; filesystem
watching is intentionally *not* in core (a consumer concern — see the
external-change section). See [VISION.md](VISION.md) for the why and
[ARCHITECTURE.md](ARCHITECTURE.md) for the design pynakes already follows.

## State model: thin reconciled handle over a file-derived buffer

The decision behind the lifecycle below — driven by invariant #6 (the file is
the single source of truth) and #7 (determinism):

- **Rendering and diffing are derived from explicit snapshots.** `Collection`
  retains pristine text and entry snapshots, then derives preview text and a
  diff from its staged library. The implementation keeps this logic private to
  the facade, but tests exercise it through `preview()` and `diff()`.
- **`Collection` is a thin stateful *handle*** bundling `{path, lib,
  pristine_snapshot, fingerprint, is_dirty}`. Its in-memory state is a **derived
  buffer over the file** — never an authoritative model. `commit()` always
  reconciles with the live file.
- **Litmus test for any state:** *if I delete it and re-read from disk, do I lose
  anything?* No → safe derived buffer. Yes → a second source of truth; not
  allowed.

The same object serves both consumer shapes: the CLI uses it transactionally
(`open → op → commit`); a GUI or downstream application may hold it open across
edits. In both cases the buffer stays derived and `commit()` reconciles.

## Vocabulary

The system has three nested units (entry ⊂ collection ⊂ library):

- **Entry** — one bib record (the existing `BibEntry`).
- **Collection** — one `.bib` file (a single πίναξ): the load → edit → preview →
  commit lifecycle for that file.
- **Library** — the collection: a directory / git repo of collections. This is the
  *Pinakes* — your catalog. (The tool, `pynakes`, is the librarian; the
  `Library` is what it tends.)

## Goal

Make the `.bib` file the single source of truth and expose one in-process API
that owns the lifecycle, including the surgical minimal-diff splice and the
atomic, re-parse-validated write that currently live inside `cli.py`. Any
consumer should get those guarantees for free.

## Non-goals (what the engine never owns)

- No database of record. The file is canonical; consumers may keep a **derived,
  rebuildable** cache/index, nothing else.
- No persistent state between runs, no sync, no UI. Those belong to the consumer
  (CLI, app, server); git provides history and sync.
- No new transformation logic. The engine is a *facade*: it delegates to the
  existing pure operation modules (`groups`, `fields`, `keys`, `convert`,
  `journals`, `normalize`, `lint`, `doi`) and adds only lifecycle orchestration.

## Layering

```
operation modules        functions on BibFile (mutate in place,
(groups, fields, ...)     return a count/report) — already exist, unit-tested
        │
        ▼
Collection (engine.py)        binds one file: parse, stage edits, diff, commit,
                          external-change detection — implemented boundary
        │
        ▼
Library (planned)         a git repo of collections: search, identity/dedup across
                          files, locate-key, inbox→canonical→projection
        │
   ┌────┼─────────┬───────────────┐
   ▼    ▼         ▼               ▼
  CLI       daemon/server   parallel app   (thin consumers; all share
                                           the same contract)
```

The CLI is rewritten as a Collection consumer. That rewrite is the proof the
boundary is correct: if `cli.py` reduces to "open → call op → diff/commit", a
parallel project can do the same.

## The Collection API (one file)

```python
from pynakes.engine import Collection

# Bind a file. Parses it and captures the source text plus a fingerprint
# (size, mtime, and content hash) for change detection.
coll = Collection.open("refs.bib")               # raises FileNotFoundError / ParseError

# --- read-only views (no staging) ---------------------------------------
coll.entries                                  # EntryStore (duplicate-tolerant)
coll.lint()                                   # -> list[Issue]
coll.duplicate_keys()                         # -> dict[str, int]
coll.is_dirty                                 # any staged edits since open/commit?

# --- staged edits (mutate in memory; nothing is written) -----------------
# Each operation returns its existing count or domain report; the cumulative
# staged diff is read from the collection, not an individual operation.
coll.rename_field("journal", "journaltitle", where=None)
coll.add_to_group("Smith2020", "Economics")
coll.convert("biblatex")
coll.normalize(options)
coll.import_doi("10.5555/x", key_source="generated")   # append, not splice

# --- preview ------------------------------------------------------------
coll.diff()                                   # unified diff of ALL staged edits vs disk
coll.preview()                                # the would-be file text

# --- commit / discard ---------------------------------------------------
result = coll.commit()                        # atomic write + .bak + re-parse validate
coll.reset()                                  # drop staged edits, back to disk state
coll.reload()                                 # re-read from disk (raises if dirty,
                                             # unless reload(force=True))
```

### Staging & commit model

This generalizes the CLI's existing `snapshot → op → commit`:

1. `Collection.open` captures the pristine on-disk text and a per-entry snapshot of
   `raw_content` (keyed by entry identity).
2. Operations mutate the in-memory `BibFile` through `editing.py`, exactly as
   today — only changed fields' `raw_content` differ from the snapshot.
3. `diff()` / `preview()` / `commit()` are *derived*: each changed entry yields a
   `(pristine_block, current_block)` edit; `editing.splice_into_text` patches the
   pristine file text so untouched formatting (blank lines, comments, field
   order) survives byte-for-byte. If a block can't be located, fall back to
   `write_bib`. Appends (DOI import) and metadata comment edits are handled
   explicitly.
4. `commit()` writes via `io.save_text` (temp file → re-parse validate → `.bak`
   → atomic rename), then refreshes the pristine snapshot + fingerprint.

A GUI maps this directly: staged edits ↔ an editable view, `diff()` ↔ a preview
pane, `commit()` ↔ Save, `reset()` ↔ Discard. Many ops, one commit.

### External-change detection — the VSCode model (the concurrency story)

Three actors edit the same file: the app, the user's text editor, and an agent.
The behavior follows VSCode exactly — the file is truth, the buffer is derived,
and an external change reconciles like an editor reloading a changed file:

- **Clean buffer + file changes on disk → reload instantly.** Nothing is staged,
  so the buffer just mirrors the new disk content (this is the "edit a file
  outside and see it update live" behavior).
- **Dirty buffer + file changes on disk → conflict, never silent clobber.** The
  consumer is notified and chooses: keep mine, take theirs, or compare. The
  engine does not auto-resolve.
- **`commit()` while disk changed since open → `ExternalModificationError`**
  (unless forced), so a save can't overwrite an external edit blindly.

The engine exposes the *primitives* that make this possible; the live-update UX
lives in the consumer (BiMaS):

- `fingerprint` / `externally_changed()` — cheap "did disk change?" check (poll).
- `reload(force=False)` — re-read from disk; seamless when clean, raises when
  dirty so the consumer decides.
- `is_dirty` — are there staged edits since open/commit?

These pull primitives are sufficient: a consumer's own event loop calls
`externally_changed()` and, if `not is_dirty`, `reload()` for an instant update
(else surfaces a conflict). **Decided: no `watch(callback)` in pynakes core** — a
filesystem watcher is a background thread (non-deterministic, dependency-bearing,
and a UX concern), so the *push* loop is the consumer's job. If a push helper
ever earns its place it ships as an **opt-in extra** (`pynakes[watch]`), built
when BiMaS needs it — never required by core.

This (the pull primitives) is the piece bare functions can't provide and every
stateful consumer needs.

## The Library API (the collection)

A `Library` is a directory / git repo of collections — the Pinakes. It adds the
cross-file operations a single collection can't express. **This API is a future
design sketch, not an implemented importable class:**

```python
from pynakes.engine import Library

lib = Library.open("~/research/refs")        # a directory / git repo of .bib files

lib.collections()                                # -> list[Collection]
lib.collection("topics/ml.bib")                  # open one collection in the collection
lib.search("attention transformer 2017")     # global query (via the derived index)
lib.find_key("Vaswani2017")                  # -> which collections contain it
lib.duplicates()                             # cross-file identity/dedup candidates
lib.promote(entry, to="canonical/ml.bib")    # inbox → canonical, or → a projection
lib.reindex()                                # rebuild the derived search index
```

- **Identity** is by stable id (DOI / arXiv / OpenAlex) so the same work in two
  collections is recognized as one; dedup *reports* conflicts rather than guessing.
- **The index is a derived cache** (e.g. SQLite FTS), rebuildable from the
  collections at any time — never a competing source of truth.
- **Projections** (per-project bibfiles) are views derived from the canonical
  collections; `pynakes used --out` is today's primitive for this.

## Transport sugar (all wrap the same engine)

- **CLI**: `_finish_mod` becomes `coll.<op>(...)` + `coll.commit()`; the JSON
  envelope is a serialization of `Change`/`SaveResult`.
- **Downstream adapters**: a server or tool wrapper can use
  `open → op → (dry_run ? diff() : commit())`. It remains outside the core;
  the CLI is the supported machine-facing interface today.
- **Daemon/server**: holds open collections/libraries to avoid re-parsing on every
  call for a chatty frontend; same API, just long-lived.

## What a parallel project builds against

The parallel project owns state + UX (capture, PDF, search index, sync, GUI) and
treats `lib`/`coll.entries` as its derived, rebuildable view. It never persists a
competing source of truth. In return it inherits, for free, the property no
from-scratch manager has: **every edit is surgical, validated, atomic, and
non-corrupting.**

## Migration steps

1. [x] Add `engine.py` with `Collection`, lifting `_snapshot`/`_commit` orchestration out
   of `cli.py` (delegating to the existing operation modules — no new transform
   logic).
2. [x] Add fingerprint + `ExternalModificationError`.
3. [x] Rewrite `cli.py` commands as Collection consumers (dogfood; the test suite is the
   regression guard).
4. [x] Add `reload()`; optional `watch()` remains deferred.
5. [ ] Add `Library` (collection over a git repo of collections) + a derived index.
6. [ ] Document and pin the broader public API contract after `Library` lands.
