# LLM & automation integration

This guide describes how an LLM or automation workflow should drive the
`pynakes` CLI: the command surface, the safe edit workflow, exit codes, and the
structured JSON contract. It is written for a program (or an agent) that calls
`pynakes` as a tool.

> Working *on* the pynakes codebase instead of using it? See `AGENTS.md` at the
> repository root.

## Why pynakes is automation-friendly

- **Deterministic by default.** The same local input produces the same output.
  Network access is limited to explicit online workflows: `ref import`,
  `asset fetch`, `ref import --fetch`, `verify --online`, and `enrich --online`.
- **Preview before writing.** Every modifying command supports `--dry-run`.
- **Structured output.** `--json` returns a documented envelope (see below).
- **Conflicts return options, not guesses.** Blocked operations exit `2` with a
  list of resolutions.
- **Safe writes.** Modifications are atomic (temp file → re-parse validation →
  rename), and edits are surgical so unmodified entries stay byte-for-byte
  identical. Pass `--backup` to also keep a `<file>.bak` copy (off by default).

## Capabilities introspection

`pynakes capabilities --json` is self-describing: an agent can read it and
construct valid calls without trial and error. Beyond the operation list and
exit-code semantics, it includes:

```bash
pynakes capabilities --json
```

- `command_schemas` — a map keyed by full command path (e.g. `"groups add-entry"`,
  `"split"`) to that command's `help`, positional `arguments`, and `options`.
  Each parameter carries a stable `type` (`string`, `boolean`, `path`,
  `list[string]`, …), its `flags` (for options), `required`, `default`, and
  `help`. Derived from the live CLI, so it never drifts from the real surface.
- `error_codes` — every `error` (exit 1) and `conflict` (exit 2) code the JSON
  envelope can carry, with a one-line meaning, so you can branch on failures.
- `predicate_grammar` — the operators and special predicates accepted by
  `fields --where` and `corpus split --to`.

## Command surface

Read-only:

- `pynakes inspect [file] [--json]`
- `pynakes search <query> [file] [--field ...] [--where ...] [--no-rank] [--json]`
- `pynakes lint [file...] [--strict] [--json]`
- `pynakes groups list [file] [--json]`
- `pynakes keys check [file...] [--strict] [--json]`
- `pynakes metadata list [file] [--json]`
- `pynakes asset check [file...] [--root ...] [--strict] [--json]`
- `pynakes dedupe check [file...] [--strict] [--json]`
- `pynakes verify [file...] [--online] [--published] [--strict] [--json]` —
  `--published` also reports preprint/published identity links, including
  DOI-backed entries that can be linked to arXiv through provider metadata
- `pynakes capabilities [--json]`

The five gate checks (`lint`, `keys check`, `asset check`, `dedupe check`,
`verify`) accept multiple `.bib` files and support `--strict` to exit `1` on a
finding — the primitives for CI and pre-commit gating. See
[Git Workflows](git-workflows.md). A single file keeps its per-file JSON
envelope; multiple files emit an aggregate `{status, action, strict, files,
summary}` envelope.

`lint` and `keys check` validate the bibliography itself. To check whether TeX
sources cite missing or unused bibliography entries, run `tex scan` with the
`.bib` file and the `.tex` / `.aux` sources; that is a separate read-only
citation usage check.

Modifying (all support `--dry-run`, `--diff`, `--json`):

- `pynakes groups add-entry [file] <key> <group>`
- `pynakes groups remove-entry [file] <key> <group>`
- `pynakes groups tree [file]` — display the hierarchical group tree
- `pynakes groups add-group [file] <name> [--parent ...] [--color ...]`
- `pynakes groups remove-group [file] <name>` — removes group and its children
- `pynakes groups rename-group [file] <old> <new>`
- `pynakes groups move-group [file] <name> <new-parent>` (empty string = root)
- `pynakes groups update-group [file] <name> [--color ...] [--context ...] [--parent ...] [--expanded/--collapsed] [--description ...]`
- `pynakes keys generate <old-key> [file]` — regenerate one key using the
  preferred pattern (`AuthorYearTitle` by default); linked `tex-sources`
  citations are updated when configured. Use `--all` to regenerate every key.
- `pynakes keys repair [file]` — make duplicate keys unique
- `pynakes keys rename [file] <old> <new> <tex-source>...` — rename one key in
  the `.bib` file and matching TeX citation commands
- `pynakes fields rename [file] <old> <new> [--where ...]`
- `pynakes fields move [file] <old> <new> [--where ...]`
- `pynakes fields append [file] <field> <value> [--where ...]`
- `pynakes fields clear [file] <field> [--where ...]`
- `pynakes fields protect-title [file] [--field ...] [--term ...] [--where ...]`
- `pynakes ref add <key> [file] --field name=value ... [--type ...]` — add a manually specified entry
- `pynakes ref import <identifier> [file] [--key ...] [--key-source generated|provider] [--allow-duplicate] [--fetch] [--cache-dir DIR]` — `<identifier>` is a DOI, DOI URL, arXiv id, or arXiv URL
- `pynakes asset fetch [key] [file] [--preprint] [--published] [--source] [--bestpdf] [--cache-dir DIR]` — download configured
  Pinax materials: arXiv PDF/source and, with a suitable `fetch-policy`,
  open-access published PDFs for DOI-backed entries. Per-invocation flags
  override the metadata `fetch-policy`; pass none to use metadata. Human
  runs render download progress on stderr; `--json` stdout remains
  machine-readable JSON only.
- `pynakes metadata set [file] <key> <value> [--allow-unknown]`
- `pynakes metadata adopt-jabref [file]` — start maintaining a JabRef metadata
  projection for a pynakes-native library (mirrors JabRef-native settings into
  `jabref-meta` and keeps them in sync from then on)
- `pynakes normalize [file] [--keys on|off]` — includes journal abbreviation/expansion when
  `--journal-style abbreviated|full` or matching metadata is set; `--keys on`
  regenerates citation keys from the configured pattern (opt-in; Pinax material
  files are renamed consistently)
- `pynakes convert [file] --to biblatex|bibtex`
- `pynakes dedupe merge [file]` — conservatively merge duplicate-work clusters
- `pynakes enrich [file] [--online] [--published]` — conservatively fill missing
  metadata; `--published` also promotes preprints to their published version and
  backfills arXiv ids for DOI-backed entries when OpenAlex or Semantic Scholar
  exposes one
- `pynakes tex scan [bib-file] [source...] [--out ...] [--group ...] [--keyword ...]`

Maintenance write (supports `--json`, but not `--dry-run` / `--diff`):

- `pynakes asset check [file...] --fix [--backup]` — reconcile Pinax manifest
  drift. `--backup` keeps the previous manifest as `manifest.json.bak`.

Creating / projecting — **create** new files (support `--dry-run`, `--diff`,
`--json`):

- `pynakes init <file> [--type biblatex|bibtex] [--key-pattern ...] [--from <file>] [--force] [--backup]`
  — create a new library seeded with a metadata profile (a sensible default, or
  one copied from `--from`). Refuses to overwrite an existing file without
  `--force`; emits `FileExists` (exit `1`) otherwise. `--backup` keeps the
  overwritten file as `<file>.bak`.
- `pynakes corpus combine <file>... --out <file> [--dedupe]` — union several `.bib`
  files into one. `--dedupe` collapses identical same-key entries and reports a
  conflict (exit `2`) when same-key entries differ.
- `pynakes corpus split <file>... --to <FILE>='<predicate>'... [--copy] [--tex ...]
  [--aux ...] [--dedupe] [--minimal]` — combine inputs in memory and route
  entries into several outputs. Each `--to` pairs an output file with a
  predicate: a [`--where`](#the-where-filter) expression, or one of `*`, `used`
  / `unused` (against `--tex`/`--aux`), or `group "Name"`. First match wins by
  default; `--copy` routes an entry to every matching output. By default each
  output also carries the source library's `jabref-meta`/`pynakes-meta` blocks
  (groups, save-order config, Pinax fetch settings) and copies any linked
  Pinax materials, since a bucket is usually still a working library; pass
  `--minimal` when a bucket is a standalone snippet instead (e.g. one entry
  pulled out to hand to a collaborator) — it drops those metadata blocks
  entirely and skips materials copying. There is no dedicated single-entry
  export command yet; `split` with one `--to key == "..."` rule and
  `--minimal` is the way to pull one reference out cleanly.

Transactional:

- `pynakes corpus batch [file] --ops '<json>' | --ops-file <path>` — apply a sequence
  of operations to one file atomically (one preview, one commit; nothing is
  written if any operation fails). The operation vocabulary (op name → required/
  optional params) is in `capabilities` under `batch_operations`. Example:
  `--ops '[{"op":"groups.add_entry","key":"Smith2020","group":"ML"},{"op":"normalize","journal_style":"abbreviated"}]'`.

Planned (not implemented): `entries`.

## The `--where` filter

The `fields` subcommands accept a `--where` expression to restrict which
entries are touched. The grammar is a single condition:

```
FIELD contains "text"      # case-insensitive substring match on the field value
FIELD == "value"           # case-insensitive exact match (FIELD = "value" also works)
FIELD exists               # the field is present on the entry
```

`FIELD` is any field name (`title`, `author`, `journal`, …) plus two special
names: `type` matches the entry type (`article`, `book`, …) and `key` matches
the citation key. Quote values containing spaces. Examples:

```bash
pynakes fields append refs.bib keywords ml --where 'type == "article"'
pynakes fields clear  refs.bib abstract  --where 'key == "Smith2020"'
pynakes fields rename refs.bib url doi    --where 'doi exists'
```

Targeting `key == "..."` is the way to edit one specific entry — including the
manual resolution `dedupe merge` suggests for an ambiguous duplicate-work
cluster.

## Search

`search` is read-only and returns matching entries without touching the file:

```bash
pynakes search learning refs.bib
pynakes search 'title:"natural language" type:article' refs.bib --json
pynakes search widgets refs.bib --field title --where 'year = 2024' --json
```

Search terms are whitespace-separated and ANDed. Quoted phrases stay together.
`field:term` scopes a term to one field; `key:` and `type:` target citation keys
and entry types. Plain terms search the key, type, and stored fields.

Each match reports which field(s) it matched on — `matched_fields` in JSON, or
a bracketed `[field, ...]` tag in human output — e.g. `key`, `type`, `title`,
`author`, `groups`, `abstract`, or any other stored field name.

By default, matches are ranked by relevance: the strongest matched field
wins, in the order `key` > `title` > `author` > other stored fields >
`groups`/`abstract` (weak signals, since a group or abstract mention doesn't
mean the term is central to the entry). Ties keep file order. Pass `--no-rank`
to get plain file order instead, e.g. when diffing output against a prior run.

## Recommended workflow

1. **Inspect first.** Understand the file before editing.

   ```bash
   pynakes inspect refs.bib --json
   pynakes lint refs.bib --json
   ```

2. **Dry-run, then apply.** Preview with `--dry-run --diff --json`, then re-run
   the same command without `--dry-run` once the diff is acceptable.

   ```bash
   pynakes normalize refs.bib --dry-run --diff --json
   pynakes normalize refs.bib --json
   ```

3. **Prefer small, composed operations** over one big step — e.g. normalize
   formatting, then repair keys, then add groups.

For a full local validation pass over a bibliography and linked TeX source, use
the checks in this order:

```bash
pynakes inspect refs.bib --json
pynakes lint refs.bib --json
pynakes keys check refs.bib --json
pynakes dedupe check refs.bib --json
pynakes tex scan refs.bib paper.tex --json
pynakes asset check refs.bib --json
pynakes verify refs.bib --json
```

Only add `verify --online` when provider lookups are intentionally allowed.

## Common tasks

### Normalize a bibliography

```bash
pynakes normalize refs.bib --dry-run --diff --json
pynakes normalize refs.bib --json
```

`normalize` can protect title capitalization, normalize author/editor lists,
normalize DOI values, and abbreviate or expand journal titles when a journal
style is configured. It honors project metadata overrides via `jabref-meta`
comments and CLI options.

### Import or add a reference

```bash
pynakes ref import 10.1145/3377811.3380368 refs.bib --dry-run --diff --json
pynakes ref import 10.1145/3377811.3380368 refs.bib --json
pynakes ref import arXiv:2301.00001 refs.bib --json
pynakes ref import arXiv:2301.00001 refs.bib --fetch --json
pynakes ref add Manual2026 refs.bib --field title="Manual Reference" --field year=2026 --json
```

`import` performs DOI/arXiv metadata lookup and is network-backed. `add` is
local and manual: it appends exactly the key, entry type, and fields you supply.
If an `import --dry-run` lookup fails, the command reports that no changes were
written before returning the provider/network error.

Citation-key priority:

- `--key` wins when supplied.
- `--key-source provider` keeps the provider's key when one is available.
- `--key-source generated` (default) generates a key locally, using JabRef
  citation-key metadata when present.
- `import --fetch` downloads configured Pinax materials for the new key after
  the import succeeds, using the same fetch policy as `asset fetch`.

### Repair duplicate keys

```bash
pynakes keys check refs.bib --json
pynakes keys repair refs.bib --dry-run --diff --json
pynakes keys repair refs.bib --json
```

### Rename one key across BibTeX and TeX

```bash
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/ --dry-run --diff --json
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/ --json
```

`keys rename` exits `2` if the target key already exists or the source key is
duplicated, so an agent should report the conflict options instead of guessing.

### Inspect or update JabRef metadata

```bash
pynakes metadata list refs.bib --json
pynakes metadata set refs.bib databaseType biblatex --dry-run --diff --json
pynakes metadata set refs.bib databaseType biblatex --json
```

`metadata set` rejects unknown keys unless `--allow-unknown` is passed. If
duplicate matching metadata blocks are present, it exits `2` with a conflict
instead of choosing one.

Routing is file-context-aware: a JabRef-native key (e.g. `databaseType`) is
written to `jabref-meta` only when the file is already *JabRef-tracked* (carries
`jabref-meta` blocks); otherwise it, like every pynakes-owned key, stays in
`pynakes-meta`. To make a pynakes-native library track JabRef from then on, run
`pynakes metadata adopt-jabref <file>` — it relocates any JabRef-native keys into
`jabref-meta` and anchors a `databaseType`. Its envelope adds `moved_keys`,
`database_type_added`, and `was_tracked`; re-running once tracked is a no-op.

See the [JabRef compatibility guide](jabref-compatibility.md) for the full
namespace/owner model and the native `dialect`/`sort-order` keys that alias
`databaseType`/`saveOrderConfig`.

### Add entries to a group

```bash
pynakes groups list refs.bib --json
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff --json
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --json
```

### Classify a newly imported entry into the best group

pynakes has no built-in classifier — deliberately, to keep core operations
offline and deterministic (see [Architecture](architecture.md)). "Automatic"
grouping on import is instead a pattern for the calling agent: read the entry
and the candidate groups, judge the best fit, then apply it with `add-entry`.

```bash
pynakes ref import 10.1145/3377811.3380368 refs.bib --json   # 1. import, note the new key
pynakes inspect refs.bib --json                              # 2. read the new entry's fields
pynakes groups tree refs.bib --json                          # 3. read group names + descriptions
pynakes groups add-entry refs.bib <NewKey> "<Chosen Group>" --dry-run --diff --json
pynakes groups add-entry refs.bib <NewKey> "<Chosen Group>" --json
```

`groups tree --json` returns each node's `name` and `description` (plus
`parent`, for hierarchy) — set a descriptive `description` on your groups with
`groups update-group refs.bib "<Name>" --description "..."` so an agent has
enough signal to pick well. `groups add-entry` only writes to the flat
`groups` field; it works the same whether or not a `group-tree` is defined.
Run it with `--dry-run --diff` first to sanity-check the agent's pick before
committing, like any other modifying command.

### Protect title capitalization

```bash
pynakes fields protect-title refs.bib --dry-run --diff --json
pynakes fields protect-title refs.bib --term OpenAI --term iOS --json
```

### Validate linked files

```bash
pynakes asset check refs.bib --json
pynakes asset check refs.bib --root ~/papers --json
```

The checker is read-only. It reports `ok`, `missing`, `wrong_type`, and
`unresolved` statuses for JabRef `file` links.

### Track cited and uncited entries

```bash
pynakes tex scan refs.bib paper.tex --json
pynakes tex scan refs.bib paper.tex --group Used --dry-run --diff --json
```

## Exit codes

- `0`: success
- `1`: error (parse, validation, or I/O failure)
- `2`: conflict — report the returned `options` or try a safer operation

## JSON output

**Every modifying command** (`groups`, `keys`, `fields`, `metadata`,
`normalize`, `convert`, `ref add`, `ref import`, `asset fetch`, `dedupe merge`,
`enrich`, `tex scan`) shares one envelope:

```json
{
  "status": "success",
  "action": "normalize",
  "file": "refs.bib",
  "dry_run": true,
  "modified": true,
  "modified_entries": 3,
  "warnings": [],
  "diff": "--- refs.bib\n+++ refs.bib\n..."
}
```

Field meanings (stable across commands):

- `status`: `"success"`, `"error"`, or `"conflict"`.
- `action`: the command name (e.g. `groups_add_entry`, `keys_repair`).
- `file`: the target `.bib` path. (Always `file` — never `input_path`.)
- `dry_run`: whether the run was a preview.
- `modified`: whether the file content **would change** (dry-run) or **did
  change** (real run).
- `modified_entries`: count of entries that changed.
- `warnings`: always present; an array (empty when there are none).
- `plan`: always present; a structured, machine-readable description of the
  staged changes (see below).
- `diff`: present only when `--diff` was passed and there is a change.

### The `plan` object

`plan` is the structured counterpart to the textual `diff` — an agent can reason
over it directly instead of parsing a diff. It is computed against the
pre-change state (so a `--dry-run` plan and the real-run plan match):

```json
"plan": {
  "summary": {"added": 0, "removed": 0, "renamed": 0, "modified": 1, "metadata_changed": 0},
  "entries": [
    {"change": "modified", "key": "Smith2020",
     "type": {"old": "article", "new": "misc"},
     "fields": {"doi": {"old": "https://doi.org/10.1/x", "new": "10.1/x"}}}
  ],
  "metadata": [{"key": "normalize-dois", "old": null, "new": "on"}]
}
```

Each `entries` item is one of `added` / `removed` (with `key`), `renamed` (with
`from` / `to` — a key change whose record is otherwise unchanged), or `modified`
(with per-field `old`/`new`, and an entry-type `old`/`new` when it changed).
`metadata` lists top-level metadata key changes. Duplicate citation keys are
compared best-effort.

Command-specific keys are added alongside these (e.g. `renames` for
`keys generate`/`repair`, `sources` for `keys generate`/`rename`,
`report`/`tagged`/`exported` for `tex scan`,
`operations` for `normalize`).

**Errors** return `{"status":"error","error":"<Type>","message":"..."}` with
exit code 1 (e.g. `FileNotFound`, `ParseError` with `line`, `InvalidInput`).
**Conflicts** return `{"status":"conflict","error":"...","options":[...]}` with
exit code 2, where `options` lists the resolutions to choose from.

Read-only commands (`inspect`, `search`, `lint`, `groups list`, `keys check`,
`metadata list`, `asset check`, `capabilities`) return
`status`, `action`, `file`, plus command-specific data (e.g. `lint` returns
`issues`; `inspect` returns `duplicate_keys`; group and metadata commands return
`groups` and `metadata` respectively).

### Projection envelopes (`corpus combine`, `corpus split`)

The projection commands read inputs read-only and create new files, so instead
of the single-`file` / `modified` envelope they report `inputs` and the files
they produce. `corpus combine`:

```json
{
  "status": "success",
  "action": "combine",
  "inputs": ["a.bib", "b.bib"],
  "out": "combined.bib",
  "dedupe": true,
  "dry_run": false,
  "written": true,
  "entries": 42,
  "warnings": [{"type": "duplicate_keys", "keys": ["Smith2020"]}],
  "diff": "..."
}
```

`corpus split` reports one entry per output bucket and how many entries matched no rule:

```json
{
  "status": "success",
  "action": "split",
  "inputs": ["1.bib", "2.bib"],
  "dry_run": false,
  "copy": false,
  "minimal": false,
  "outputs": [
    {"file": "used.bib", "predicate": "used", "entries": 30, "written": true},
    {"file": "rest.bib", "predicate": "*", "entries": 12, "written": true}
  ],
  "unrouted": 0,
  "warnings": []
}
```

Both still use exit `0`/`1`/`2`; `--dedupe` conflicts return the standard
`{"status":"conflict","error":"DuplicateMergeKey","options":[...]}` at exit `2`.
`--diff` adds a `diff` of each created file. `warnings` may carry
`{"type":"duplicate_keys",...}` and (for `split`) `{"type":"unrouted_entries",
"count":N}`.

## Best practices

- Use `--dry-run --diff --json` before modifying files.
- Always check `status` and the process exit code; never ignore exit `2`.
- Inspect the file before assuming keys, groups, or fields exist.
- Let `pynakes` parse and write BibTeX instead of editing entries by hand.
- Keep operations focused and report the diff when asking for confirmation.
