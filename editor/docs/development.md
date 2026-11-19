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
to 3.12 to match CI, for dependency resolution; native runtime selection is checked separately in CI.

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
  extension.ts           stable activation entry point
  core/                  shared projections, reads, edit sessions, fetch plans, HTML shell
  engine/                Node CLI transport, arguments, and executable contract
  vscode/                document ownership, dialogs, navigation, discovery, diagnostics
  test/                  shared UI, engine contracts and host integration checks
ui/                      shared browser scripts, styles and default theme
media/                   VS Code messaging and theme adapters, extension icon
scripts/
  vendor-engine.mjs      staged engine build and isolated smoke test
  bundle_runtime.py      downloads the supported native wheel variants
  pynakes_launcher.py    offline wheel selection and isolated entry point
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

Bibliography refreshes use one `inspect --display --insights --json` call: one
process and one parse for entries, groups, lint, citations (`tex_scan`), and
material state (`asset_check`). A buffer with unsaved changes is read through a
mirror, so the call passes `--origin` with the document's saved path and the
engine resolves `tex-sources`, `pinax-files-dir`, and relative `file` links from
there. This requires an engine supporting both (included in the bundled
engine).

Writes run sequentially because each rewrites the file atomically. A staged
commit is one `batch` write, however many entries it covers.

## Packaging

Use `npm run package:prerelease` for the 0.1.0 alpha. It sets the VSIX's
prerelease marker and runs the same vendoring/compilation steps as `package`.
When the engine is ready for the coordinated release, set
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYNAKES` to the intended release version
for the package command; do not reuse an earlier release number. Local RC bundles
are validation artifacts. The extension keeps its own
0.1.0 version. See [the release checklist](../../RELEASE.md).

The VSIX is not published: the `pynakes` publisher namespace must be verified
before publication on the Marketplace or Open VSX. The alpha has no UI/settings
compatibility promise; its engine consumes the beta JSON envelope.


The field editor also reads `ref schema`; its digest must match `inspect` before
rendering. New entries use `ref add --no-interactive` rather than creating and
renaming a placeholder. Rebuild the bundled engine after changes to these
contracts; testing against a different installed engine is not equivalent.

### Native runtime support

One VSIX contains shared pure Python dependencies and 16 Pydantic Core wheels:
standard CPython 3.12–3.15 for Linux x64/glibc, macOS x64, macOS ARM64 and
Windows x64. Wheel tags select both the ABI and platform, including macOS/glibc
minimum versions. Free-threaded Python, PyPy, musl Linux and other architectures
are not bundled; use a separately installed engine there. There is no runtime
download or pip install.

The build uses `pip download --only-binary` for every target and fails if a
variant is missing or another unclassified native dependency appears. It also
includes Windows' conditional Colorama dependency when built on another OS.
The launcher uses `-I -S` to exclude ambient packages and `PYTHONPATH`. A failed
build leaves the previous bundle intact. `engine/native.json` records the exact
wheels shipped. Packaging tests run with
`python -m unittest discover -s scripts -p 'test_bundle_*.py'` (requires packaging).

Run the packaged launcher with `--version` and `inspect <fixture> --json` on
each supported OS/Python combination before release. Cross-downloading a wheel
is not proof that it executes on that target.
