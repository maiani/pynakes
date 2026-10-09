# Changelog

All notable changes to the pynakes VS Code extension are documented in this
file. Changes to the engine it runs are in the
[repository changelog](https://github.com/maiani/pynakes/blob/main/CHANGELOG.md).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The extension is versioned on its own, starting at 0.1.0: an odd minor version
marks a Marketplace pre-release, and an even one will mark the first stable
release. Its version says nothing about which engine it runs.

## [Unreleased] - 0.1.0

### Added

- `editor/`: a VS Code / Open VSX extension companion. It opens a `.bib` file
  as a sortable, filterable entry table with a field detail pane, browses the
  declared group hierarchy, runs the engine's own search, surfaces lint findings
  per entry, and stages field edits for review as an exact diff before commit.
  It flags duplicate citation keys, reports encoding, line ending, `@string`
  count, and which metadata namespaces the file carries, follows the text
  buffer rather than the file on disk, and jumps from a row to the entry's
  declaration in the source. The client holds no bibliography implementation
  of its own: every value it displays comes from the engine's JSON envelope,
  and every change goes through an engine command. It is not yet published to
  either marketplace, is excluded from the Python sdist and wheel, and has its
  own Node toolchain; see [README.md](README.md).
- The extension bundles the engine, so it needs a Python 3.12+ interpreter but
  no pynakes install. `npm run vendor-engine` builds the engine and its
  dependencies into `editor/engine/` (generated, git-ignored, shipped only
  inside the VSIX). Every runtime dependency is a pure-Python `py3-none-any`
  wheel, so one universal bundle covers every platform with no per-platform
  build and nothing to code-sign. An engine the user installed themselves is
  preferred when its version is strictly newer than the bundled one, so
  upgrading pynakes takes effect without an extension release. The interpreter
  is taken from the Python extension's selection, then a workspace virtual
  environment, then `PATH`; `pynakes.executable` still overrides everything,
  and `pynakes.engine` can force `bundled` or `installed`.
- `pixi.toml` at the repository root provides the toolchain the extension
  needs, Node plus a Python pinned to 3.12 (the floor of `requires-python`), so
  `pixi run build-extension` produces an installable
  `editor/pynakes-vscode-<version>.vsix` on a machine set up for neither.
  `install-extension`, `test-extension`, and `clean-extension` round out the
  set. This is additive: the pip workflow remains how the engine is developed.
- The view can change *which* entries exist, not only their fields.
  **Import…** resolves a DOI, arXiv id, ISBN, or supported URL into a new
  entry; **New entry** appends an empty entry of a chosen type and selects it
  so the field editor fills it in; an entry's detail pane removes it; its
  **Groups** chips add and remove membership (a name typed under "New group…"
  creates the group; picking an existing one never does); and **Duplicates**
  lists what `dedupe check` found, each cluster with the merge that resolves
  it. These are not staged, since none is a field edit, but they keep the
  staged editor's guarantee: the engine's own `--dry-run --diff` goes to the
  Staged diff pane, the approval dialog names what a diff cannot show
  (materials about to be deleted, a network request already made), and
  approving re-runs the identical invocation without `--dry-run`. An engine
  conflict is treated as the engine declining to guess rather than as a
  failure: an import of a reference already held asks whether to add it
  anyway and replays the answer, and a taken citation key says so and writes
  nothing.
- **Writes are guarded by the previewed digest.** A commit or an entry-level
  change carries the `source_sha256` its preview reported, so a change made
  while the approval dialog is open is refused rather than overwritten.
  Several staged entries are committed as one `corpus batch` (one write, all or
  nothing) instead of one `ref edit` per entry, and a conflict envelope is
  treated as not applied, keeping the staged edits, where it used to count as
  success and drop them.
- The detail pane has a "Compare with remote" action next to each of an
  entry's `doi` and `eprint` fields (both, when both are present). It fetches
  that identifier's DOI/arXiv record via the engine's `ref compare` and shows a
  three-column Local / Other / Merged table in a "Compare" panel tab, with
  word-level highlighting of the differing spans within each field. Clicking a
  Local or Other cell selects that value into the Merged column, which is also
  freely editable. The merged column defaults to the local value on a genuine
  conflict (never silently overwritten), or to the other side when the field is
  missing locally. Nothing is written automatically: "Apply merged" stages each
  field through the normal preview, diff, and commit flow.
- `pynakes.allowOnlineLookups` (on by default) gates every network-backed action
  in the view: comparing with a remote record and importing by identifier. With
  it off, those actions say lookups are disabled instead of failing at the
  provider.
- The view shows which entries the manuscript cites, and where. With
  `tex-sources` declared, entries nothing cites carry a `○` marker, and an
  **uncited** toggle narrows the table to them; an entry's **Cited at** list
  opens the `.tex` file at that `\cite`, positioned by the engine's
  per-occurrence line and column. Citations naming a key no entry declares are
  published as diagnostics on the `.tex` file that makes them, so an undefined
  citation appears in Problems where it was typed. All of it comes from the
  engine's `tex scan --json` citation index; the client scans nothing itself.
- Entries with linked files carry a `🗎` marker, and the detail pane lists each
  material by kind (published PDF, preprint, source, supplement, erratum for a
  Pinax store, plus any BibLaTeX `file`-field link), marking a missing or
  wrong-type link rather than hiding it. Clicking one opens it with the
  operating system's handler; a directory is revealed in the file manager.
  Every path comes from `asset check --json`: the client never constructs
  `<key><suffix>.pdf` itself, and opens a path only when the last read reported
  it. Both this and the citation index read the document's real path on disk
  rather than the temporary mirror used for an unsaved buffer, because
  `tex-sources`, `pinax-files-dir`, and relative `file` paths resolve from the
  `.bib`'s own directory. The cost, noted in the README, is that an unsaved edit
  to `tex-sources` or to a `file` field shows only once the file is saved.
- The view's findings are published as native VS Code diagnostics, so they
  appear in the Problems panel, and as squiggles in any text editor showing the
  same `.bib`, as well as in the view. Each diagnostic sits at the finding's
  entry declaration line, located by the engine's per-issue `line` field.
  `pynakes.showFindings` gates both presentations together, and a failed
  re-read (parse error, engine unavailable) clears the published set, so
  Problems never outlives what the view shows.
- The detail pane's citation key is editable: renaming it runs the engine's
  `keys rename`, which also rewrites matching `\cite{...}` keys in any linked
  TeX sources. It asks for confirmation first, since it can touch files beyond
  the `.bib`, and refuses if the entry has pending staged changes, since those
  are keyed by the old citation key.
- Every pane (the groups sidebar, the detail pane, and the bottom
  findings/diff panel) is resizable by dragging its border, the way table
  columns already were; each size is remembered per workspace. Icon buttons
  (undo or remove a field, collapse toggles, compare) are bigger, with a wider
  hit target and hover highlight.
- `editor/src/test/cliContract.test.ts` runs the real engine, not a mock,
  against a temporary `.bib`, checking argument order and envelope shapes for
  the commands the view calls, including `groups add-entry --create`. It needs
  a `python3` that can import this repository's `src/pynakes`, and skips itself
  with a clear reason otherwise, so `npm test` still works for editor-only
  contributors.

### Changed

- **The extension uses the 0.7 command surface.** `search`, `ref compare`,
  `ref add`, and `ref import` pass the library first; the view expects the
  actions `tex_scan`, `asset_check`, and `corpus_batch`; and lint counts are
  read from the envelope's `summary`.
- The view's panes (the entry editor, Findings, Staged diff, and Compare) can
  be moved between two docks: the right dock (where the editor normally sits)
  and the bottom dock (where findings and the diff live). A pane moves via the
  small arrow beside its tab, and a dock holding more than one pane shows a tab
  row. Each pane's location and the active tab per dock are remembered per
  workspace.
- `pynakes.search.fuzzy` and `pynakes.showFindings` are now honored. Both were
  declared but read by nothing: the fuzzy toggle now starts from the setting on
  first open (a toggle made in the view still persists over it), and the
  severity markers and the findings tab now disappear when findings are turned
  off. Setting changes reach an open view live.

### Fixed

- The view left an empty band below its panes. A hidden banner or notice takes
  no grid slot, so the panes slid up into a row sized to their content; each
  part of the view now keeps its own row and the panes fill the window.
- The view threw on its first render whenever a dock held any pane, so the
  right and bottom docks never appeared and editing was unreachable. Each pane
  tab was marked active after its fragment had been appended, when the fragment
  was already empty; only the active pane's tab is now marked, before appending.
  Webview smoke tests now load the real view in jsdom, drive it through the
  real engine, and fail on any error it raises.
- A locally built `.vsix` bundled engine modules since deleted from `src/`:
  setuptools reused a stale `build/` directory. Vendoring now clears it first.
- Engine warnings are shown by their message. The engine reports warnings as
  objects, and the view joined them as strings, which would have shown
  `[object Object]`.
- Sorting a column descending put blank values first: blanks were sorted last
  ascending and the whole order was then reversed, contradicting the rule that
  gaps never lead. Direction now lives inside the comparator.
- Engine discovery kept a single memoized resolution keyed on settings, so two
  open bibliographies in different workspace folders evicted each other's entry
  and re-probed (respawning version probes) on every read. Resolutions are
  cached per key instead.
- A pending entry-type change was never checked against the dry-run plan at
  commit time, unlike field edits, so a type changed elsewhere could be
  silently overwritten. The commit is now refused with the other conflicts.
- Staged changes are dropped when their document closes, where they previously
  lingered for the session.
- Closing one bibliography view no longer hides the status bar item while a
  sibling view is still active.
