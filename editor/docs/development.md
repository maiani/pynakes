# Developing and packaging the editor

[Editor overview](../README.md) · [User guide](usage.md) · [Configuration](configuration.md) · [Architecture](architecture.md) · [Development](development.md)

Run the npm commands below from `editor/`; run the Pixi commands from the repository root.

## Setup and checks

```bash
npm install
npm run compile        # tsc -> out/
npm run watch          # incremental
npm test               # node --test over out/test, the real engine included
npm run vendor-engine  # build the bundled engine into engine/ (git-ignored)
npm run package        # .vsix, vendoring and compiling first
```

Press `F5` to launch an extension development host. This works both with this
directory open as the workspace root and with the repository root open — the
root carries its own `.vscode/launch.json` pointing at `editor/`.

`npm run package` needs no preparation: `vsce` runs the `vscode:prepublish`
script, which vendors the engine and compiles before packaging, so a VSIX can
never ship a stale or missing bundle. `npm run package:clean` removes the
vendored tree first when you want to prove a build from nothing.

If you would rather not set up Node and a suitable Python yourself, the
repository root carries a [pixi](https://pixi.sh) manifest that provides both:

```bash
pixi run build-extension    # -> editor/pynakes-vscode-<version>.vsix
pixi run install-extension  # builds, then installs it into VS Code
pixi run test-extension     # compile and run the tests, engine included
pixi run clean-extension    # drop engine/, out/, and any .vsix
```

The packaged extension is written to **`editor/pynakes-vscode-<version>.vsix`**,
in the editor directory; `vsce` prints its absolute path when it finishes. Install it
by hand with `code --install-extension editor/pynakes-vscode-<version>.vsix`, or
let `pixi run install-extension` resolve the filename for you. Pixi pins Python
to 3.12 to match CI, so a bundle built locally is the bundle CI proves.

Most tests pin the pure modules (`model.ts`, `insights.ts`, `staging.ts`,
`version.ts`, the material-opening decision). The rest run the real engine from
this repository's `src/` against temporary `.bib` files: argument order and
envelope shapes (`cliContract`, `operandContract`, `fetchContract`), the write
path with only the dialogs stood in (`mutationFlow`), and the real webview
scripts in jsdom (`webview`). Those skip with a reason when `python3` cannot
import pynakes, and `PYNAKES_REQUIRE_ENGINE=1` — set in CI — turns the skip
into a failure. `src/test/engine.ts` holds the shared engine command and
temp-file helpers. Do not grow a bibliography fixture corpus here; that belongs
to the engine's own suite.

### Layout

```
src/
  extension.ts           activation: registers the editor and commands
  bibliographyEditor.ts  the custom editor: buffer sync, reads, message routing
  documentAccess.ts      mirror, working directory, settings, buffer reconciliation
  stagedCommit.ts        previews and commits the staged field edits
  keyRename.ts           renames one citation key, as a previewed mutation
  mutations.ts           entry-level changes: preview, approve, guarded write
  groupHierarchy.ts      sidebar prompts for editing the group hierarchy
  materialFetch.ts       fetching materials: plan, approve, cancellable run
  fetchPlan.ts           the asset fetch envelope, and what the dialogs say about it
  navigation.ts          opens sources, citations, and materials
  materialOpener.ts      where a material opens: in VS Code or with the system
  diagnostics.ts         findings and undefined citations as native diagnostics
  statusBar.ts           the engine/file status bar item
  library.ts             composes the engine reads; runs preview and commit
  pynakes.ts             builds every engine invocation
  engineProcess.ts       the only module that spawns the engine; stops whole trees
  engineDiscovery.ts     which engine to run, and why
  version.ts             PEP 440 parsing and comparison
  model.ts               engine envelope types + projection to table rows
  insights.ts            group-tree and lint projections
  staging.ts             pending edits, and the conflict check that guards a commit
  records.ts             own-property lookups for maps keyed by the file's text
  webview.ts             webview HTML shell, CSP, resource URIs
scripts/
  vendor-engine.mjs      builds the bundled engine
media/                   webview client: state, table, groups, detail, compare,
                         duplicates, libraryPanels, panels, layout, main
```

The view is a `CustomTextEditorProvider` rather than a standalone webview so VS
Code keeps ownership of the document: the text buffer stays authoritative,
external edits arrive as change events, and the extension holds no file state
beyond pending edits.

A call that is cancelled or runs past its time limit is stopped along with
every process it started — the engine is often reached through a launcher whose
Python child does the work. On Linux and macOS the engine runs as the leader of
its own process group and the whole group is signalled; on Windows `taskkill
/T /F` stops the tree.

Bibliography refreshes use `inspect --display --insights --json` to share one
engine snapshot for entries, groups, and lint. This requires an engine supporting
`--insights` (included in the bundled engine). Citation and material checks run
separately against the saved bibliography, including when the editor has unsaved
changes.

Writes run sequentially because each rewrites the file atomically. A staged
commit is one `corpus batch` write, however many entries it covers.

## Packaging

Use `npm run package:prerelease` for the 0.1.0 alpha. It sets the VSIX's
prerelease marker and runs the same vendoring/compilation steps as `package`.
When the engine is ready for the coordinated release, set
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES=0.7.0` for the package command
so the bundle identifies itself as the final Beta version. Local RC bundles
are validation artifacts. The extension keeps its own
0.1.0 version. See [the release checklist](../../RELEASE.md).

The VSIX is not published: the `pynakes` publisher namespace must be verified
before publication on the Marketplace or Open VSX. The alpha has no UI/settings
compatibility promise; its engine consumes the beta JSON envelope.
