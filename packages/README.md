# Shared graphical client packages

Both `clients/vscode` and `clients/desktop` consume these internal source
packages. They are private and are not published to npm or included in the
Python distribution. Each host builds the sources into its own artifact using
its existing toolchain; no root npm installation or monorepo build service is
required.

- **client-core/src** owns projections, staging, edit sessions, mutation review
  and the host message contract. Its **engine/** directory implements the Node
  CLI transport. It does not discover host settings or import host APIs.
- **client-ui/src/shell.ts** produces the host-independent HTML shell.
  **client-ui/assets/** contains browser scripts, CSS and the default theme.
  The UI communicates only through `window.PynakesHost`.

The VS Code and Electron adapters own document/file lifecycle, dialogs,
clipboard, navigation, engine discovery and their messaging bridges. The Python
engine remains authoritative for bibliography behavior and all writes.

After shared changes, run both clients' checks from the repository root:

```sh
npm test --prefix clients/vscode
npm test --prefix clients/desktop
npm run smoke --prefix clients/desktop
```

Install each host's dependencies with `npm ci --prefix clients/<host>` first.
Engine-backed tests require the Python development environment. The VS Code
suite also checks that shared sources do not import VS Code or Electron.
