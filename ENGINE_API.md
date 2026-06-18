# pynakes as a bib-file engine

A design sketch for the library-level API that turns pynakes into a reusable
**bib-file engine** — the deterministic kernel that the CLI, an MCP server, a
daemon, or a parallel stateful application all build on.

Status: `Volume` is implemented for one `.bib` file. It exposes read-only views,
delegated operation methods, staged previews/diffs, atomic commits, reset/reload,
and external-modification detection. `Library` remains future work; filesystem
watching is intentionally *not* in core (a consumer concern — see the
external-change section). See [VISION.md](VISION.md) for the why and
[ARCHITECTURE.md](ARCHITECTURE.md) for the design pynakes already follows.

## State model (decided): stateless core + thin reconciled handle

The decision behind the lifecycle below — driven by invariant #6 (the file is
the single source of truth) and #7 (determinism):

- **The commit/diff machinery is a pure, stateless function.** Given
  `(original_text, edited_lib, pristine_snapshot)` it returns
  `(new_text, diff, result)`. No hidden state; trivially testable; this is the
  load-bearing logic.
- **`Volume` is a thin stateful *handle*** bundling `{path, lib,
  pristine_snapshot, fingerprint, is_dirty}`. Its in-memory state is a **derived
  buffer over the file** — never an authoritative model. `commit()` always
  reconciles with the live file.
- **Litmus test for any state:** *if I delete it and re-read from disk, do I lose
  anything?* No → safe derived buffer. Yes → a second source of truth; not
  allowed.

The same object serves both consumer shapes: the CLI/MCP use it transactionally
(`open → op → commit`, effectively stateless); a GUI/BiMaS holds it open across
edits (stateful), but the buffer stays derived and `commit()` reconciles.

## Vocabulary

The system has three nested units (entry ⊂ volume ⊂ library):

- **Entry** — one bib record (the existing `BibEntry`).
- **Volume** — one `.bib` file (a single πίναξ): the load → edit → preview →
  commit lifecycle for that file.
- **Library** — the collection: a directory / git repo of volumes. This is the
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
operation modules        pure functions on BibLibrary (mutate in place,
(groups, fields, ...)     return a count/report) — already exist, unit-tested
        │
        ▼
Volume (engine.py)        binds one file: parse, stage edits, diff, commit,
                          external-change detection — NEW, the boundary
        │
        ▼
Library (engine.py)       a git repo of volumes: search, identity/dedup across
                          files, locate-key, inbox→canonical→projection — NEW
        │
   ┌────┼─────────┬───────────────┐
   ▼    ▼         ▼               ▼
  CLI  MCP     daemon/server   parallel app   (thin consumers; all share
                                               the same contract)
```

The CLI is rewritten as a Volume consumer. That rewrite is the proof the
boundary is correct: if `cli.py` reduces to "open → call op → diff/commit", a
parallel project can do the same.

## The Volume API (one file)

```python
from pynakes.engine import Volume

# Bind a file. Parses it, remembers the original bytes + a fingerprint
# (size+mtime, falling back to a content hash) for change detection.
vol = Volume.open("refs.bib")               # raises FileNotFoundError / ParseError

# --- read-only views (no staging) ---------------------------------------
vol.entries                                  # EntryCollection (duplicate-tolerant)
vol.lint()                                   # -> list[Issue]
vol.duplicate_keys()                         # -> dict[str, int]
vol.is_dirty                                 # any staged edits since open/commit?

# --- staged edits (mutate in memory; nothing is written) -----------------
# Each returns a Change: affected-entry count + warnings; the cumulative diff
# is read from the volume, not the individual call.
vol.rename_field("journal", "journaltitle", where=None)
vol.add_to_group("Smith2020", "Economics")
vol.convert(to="biblatex")
vol.normalize(options)
vol.import_doi("10.5555/x", key_source="generated")   # append, not splice

# --- preview ------------------------------------------------------------
vol.diff()                                   # unified diff of ALL staged edits vs disk
vol.preview()                                # the would-be file text

# --- commit / discard ---------------------------------------------------
result = vol.commit()                        # atomic write + .bak + re-parse validate
vol.reset()                                  # drop staged edits, back to disk state
vol.reload()                                 # re-read from disk (raises if dirty,
                                             # unless reload(force=True))
```

### Staging & commit model

This generalizes the CLI's existing `snapshot → op → commit`:

1. `Volume.open` captures the pristine on-disk text and a per-entry snapshot of
   `raw_content` (keyed by entry identity).
2. Operations mutate the in-memory `BibLibrary` through `editing.py`, exactly as
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

A `Library` is a directory / git repo of volumes — the Pinakes. It adds the
cross-file operations a single volume can't express:

```python
from pynakes.engine import Library

lib = Library.open("~/research/refs")        # a directory / git repo of .bib files

lib.volumes()                                # -> list[Volume]
lib.volume("topics/ml.bib")                  # open one volume in the collection
lib.search("attention transformer 2017")     # global query (via the derived index)
lib.find_key("Vaswani2017")                  # -> which volumes contain it
lib.duplicates()                             # cross-file identity/dedup candidates
lib.promote(entry, to="canonical/ml.bib")    # inbox → canonical, or → a projection
lib.reindex()                                # rebuild the derived search index
```

- **Identity** is by stable id (DOI / arXiv / OpenAlex) so the same work in two
  volumes is recognized as one; dedup *reports* conflicts rather than guessing.
- **The index is a derived cache** (e.g. SQLite FTS), rebuildable from the
  volumes at any time — never a competing source of truth.
- **Projections** (per-project bibfiles) are views derived from the canonical
  volumes; `pynakes used --out` is today's primitive for this.

## Transport sugar (all wrap the same engine)

- **CLI**: `_finish_mod` becomes `vol.<op>(...)` + `vol.commit()`; the JSON
  envelope is a serialization of `Change`/`SaveResult`.
- **MCP**: each tool is `open → op → (dry_run ? diff() : commit())`. Dry-run is
  the default; write requires explicit opt-in — same safety posture as the CLI.
- **Daemon/server**: holds open volumes/libraries to avoid re-parsing on every
  call for a chatty frontend; same API, just long-lived.

## What a parallel project builds against

The parallel project owns state + UX (capture, PDF, search index, sync, GUI) and
treats `lib`/`vol.entries` as its derived, rebuildable view. It never persists a
competing source of truth. In return it inherits, for free, the property no
from-scratch manager has: **every edit is surgical, validated, atomic, and
non-corrupting.**

## Migration steps

1. [x] Add `engine.py` with `Volume`, lifting `_snapshot`/`_commit` orchestration out
   of `cli.py` (delegating to the existing operation modules — no new transform
   logic).
2. [x] Add fingerprint + `ExternalModificationError`.
3. [x] Rewrite `cli.py` commands as Volume consumers (dogfood; the test suite is the
   regression guard).
4. [x] Add `reload()`; optional `watch()` remains deferred.
5. [ ] Add `Library` (collection over a git repo of volumes) + a derived index.
6. [ ] Document and pin the broader public API contract after `Library` lands.
