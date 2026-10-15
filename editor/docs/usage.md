# Using the bibliography editor

[Editor overview](../README.md) · [User guide](usage.md) · [Configuration](configuration.md) · [Architecture](architecture.md) · [Development](development.md)

## Open a bibliography

`.bib` files still open in the text editor by default — the view is opt-in:

- **Open with Pynakes** from the command palette, or
- right-click a `.bib` file in the explorer, or
- **Reopen Editor With… → Pynakes Bibliography**.

To make it the default for `.bib`:

```jsonc
{ "workbench.editorAssociations": { "*.bib": "pynakes.bibliography" } }
```

## Navigation and selection

In the view: type to search, click a column header to sort, click a group to
filter, click a material or a citation to open it (`Alt`-click a material to
open it the other way, see [Materials](#materials)), `↑`/`↓` to move between
entries, `Enter` to open the entry's declaration in the source
text, double-click to open a local PDF, `Ctrl`/`Cmd`+`F` to focus the search box.

Set `pynakes.doubleClickAction` to `source` to make double-click open the source
declaration instead (the previous behavior). The default, `openPdf`, follows
`pynakes.openMaterialsWith` and offers a choice when several PDFs are available.
If no local PDF is available, a notification says so.

Select multiple entries with Ctrl/Cmd-click, or use Shift-click / Shift+↑/↓
for a range. Ctrl/Cmd+A selects the visible entries when not editing text.
The detail pane then offers **Add to group**, **Remove from group**, and
**Remove entries** for the selection. Each change uses one combined diff and
approval; removing entries also removes their Pinax materials, as the approval
explains. Filtering clears hidden entries from the selection.

Drag an entry or the current selection onto a group to add that membership,
keeping other group memberships. This also goes through diff review and approval.

Everything clickable is reachable with `Tab` and shows a focus ring. A group row
filters on `Enter` or `Space` and opens its actions on `Shift`+`F10` (or the
context-menu key); a key in a duplicate cluster, a finding, a material or a
citation is a button, so `Enter` activates it rather than opening the selected
entry's source.

## Toolbar and dock tabs

The top bar holds search/filter controls and the two entry-creation actions,
**Import…** and **New entry**. Bibliography-wide work lives in the bottom tabs:
scan and merge in **Duplicates**, fetch in **Materials**, and edit library
settings in **Metadata**. These tabs can be moved to the right dock as usual.

## Edit bibliography metadata

In **Metadata**, select a pynakes or JabRef block to edit its value, or choose
**New metadata** to add one. Finite, single-valued settings use dropdowns from
the engine's choice registry; lists, numbers, and free-form values use text areas. **Review change…** and **Remove block…** use the
engine's validation, diff preview, and approval before writing. Drafts survive
tab switches; they are separate from staged entry-field edits. Unknown JabRef
keys require explicitly enabling the corresponding checkbox. Use the Groups
sidebar for convenient group hierarchy edits.

## Browse

A sortable entry table — type, citation key, author, title, year, and
the container the work appeared in — with duplicate citation keys flagged rather
than hidden, and a status column marking entries that have findings or pending
edits.

## Groups

The declared hierarchy in a sidebar, with per-group counts; selecting
a group filters the table to it and its descendants. The hierarchy comes from the
file's metadata while membership comes from the entries themselves, and those two
can genuinely disagree — a group only the entries mention is shown, marked as not
declared, instead of being silently dropped.

## Search

The engine's own search, not a local text filter, so a query means
the same thing here as on the command line. Words, phrases, and `field:term`
scoping; an optional `--where` predicate; an optional `--fuzzy` toggle. Results
keep the engine's relevance ranking unless you sort a column. Leaving the query
empty and giving only a predicate answers set questions such as
`year >= 2020 and doi missing`.

## Findings

`lint` results as a severity marker per row and a panel grouped by
category; clicking a finding selects its entry. They are also published as
native diagnostics, so the same findings appear in VS Code's **Problems** panel
(and as squiggles in any text editor showing the file), each placed at its
entry's declaration line by the engine. Advisory only — the view never applies a
fix on its own. The `pynakes.showFindings` setting gates both views of the
findings at once; a failed re-read clears Problems along with the view rather
than leaving stale entries behind.

## Edit, review, then commit

Fields are editable in the detail pane, along with
the entry type; fields can be added and removed. The panes are relocatable: Edit,
Findings, the staged diff, Compare, Duplicates, Materials, and Metadata each live in either the right
dock or the bottom dock, moved by the arrow beside their tab, and stack as tabs
when one dock holds more than one. Nothing is written when you type. Edits
accumulate as pending changes, **Preview** shows the engine's exact unified diff,
and committing asks for explicit confirmation with that diff on screen. Three
properties matter:

- *The diff you approve is the diff that lands.* Every pending entry goes into
  one `corpus batch`; its diff is the engine's own, from `--dry-run --diff`,
  never reconstructed here, and the commit reruns the same operations in the
  same order.
- *A commit lands whole or not at all.* The batch is one write, so a commit that
  cannot apply one entry applies none, and every pending edit stays pending.
- *A commit cannot silently clobber a change made elsewhere.* Every pending edit
  remembers the value it was made against; the dry run reports what the file
  currently holds; if those disagree the commit is refused with nothing written,
  rather than reverting someone else's work. And the commit carries the file
  digest the dry run reported (`--expect-sha256`), so a change made while the
  approval dialog is open is refused by the engine too, rather than overwritten.

Pending changes survive switching away from the tab, because they live in the
extension rather than in the webview.

## Follow the buffer, not the disk

Editing the same file as text updates the
view, with unsaved text read through a temporary mirror. There is no refresh
button: the view reloads itself on document changes, saves, and setting changes.

## Committing follows your editor settings

Writing needs the buffer and the
file to agree. When `files.autoSave` is on, the buffer is saved for you, because
that is what the editor would do moments later anyway. With autosave off, saving
is your decision, so it is asked for rather than assumed.

## Citations, and the sources that make them

When the library declares
`tex-sources`, the engine's citation index says which entries the manuscript
actually cites. Entries nothing cites carry a `○` marker, and the **uncited**
toggle narrows the table to them — the "what can this bibliography drop"
question. An entry's **Cited at** list opens the `.tex` file at that `\cite`,
and citations naming a key no entry declares are published as diagnostics *on
the source file that makes them*, so an undefined citation appears where it was
typed. Nothing is guessed locally: every occurrence's file, line, and column
comes from the engine's `tex scan` report.

## Add, remove, group, merge

The toolbar's **Import…** resolves a DOI, arXiv
id, ISBN or supported URL into a new entry; **New entry** adds an empty one of a
chosen type and selects it so the field editor can fill it in. The **Duplicates**
tab contains **Find duplicates**, which lists the clusters `dedupe check` finds, each with the merge that resolves it.
An entry's detail pane removes it, and its **Groups** chips add and remove
membership. Every one of these goes through the same path: the engine's own
`--dry-run --diff` lands in the Staged diff pane, the approval dialog names what
the diff cannot show — materials that would be deleted, a network request that
was made — and approving re-runs the identical invocation without `--dry-run`,
conditional on the file still being the one the preview read. Nothing here is
staged, because none of it is a field edit; what it shares with the field editor
is that the diff you approve is the diff that lands. None of it may rewrite an
entry that still has pending field edits: the engine's preview names every entry
a change would remove, modify or re-key — including every cluster a whole-file
**Merge every duplicate** reaches, and a pair's surviving entry when the merge
fills it in — and the change is refused, with nothing written, if any of them
has pending edits.

## Rename a citation key

Editing the key at the top of the detail pane is
`keys rename`, through the same preview, approval and guarded write. It reaches
further than the `.bib`: the engine also rewrites matching `\cite{...}` keys in
the linked TeX sources, re-points any `crossref` naming the entry, and moves the
key's Pinax material files. The Staged diff pane shows the `.bib` and every
rewritten source; the approval dialog says how many citations change in which
source, and lists each material file that would change name, since no diff
shows that. A key already taken is the engine's conflict, reported with nothing
written. A rename is refused while the entry — or an entry whose `crossref`
follows it — has pending field edits, because those are keyed by the old key.

A conflict is the engine declining to guess rather than a failure — and never a
success: whatever answered with one wrote nothing, and is reported as such.
Importing a reference the library already holds asks whether to add it anyway
and replays the answer; a citation key already taken says so and writes
nothing; a file that changed while the approval dialog was open says so, writes
nothing, and re-reads the file.

## Materials

Entries whose linked files exist carry a `🗎` marker, and the
detail pane lists them by kind — published PDF, preprint, source, supplement,
erratum for a Pinax store, plus any BibLaTeX `file`-field link — with a missing
or wrong-type link marked rather than hidden. Clicking one opens it inside VS
Code, beside the view, in whatever editor is associated with the file — a PDF
viewer extension, the built-in image preview, the text editor — and opening it
there never runs it. Each row also offers **Open externally**, which hands the
file to the operating system's default application instead, and `Alt`-click
(`Option`-click) on the material does the same. The `pynakes.openMaterialsWith`
setting swaps the two: with `"system"`, a click opens externally and the row
offers **Open in Code**.

```jsonc
{ "pynakes.openMaterialsWith": "editor" } // default; or "system"
```

VS Code has no PDF viewer of its own. Without a viewer extension a PDF still
opens in VS Code, to its binary-file placeholder, and a notification — once per
format per session, never blocking — offers to open it externally, to always
open materials externally (setting `"system"`), or to search for a PDF viewer.
Whether a viewer exists is read from the installed extensions' custom editors
and `workbench.editorAssociations`. A directory is never opened: it is revealed
in the Explorer when it lies inside the workspace and the choice is VS Code,
and in the system file manager otherwise. Only materials the engine found on
disk can be opened. The client never *builds* a material path:
`<key><suffix>.pdf` is the Pinax store's addressing scheme, and every path shown
here came from `asset check --json`.

**Fetch missing…** in the entry’s Materials section downloads what the entry lacks, and the
**Materials** tab's **Fetch missing materials…** does it for every entry; either asks first which
materials — the library's `pinax-fetch-policy`, or one of the engine's own
`--material` choices. This is `asset fetch`, through the same preview, approval
and guarded write as everything above, with one difference in what the dialog
has to say: a fetch's real work is files beside the `.bib` and requests to the
network, which no diff of the `.bib` shows. So the engine's dry run — which
makes no request and creates nothing — names each file a real run would
request, the DOI or arXiv id it would be requested by, and the path it would
land at, and the approval lists exactly those, along with every entry left out
and the engine's reason (no identifier, already present). An entry with nothing
to fetch says why instead of asking. The `.bib` changes only when the library
has no Pinax store yet, and then the diff shows the `pinax-files-dir` it
records. Downloads run under a cancellable progress notification; every
material lands atomically, so stopping one keeps what finished and leaves
nothing half-written. A provider that cannot supply a file is a skip with its
reason, not an error, and the Materials list re-reads when the fetch ends. Like
Import, fetching honors `pynakes.allowOnlineLookups`: with lookups off it says
so rather than failing at the provider.

The citation and material reads, and the fetch, are about the files *around* the bibliography,
so they use the `.bib` as saved, at its real location — `tex-sources`,
`pinax-files-dir`, and a relative `file` path all resolve from the `.bib`'s own
directory, and the temporary mirror used for an unsaved buffer has neither. A
fetch may write, so an unsaved buffer is saved first, under the same
autosave-or-ask rule a commit follows. For the reads, the cost is that an
unsaved edit to a `file` field or to `tex-sources` is not reflected until you
save.

## Edit the group hierarchy

The groups sidebar edits the hierarchy itself,
which is a different thing from an entry's membership of a group: **+** in its
heading adds a top-level group, and each group's **⋯** button (or its context
menu) offers adding a subgroup, renaming, moving under another group or to the
top level, editing the description, and removing. These are the engine's
`groups add-group`, `rename-group`, `move-group`, `update-group` and
`remove-group`, through the same preview, approval and guarded write as
everything above. The client knows none of the tree's rules: a name already
taken is the engine's conflict, a move under the group's own descendant is the
engine's refusal, and when a group is removed the approval dialog names every
subgroup that goes with it, as the engine reported them. A rename carries the
group's members along (`rename-group --members`): every entry filed under exactly
the old name is moved to the new one, the approval dialog says how many and
which, as the engine's preview named them, and a sidebar filter on the group
follows it. Removing a node leaves entries' memberships as they were, and the
dialog says so — an entry still filed under a removed group shows it as a group
the hierarchy does not declare, which that group's **⋯** offers to declare
again.
