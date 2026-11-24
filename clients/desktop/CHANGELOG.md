# Changelog

## Unreleased — 0.1.0

- Organize hosts under `clients/vscode` and `clients/desktop`, with shared
  application and UI sources in `packages/client-core` and `packages/client-ui`.


- Add an Electron host for the shared bibliography editor, with local file
  windows, staged edits, guarded writes, native approval dialogs, group and
  metadata changes, reference import/export and external-file refresh.
- Share the renderer, edit session and mutation review text with VS Code.
- Package the existing isolated Python engine bundle alongside the desktop host.
  A supported Python interpreter remains required.
