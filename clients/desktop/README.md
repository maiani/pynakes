# Pynakes desktop

An initial Electron application for editing local BibTeX/BibLaTeX bibliographies
outside VS Code. It uses the **same renderer, engine client, staged edit session,
and mutation review logic** as the extension. Electron supplies windows, file
selection, dialogs, clipboard access and external-file refresh.

## Run from this checkout

Requires Node 22.12+ and a compatible pynakes engine:

```sh
python -m pip install -e .
npm ci --prefix clients/desktop
npm start --prefix clients/desktop -- /absolute/path/references.bib
```

Without a filename, the app opens a file picker. Use File → New bibliography to
create an empty file, or File → Open to open another bibliography in its own
window. The application never downloads or installs an engine at startup.

Engine discovery prefers `PYNAKES_EXECUTABLE` when set, otherwise the packaged
engine (or `clients/vscode/engine` in a development checkout), then `pynakes` on PATH.
For a bundled engine, `PYNAKES_PYTHON` selects the interpreter; otherwise
`python3` and `python` are tried. The current bundle supports CPython 3.12–3.15
on Linux glibc x64, macOS x64/arm64 and Windows x64.

## First version

- Shared reference table, alternating row backgrounds, detail fields, groups,
  metadata, search, lint findings and citation/material lists.
- Stage field/type edits, preview the exact diff, approve and apply with the
  engine's source fingerprint. External changes refresh the view and stale
  writes are refused. Pending edits prevent accidental window closure.
- Add/import/rename/remove entries, edit groups and metadata, compare remote
  records, find duplicates and export selected references through the engine.
- Copy citation commands and open linked materials with the system application.

This is a local bibliography editor, **not yet the planned Library/Catalogue
manager**. Apply or discard field edits before entry/group mutations. Citation
commands are copied to the clipboard rather than inserted into another editor.
Material downloading is hidden until desktop progress/cancellation is supported.
There is no native undo history; review changes before applying. Linux is tested
locally; macOS and Windows installers, signing and auto-update are future work.

## Checks and packaging

```sh
npm test --prefix clients/desktop
npm run smoke --prefix clients/desktop
npm run package --prefix clients/desktop
```

Tests need a Python interpreter with this checkout's engine dependencies;
`PYNAKES_TEST_PYTHON` overrides `python3`. The smoke test launches a real Electron
window against temporary data, exercises the isolated renderer bridge, edits and
external refresh, and writes a screenshot to the system temporary directory
(`PYNAKES_SMOKE_SCREENSHOT` overrides the path). Linux CI runs it under Xvfb.

Packaging vendors the engine through `clients/vscode/scripts/vendor-engine.mjs`, then
creates an unpacked platform application under `clients/desktop/dist/`. Set
`PYNAKES_VENDOR_PYTHON` if needed. The app includes the engine and its dependency
variants, **but still requires a supported Python interpreter**. It does not
need a separately installed pynakes package. Packaging requires network access
for the Electron runtime and Python wheels. This is a development build, not a
signed installer or published release.

## Boundaries

`src/main.ts` owns Electron APIs and validates IPC origin. The sandboxed preload
exposes only the `PynakesHost` messaging/state bridge; the renderer has no Node
access. A local secure protocol serves allowlisted assets with the shared CSP.
`src/controller.ts` adapts desktop services to `packages/client-core` and the engine.
Bibliography parsing, metadata definitions and all writes remain in Python.
A replacement host can retain the renderer and engine contract.
