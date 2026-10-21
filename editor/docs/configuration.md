# Editor configuration

[Editor overview](../README.md) · [User guide](usage.md) · [Configuration](configuration.md) · [Architecture](architecture.md) · [Development](development.md)

Set these options in VS Code’s Settings UI (search for **Pynakes**) or in `settings.json`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `pynakes.executable` | `""` | Override engine discovery with a command or interpreter. |
| `pynakes.executableArgs` | `[]` | Arguments before each subcommand; use `["-m", "pynakes"]` with a Python interpreter. |
| `pynakes.engine` | `"auto"` | Choose `auto`, `bundled`, or `installed` (see engine discovery below). |
| `pynakes.search.fuzzy` | `false` | Initial fuzzy-search setting; the view can toggle it per search. |
| `pynakes.showFindings` | `true` | Show findings in the view and VS Code Problems. |
| `pynakes.openMaterialsWith` | `"editor"` | Open materials in `editor` or with the `system` application. |
| `pynakes.allowOnlineLookups` | `true` | Allow remote comparisons, imports, and material fetching. |
| `pynakes.doubleClickAction` | `"openPdf"` | Open a PDF (`openPdf`) or jump to the declaration (`source`). |
| `pynakes.citationCommand` | `"cite"` | Macro for a new citation inserted into a TeX file (`citep`, `autocite`, …); it must be one the engine counts. |
| `pynakes.citationCompletion` | `true` | Complete keys inside `\cite{…}` in TeX files from the open bibliographies; turn off if another extension already does. |

## Which engine runs

The bundled engine needs Python 3.12 or newer. The interpreter is taken from
the Python extension’s selected environment, then a workspace `.venv`/`venv`,
then `PATH`.

In precedence order:

1. `pynakes.executable`, when non-empty — never overridden, no probing.
2. `pynakes.engine`, when it forces `bundled` or `installed`.
3. Otherwise both are probed and the **installed** engine is used only if it is
   *strictly newer* than the bundled one. A version tie keeps the bundle.
4. If no interpreter can run the bundle, the installed engine is used even when
   it is older.
5. Neither available — an error explaining what to configure.

So upgrading pynakes yourself takes effect without waiting for an extension
release. VS Code's status bar names the engine in use while a bibliography view
is active; hover it for the file's details — entry and finding counts, duplicate
keys, metadata namespaces, encoding and line endings — and the reason a
particular engine was chosen. Clicking it re-reads the file. This is deliberately
*not* a row inside the view: it is ambient information that is rarely read, and
the view's vertical space is better spent on entries.

Two settings cover the escape hatches:

```jsonc
{
  // Bypass discovery entirely. Pair with executableArgs for an interpreter.
  "pynakes.executable": "/path/to/.venv/bin/python",
  "pynakes.executableArgs": ["-m", "pynakes"]
}
```

When developing the engine in this repo, note that a same-version tie keeps the
*bundled* engine, so source changes will not appear in the view until you either
re-run `npm run vendor-engine` or set `pynakes.engine` to `installed` against an
editable install.

See the [user guide](usage.md) for PDF viewers, keyboard controls, and metadata editing. Bibliography metadata is stored in the `.bib`; it is separate from these VS Code settings.
