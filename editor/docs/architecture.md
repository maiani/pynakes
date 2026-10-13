# Editor architecture

[Editor overview](../README.md) · [User guide](usage.md) · [Configuration](configuration.md) · [Architecture](architecture.md) · [Development](development.md)

## Engine boundary

**It has no bibliography implementation of its own.** Every fact it displays
arrives from the engine's JSON envelope, and every change leaves through one of
the engine's own modifying commands. There is no BibTeX parser here, no metadata
schema, no selector-grammar evaluator, and no separate bibliography database —
so bibliography behavior is shared with the CLI. The client still needs tests
for its presentation and interaction behavior.

The consequence worth knowing: when this client needs something the engine cannot
express, the fix goes into the engine, not into TypeScript here. That rule is
recorded in [AGENTS.md](../../AGENTS.md), and it has already been exercised:

- a predicate-only `search` (`pynakes search "" --where 'doi missing'`), because
  the selector grammar had no read-only path, and the alternative was evaluating
  predicates in the client;
- `dedupe merge --key`, for reviewing one duplicate pair at a time, because the
  alternative — deciding in TypeScript which entries to fold together — is the
  merge algorithm itself;
- `--expect-sha256` and the `source_sha256` it takes back, to guard a commit
  against a change made during its approval, rather than the client hashing the
  file itself;
- `removed_groups` on `groups remove-group`, `rename-group --members` with its
  `members_renamed`, and `pinax_materials` on `keys rename`, so the approval
  dialogs name the subgroups, entries and material files a change takes along
  instead of the client walking the tree or working out which
  `<key>.<kind>.pdf` files would change name;
- the `planned` list on an `asset fetch` dry run, so the approval can name each
  file a fetch would write — which also exposed that a dry run created the files
  directory it was only planning to fill.

Envelope bugs surfaced the same way and were fixed in the engine: `ref remove
--diff` emitted its warnings in the `diff` field and dropped them from
`warnings`; `ref add` reported a taken citation key as an exit-1 error while
`ref import` reported the identical situation as an exit-2 conflict with
options; and `corpus batch`'s `ref.edit` neither trimmed values nor checked
field names the way `ref edit` does, so the batch operation was fixed rather
than the values trimmed here.

The engine supplies display values through `inspect --display`: cleaned titles
and split name lists are separate from the raw fields used for editing.
`src/model.ts` and `src/insights.ts` project engine output into table rows,
group trees, and findings; they do not implement bibliography semantics.

## Project scope

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
