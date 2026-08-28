# Pynakes for VS Code

A graphical client for `.bib` files, built on the pynakes engine.

> **Status: early, and not published.** It browses a bibliography, searches it,
> shows its groups and validation findings, and can stage field edits for review
> before writing. Nothing about its UI or settings is settled.

## The one rule this client keeps

**It has no bibliography implementation of its own.** Every fact it displays
arrives from the engine's JSON envelope, and every change leaves through
`ref edit`. There is no BibTeX parser here, no metadata schema, no selector-
grammar evaluator, no cache, and no second source of truth — so the view and the
CLI cannot disagree about what an entry is, and a file the engine reads correctly
cannot be displayed wrongly by the client.

The consequence worth knowing: when this client needs something the engine cannot
express, the fix goes into the engine, not into TypeScript here. That rule is
recorded in [AGENTS.md](../AGENTS.md), and it has already been exercised — the
engine gained a predicate-only `search` (`pynakes search "" --where 'doi
missing'`) because the selector grammar had no read-only path, and the
alternative would have been evaluating predicates in the client.

`src/model.ts` is the only place that transforms engine output, and it only does
display tidying: collapsing wrapped whitespace, rendering the `and` name
separator as `; `, choosing which field fills the venue column. LaTeX markup is
shown exactly as stored.

## What it does today

**Browse.** A sortable entry table — type, citation key, author, title, year, and
the container the work appeared in — with duplicate citation keys flagged rather
than hidden, and a status column marking entries that have findings or pending
edits.

**Groups.** The declared hierarchy in a sidebar, with per-group counts; selecting
a group filters the table to it and its descendants. The hierarchy comes from the
file's metadata while membership comes from the entries themselves, and those two
can genuinely disagree — a group only the entries mention is shown, marked as not
declared, instead of being silently dropped.

**Search.** The engine's own search, not a local text filter, so a query means
the same thing here as on the command line. Words, phrases, and `field:term`
scoping; an optional `--where` predicate; an optional `--fuzzy` toggle. Results
keep the engine's relevance ranking unless you sort a column. Leaving the query
empty and giving only a predicate answers set questions such as
`year >= 2020 and doi missing`.

**Findings.** `lint` results as a severity marker per row and a panel grouped by
category; clicking a finding selects its entry. They are also published as
native diagnostics, so the same findings appear in VS Code's **Problems** panel
(and as squiggles in any text editor showing the file), each placed at its
entry's declaration line by the engine. Advisory only — the view never applies a
fix on its own. The `pynakes.showFindings` setting gates both views of the
findings at once; a failed re-read clears Problems along with the view rather
than leaving stale entries behind.

**Edit, review, then commit.** Fields are editable in the detail pane, along with
the entry type; fields can be added and removed. The panes are relocatable: Edit,
Findings, the staged diff, and Compare each live in either the right dock or the
bottom dock, moved by the arrow beside their tab, and stack as tabs when one dock
holds more than one. Nothing is written when you
type. Edits accumulate as pending changes, **Preview** shows the engine's exact
unified diff, and committing asks for explicit confirmation with that diff on
screen. Two properties matter:

- *The diff you approve is the diff that lands.* It is the engine's own diff from
  `ref edit --dry-run --diff`, never reconstructed here, and the commit reuses
  the same requests in the same order.
- *A commit cannot silently clobber a change made elsewhere.* Every pending edit
  remembers the value it was made against; the dry run reports what the file
  currently holds; if those disagree the commit is refused with nothing written,
  rather than reverting someone else's work.

Pending changes survive switching away from the tab, because they live in the
extension rather than in the webview.

**Follow the buffer, not the disk.** Editing the same file as text updates the
view, with unsaved text read through a temporary mirror. There is no refresh
button: the view reloads itself on document changes, saves, and setting changes.

**Committing follows your editor settings.** Writing needs the buffer and the
file to agree. When `files.autoSave` is on, the buffer is saved for you, because
that is what the editor would do moments later anyway. With autosave off, saving
is your decision, so it is asked for rather than assumed.

**Citations, and the sources that make them.** When the library declares
`tex-sources`, the engine's citation index says which entries the manuscript
actually cites. Entries nothing cites carry a `○` marker, and the **uncited**
toggle narrows the table to them — the "what can this bibliography drop"
question. An entry's **Cited at** list opens the `.tex` file at that `\cite`,
and citations naming a key no entry declares are published as diagnostics *on
the source file that makes them*, so an undefined citation appears where it was
typed. Nothing is guessed locally: every occurrence's file, line, and column
comes from `tex scan --json`.

**Materials.** Entries whose linked files exist carry a `🗎` marker, and the
detail pane lists them by kind — published PDF, preprint, source, supplement,
erratum for a Pinax store, plus any BibLaTeX `file`-field link — with a missing
or wrong-type link marked rather than hidden. Clicking one opens it with the
operating system's handler (a directory is revealed in the file manager
instead). The client never *builds* a material path: `<key><suffix>.pdf` is the
Pinax store's addressing scheme, and every path shown here came from
`asset check --json`.

These two reads are about the files *around* the bibliography, so they read the
`.bib` as saved, at its real location — `tex-sources`, `pinax-files-dir`, and a
relative `file` path all resolve from the `.bib`'s own directory, and the
temporary mirror used for an unsaved buffer has neither. The cost is that an
unsaved edit to a `file` field or to `tex-sources` is not reflected until you
save.

Not yet: adding and removing whole entries, group editing, and duplicate
merging.

## Scope: this client is project-scoped

The axis is **project-scoped vs library-scoped**, not single-file vs multi-file.

This extension is the GUI for a bibliography belonging to a document or repo you
are editing. That is imposed by the host, not chosen: a
`CustomTextEditorProvider` is handed exactly one `TextDocument` and VS Code owns
its lifecycle, which is also what makes the diff-before-commit flow above
possible.

**Bimas** (working name) is a planned separate standalone GUI for exploring a
generic, non-project-specific library. It is not a fallback for this extension
being too restrictive; it exists because it serves a scope this one structurally
cannot reach. Single-file versus multi-file is a frequent side effect of that
axis rather than its cause — a master library is often a single `.bib`, while
`tex ... scan` spans one `.bib` plus many `.tex` files. This client may still
*read* library-scoped things, such as comparing against a master library; it
never owns or curates them.

Until Bimas starts, the CLI and this extension are developed together in this
repository. A second client is the trigger for splitting anything out, so
`editor/` should not be extracted before then.

## Requirements

A Python 3.11 or newer interpreter. The engine itself ships with the extension,
so `pip install pynakes` is not required.

The interpreter is taken from the Python extension's selected environment, then a
workspace `.venv`/`venv`, then `PATH`.

## Which engine runs

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

## Using it

`.bib` files still open in the text editor by default — the view is opt-in:

- **Open with Pynakes** from the command palette, or
- right-click a `.bib` file in the explorer, or
- **Reopen Editor With… → Pynakes Bibliography**.

To make it the default for `.bib`:

```jsonc
{ "workbench.editorAssociations": { "*.bib": "pynakes.bibliography" } }
```

In the view: type to search, click a column header to sort, click a group to
filter, click a material or a citation to open it, `↑`/`↓` to move between entries, `Enter` or a double-click to open the
entry's declaration in the source text, `Ctrl`/`Cmd`+`F` to focus the search box.

## Developing

```bash
npm install
npm run compile        # tsc -> out/
npm run watch          # incremental
npm test               # node --test over the pure modules
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
pixi run test-extension     # compile and run the unit tests
pixi run clean-extension    # drop engine/, out/, and any .vsix
```

The packaged extension is written to **`editor/pynakes-vscode-<version>.vsix`**,
beside this README; `vsce` prints its absolute path when it finishes. Install it
by hand with `code --install-extension editor/pynakes-vscode-<version>.vsix`, or
let `pixi run install-extension` resolve the filename for you. Pixi pins Python
to 3.11 to match CI, so a bundle built locally is the bundle CI proves.

Tests cover the pure modules — `model.ts`, `insights.ts`, `staging.ts`,
`version.ts` — and nothing else. That is deliberate: those hold the logic worth
pinning, while the rest is thin glue whose behavior lives in VS Code and in the
engine. Do not grow a bibliography fixture corpus here; that belongs to the
engine's own suite.

### Layout

```
src/
  extension.ts           activation: registers the editor and commands
  bibliographyEditor.ts  the custom editor: buffer sync, staging, preview, commit
  library.ts             composes the engine reads; runs preview and commit
  pynakes.ts             the only module that spawns the engine
  engineDiscovery.ts     which engine to run, and why
  version.ts             PEP 440 parsing and comparison
  model.ts               engine envelope types + projection to table rows
  insights.ts            group-tree and lint projections
  staging.ts             pending edits, and the conflict check that guards a commit
  webview.ts             webview HTML shell, CSP, resource URIs
scripts/
  vendor-engine.mjs      builds the bundled engine
media/                   webview client: state, table, groups, detail, panels, main
```

The view is a `CustomTextEditorProvider` rather than a standalone webview so VS
Code keeps ownership of the document: the text buffer stays authoritative,
external edits arrive as change events, and the extension holds no file state
beyond pending edits.

Reads run concurrently (`inspect`, `groups tree`, `groups list`, `lint` are
independent reads of an unchanging file) while writes run strictly sequentially,
because each `ref edit` rewrites the whole file atomically and concurrent writes
would race.

## Packaging

`npm run package` produces a `.vsix` installable with
`code --install-extension`. It is not published: the `pynakes` publisher
namespace is not claimed on the Marketplace or Open VSX, and the extension should
not be published while it is this incomplete.
