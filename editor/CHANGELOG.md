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

### Changed

- Refresh inspection, groups, and lint through one engine invocation, reducing
  a saved bibliography refresh from six processes to three. Citation and material
  reads remain parallel and use the saved bibliography's location.

### Added

- Metadata values with finite choices use engine-supplied dropdowns, including
  dialect, journal and formatting settings, and Boolean options. Existing values
  are preserved until explicitly changed; free-form values retain a text area.

- A Metadata dock tab for adding, editing, and removing pynakes/JabRef metadata
  through engine validation and the existing diff-and-approval flow. Drafts
  survive switching tabs.
- A Materials tab for bibliography-wide fetching. The Duplicates tab now owns
  its scan button; the top bar keeps search/filter controls, Import, and New
  entry. Clicking a bottom tab also expands a collapsed dock.

- Multi-selection with Ctrl/Cmd-click, Shift-click, Shift+arrow keys, and
  Ctrl/Cmd+A. The selection can be added to or removed from a group, or deleted,
  through one combined preview and approval. Hidden rows leave the selection
  when filtering. Drag entries onto a group to add membership while preserving
  their other memberships; group changes use the engine's atomic batch operation.

- Configurable entry double-click action: `pynakes.doubleClickAction` defaults to
  `openPdf`, using the material viewer preference and offering a choice for
  multiple PDFs. Select `source` to restore the previous source-jump behavior.
  Entries without a local PDF show a notification.

- `editor/`: a VS Code / Open VSX extension companion. It opens a `.bib` file
  as a sortable, filterable entry table (blank values sort last in either
  direction) with a field detail pane, browses the declared group hierarchy,
  runs the engine's own search, surfaces lint findings per entry, and stages
  field edits for review as an exact diff before commit. It flags duplicate
  citation keys, reports encoding, line ending, `@string` count, and which
  metadata namespaces the file carries, follows the text buffer rather than the
  file on disk, and jumps from a row to the entry's declaration in the source.
  The client holds no bibliography implementation of its own: every value it
  displays comes from the engine's JSON envelope, and every change goes through
  an engine command. It is not yet published to either marketplace, is excluded
  from the Python sdist and wheel, and has its own Node toolchain; see
  [README.md](README.md).
- The view stays consistent with the document. Staged edits show in every view
  of the same file and are dropped when the document closes. Overlapping reads
  never render stale content, out-of-order search answers are ignored, nothing
  is posted to a closed view, and the temporary mirror of an unsaved buffer is
  removed even if writing it fails. A library with an entry keyed
  `constructor`, `toString` or `__proto__` opens like any other.
- The extension bundles the engine, so it needs a Python 3.12+ interpreter but
  no pynakes install. `npm run vendor-engine` builds the engine and its
  dependencies into `editor/engine/` (generated, git-ignored, shipped only
  inside the VSIX), clearing setuptools' `build/` first so a bundle never
  carries modules since deleted from `src/`. Every runtime dependency is a
  pure-Python `py3-none-any` wheel, so one universal bundle covers every
  platform with no per-platform build and nothing to code-sign. An engine the
  user installed themselves is preferred when its version is strictly newer
  than the bundled one, so upgrading pynakes takes effect without an extension
  release. The interpreter is taken from the Python extension's selection, then
  a workspace virtual environment, then `PATH`; `pynakes.executable` still
  overrides everything, and `pynakes.engine` can force `bundled` or
  `installed`. Discovery is cached per workspace folder and settings; an engine
  that was not found is looked for again on the next read and on Refresh.
- The status bar names the engine in use while a view is active. Its tooltip
  gives the file's details and why that engine was chosen; it is plain text,
  so a key in the file cannot render as a command link.
- `pixi.toml` at the repository root provides the toolchain the extension
  needs, Node plus a Python pinned to 3.12 (the floor of `requires-python`), so
  `pixi run build-extension` produces an installable
  `editor/pynakes-vscode-<version>.vsix` on a machine set up for neither.
  `install-extension`, `test-extension`, and `clean-extension` round out the
  set. This is additive: the pip workflow remains how the engine is developed.
  Local Python coverage and test-cache artifacts are excluded from the VSIX.
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
  approving re-runs the identical invocation without `--dry-run`. Any such
  change, duplicate merges included, is refused when the engine's preview
  shows it would rewrite or remove an entry with pending staged edits. An
  engine conflict is treated as the engine declining to guess rather than as a
  failure: an import of a reference already held asks whether to add it anyway
  and replays the answer, and a taken citation key says so and writes nothing.
  A failed write, rename, fetch, preview, search or compare is reported without
  blanking the table or clearing Problems.
- **Writes are guarded by the previewed digest.** A commit or an entry-level
  change carries the `source_sha256` its preview reported, so a change made
  while the approval dialog is open is refused rather than overwritten.
  Several staged entries are committed as one `corpus batch` (one write, all or
  nothing), and every staged field and entry-type change is checked against
  the dry run's current values, so a value changed elsewhere refuses the commit
  rather than being reverted. A conflict envelope is treated as not applied,
  keeping the staged edits.
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
  in the view: comparing with a remote record, importing by identifier, and
  fetching materials. With it off, those actions say lookups are disabled
  instead of failing at the provider.
- The view shows which entries the manuscript cites, and where. With
  `tex-sources` declared, entries nothing cites carry a `○` marker, and an
  **uncited** toggle narrows the table to them; an entry's **Cited at** list
  opens the `.tex` file at that `\cite`, positioned by the engine's
  per-occurrence line and column. Citations naming a key no entry declares are
  published as diagnostics on the `.tex` file that makes them, so an undefined
  citation appears in Problems where it was typed, and two open bibliographies
  citing from the same source do not overwrite each other's. All of it comes
  from the engine's `tex scan --json` citation index; the client scans nothing
  itself.
- Entries with linked files carry a `🗎` marker, and the detail pane's
  Materials section lists each material by kind (published PDF, preprint,
  source, supplement, erratum for a Pinax store, plus any BibLaTeX
  `file`-field link), marking a missing or wrong-type link rather than hiding
  it, and saying so when nothing is on disk. Materials open inside VS Code by
  default, beside the view, in whatever editor is associated with the file;
  opening there never runs the file. `pynakes.openMaterialsWith` (`"editor"` |
  `"system"`) chooses the operating system's default application instead, and
  each material offers the other choice as a secondary action or with
  Alt/Option-click. A PDF with no viewer installed still opens in VS Code, and
  a one-time notification offers to open it externally or to find a PDF viewer
  extension. A material directory is revealed in the Explorer when it lies in
  the workspace, and in the file manager otherwise. Every path comes from
  `asset check --json`: the client never constructs `<key><suffix>.pdf`
  itself, and opens a path only when the last read reported it present on
  disk. Both this and the citation index read the document's real path on disk
  rather than the temporary mirror used for an unsaved buffer, because
  `tex-sources`, `pinax-files-dir`, and relative `file` paths resolve from the
  `.bib`'s own directory. The cost, noted in the README, is that an unsaved edit
  to `tex-sources` or to a `file` field shows only once the file is saved.
- Missing materials can be fetched: **Fetch missing…** in an entry's detail
  pane, or **Fetch materials…** in the toolbar for every entry, using the
  library's fetch policy or one chosen material. The approval names each file
  the engine would write, where, and by which DOI or arXiv id, plus every entry
  left out with the engine's reason. The write is guarded by `--expect-sha256`,
  downloads run under a cancellable progress notification, and the Materials
  list re-reads afterwards; results say which hosts were tried and what they
  answered (HTTP status and content type). Cancelling, like any engine call
  timing out, stops
  every process the call started (the process group on Linux and macOS,
  `taskkill /T` on Windows), not only the launcher.
- The view's findings are published as native VS Code diagnostics, so they
  appear in the Problems panel, and as squiggles in any text editor showing the
  same `.bib`, as well as in the view. Each diagnostic sits at the finding's
  entry declaration line, located by the engine's per-issue `line` field.
  `pynakes.showFindings` gates both presentations together, the view's severity
  markers and findings tab included, and a failed re-read (parse error, engine
  unavailable) clears the published set, so Problems never outlives what the
  view shows. `pynakes.search.fuzzy` sets the fuzzy toggle's state on first
  open (a toggle made in the view persists over it), and setting changes reach
  an open view live.
- The detail pane's citation key is editable: renaming it runs the engine's
  `keys rename`, which also rewrites matching `\cite{...}` keys in any linked
  TeX sources, re-points any `crossref` naming the entry, and moves the key's
  Pinax material files. It goes through the same preview, Staged diff,
  approval and `--expect-sha256`-guarded write as other changes; the dialog
  names the TeX citations rewritten and the material files moved, and the
  rename is refused if the entry has pending staged changes, since those are
  keyed by the old citation key. The key field is released however the rename
  ends.
- Every pane (the groups sidebar, the detail pane, and the bottom
  findings/diff panel) is resizable by dragging its border, the way table
  columns already were; each size is remembered per workspace. Icon buttons
  (undo or remove a field, collapse toggles, compare) are bigger, with a wider
  hit target and hover highlight.
- `editor/src/test/cliContract.test.ts` runs the real engine, not a mock,
  against a temporary `.bib`, checking argument order and envelope shapes for
  the commands the view calls, including `groups add-entry --create`. Webview
  smoke tests load the real view in jsdom, drive it through the real engine,
  and fail on any error it raises. Both need a `python3` that can import this
  repository's `src/pynakes`, and skip themselves with a clear reason
  otherwise, so `npm test` still works for editor-only contributors.
- The groups sidebar edits the group hierarchy. **+** adds a top-level group,
  and each group's **⋯** button or context menu adds a subgroup, renames,
  moves, edits the description, or removes it. Each change runs the engine's
  `--dry-run --diff`, shows in the Staged diff pane, is approved, and is written
  guarded by `--expect-sha256`. Removing a group names every subgroup that goes
  with it, and a group that entries name but the hierarchy does not declare can
  be declared. Renaming a group moves its entries to the new name, and the
  approval names them. A group used as the sidebar filter stays selected when
  renamed; the filter returns to All entries when the group is removed. JabRef
  group colours paint each group's swatch.
- Group rows and duplicate-cluster keys are reachable by keyboard: Enter or
  Space filters by a group, and Shift+F10 opens its actions. Enter on any
  button activates only that button, never also opening the selected entry's
  source.

### Changed

- The client is labeled an alpha, and the manifest marks it as a preview.
  `npm run package:prerelease` produces a VSIX carrying the pre-release
  marker; with `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES` set, the bundled
  engine identifies itself as that release version.
- **The extension uses the 0.7 command surface.** `search`, `ref compare`,
  `ref add`, and `ref import` pass the library first; the view expects the
  actions `tex_scan`, `asset_check`, and `corpus_batch`; lint counts are read
  from the envelope's `summary`; and engine warnings, now objects, are shown by
  their message. Citation keys, group names and identifiers are passed after
  `--`, so one beginning with `-` is never read as an option.
- The view's panes (the entry editor, Findings, Staged diff, and Compare) can
  be moved between two docks: the right dock (where the editor normally sits)
  and the bottom dock (where findings and the diff live). A pane moves via the
  small arrow beside its tab, and a dock holding more than one pane shows a tab
  row. Each pane's location and the active tab per dock are remembered per
  workspace, and the panes fill the window below the toolbar.
