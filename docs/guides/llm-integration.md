# LLM & automation integration

This guide describes how an LLM or automation workflow should drive the
`pynakes` CLI: the command surface, the safe edit workflow, exit codes, and the
structured JSON contract. It is written for a program (or an agent) that calls
`pynakes` as a tool.

> Working *on* the pynakes codebase instead of using it? See `AGENTS.md` at the
> repository root.

## Why pynakes is automation-friendly

- **Deterministic.** The same input always produces the same output (the one
  exception is `add`, which makes a network call).
- **Preview before writing.** Every modifying command supports `--dry-run`.
- **Structured output.** `--json` returns a stable envelope (see below).
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
  `fields --where` and `split --to`.

## Command surface

Read-only:

- `pynakes inspect <file> [--json]`
- `pynakes lint <file>... [--strict] [--json]`
- `pynakes groups list <file> [--json]`
- `pynakes keys check <file>... [--strict] [--json]`
- `pynakes metadata list <file> [--json]`
- `pynakes files check <file>... [--root ...] [--strict] [--json]`
- `pynakes journals check <file> [--json]`
- `pynakes dedupe check <file>... [--strict] [--json]`
- `pynakes verify <file>... [--online] [--strict] [--json]`
- `pynakes published <file> [--online] [--json]`
- `pynakes capabilities [--json]`

The five gate checks (`lint`, `keys check`, `files check`, `dedupe check`,
`verify`) accept multiple `.bib` files and support `--strict` to exit `1` on a
finding — the primitives for CI and pre-commit gating. See
[Git Workflows](git-workflows.md). A single file keeps its per-file JSON
envelope; multiple files emit an aggregate `{status, action, strict, files,
summary}` envelope.

Modifying (all support `--dry-run`, `--diff`, `--json`):

- `pynakes groups add-entry <file> <key> <group>`
- `pynakes groups remove-entry <file> <key> <group>`
- `pynakes keys generate <file> [--key <old-key>]` — regenerate every key, or
  only the selected key, using the preferred pattern (`AuthorYearTitle` by default)
- `pynakes keys repair <file>` — make duplicate keys unique
- `pynakes keys rename <file> <old> <new> <tex-source>...` — rename one key in
  the `.bib` file and matching TeX citation commands
- `pynakes fields rename <file> <old> <new> [--where ...]`
- `pynakes fields move <file> <old> <new> [--where ...]`
- `pynakes fields append <file> <field> <value> [--where ...]`
- `pynakes fields clear <file> <field> [--where ...]`
- `pynakes fields protect-title <file> [--field ...] [--term ...] [--where ...]`
- `pynakes add <file> <identifier> [--key ...] [--key-source generated|provider] [--allow-duplicate]` — `<identifier>` is a DOI, DOI URL, arXiv id, or arXiv URL
- `pynakes metadata set <file> <key> <value> [--allow-unknown]`
- `pynakes normalize <file>`
- `pynakes convert <file> --to biblatex|bibtex`
- `pynakes journals abbreviate <file> [--journal-table ...] [--ltwa-table ...]`
- `pynakes journals expand <file> [--journal-table ...] [--ltwa-table ...]`
- `pynakes dedupe merge <file>` — conservatively merge duplicate-work clusters
- `pynakes enrich <file> [--online]` — conservatively fill missing metadata
- `pynakes published <file> --apply [--online]` — apply safe published-version metadata
- `pynakes used <bib-file> <source>... [--out ...] [--group ...] [--keyword ...]`

Projections — read inputs read-only, **create** new files (support `--dry-run`,
`--diff`, `--json`):

- `pynakes merge <file>... --out <file> [--dedupe]` — combine several `.bib`
  files into one. `--dedupe` collapses identical same-key entries and reports a
  conflict (exit `2`) when same-key entries differ.
- `pynakes split <file>... --to <FILE>='<predicate>'... [--copy] [--tex ...]
  [--aux ...] [--dedupe]` — combine inputs in memory and route entries into
  several outputs. Each `--to` pairs an output file with a predicate: a
  [`--where`](#the-where-filter) expression, or one of `*`, `used` / `unused`
  (against `--tex`/`--aux`), or `group "Name"`. First match wins by default;
  `--copy` routes an entry to every matching output.

Transactional:

- `pynakes batch <file> --ops '<json>' | --ops-file <path>` — apply a sequence
  of operations to one file atomically (one preview, one commit; nothing is
  written if any operation fails). The operation vocabulary (op name → required/
  optional params) is in `capabilities` under `batch_operations`. Example:
  `--ops '[{"op":"groups.add_entry","key":"Smith2020","group":"ML"},{"op":"journals.abbreviate"}]'`.

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

## Common tasks

### Normalize a bibliography

```bash
pynakes normalize refs.bib --dry-run --diff --json
pynakes normalize refs.bib --json
```

`normalize` can protect title capitalization, normalize author/editor lists,
normalize DOI values, and abbreviate or expand journal titles. It honors project
metadata overrides via `jabref-meta` comments and CLI options.

### Add a reference (DOI or arXiv)

```bash
pynakes add refs.bib 10.1145/3377811.3380368 --dry-run --diff --json
pynakes add refs.bib 10.1145/3377811.3380368 --json
pynakes add refs.bib arXiv:2301.00001 --json
```

Citation-key priority:

- `--key` wins when supplied.
- `--key-source provider` keeps the provider's key when one is available.
- `--key-source generated` (default) generates a key locally, using JabRef
  citation-key metadata when present.

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

### Add entries to a group

```bash
pynakes groups list refs.bib --json
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff --json
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --json
```

### Protect title capitalization

```bash
pynakes fields protect-title refs.bib --dry-run --diff --json
pynakes fields protect-title refs.bib --term OpenAI --term iOS --json
```

### Validate linked files

```bash
pynakes files check refs.bib --json
pynakes files check refs.bib --root ~/papers --json
```

The checker is read-only. It reports `ok`, `missing`, `wrong_type`, and
`unresolved` statuses for JabRef `file` links.

### Track cited and uncited entries

```bash
pynakes used refs.bib paper.tex --json
pynakes used refs.bib paper.tex --group Used --dry-run --diff --json
```

## Exit codes

- `0`: success
- `1`: error (parse, validation, or I/O failure)
- `2`: conflict — report the returned `options` or try a safer operation

## JSON output

**Every modifying command** (`groups`, `keys`, `fields`, `metadata`,
`normalize`, `convert`, `journals`, `doi`, `used`) shares one envelope:

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
`keys generate`/`repair`, `sources` for `keys rename`,
`report`/`tagged`/`exported` for `used`,
`operations` for `normalize`).

**Errors** return `{"status":"error","error":"<Type>","message":"..."}` with
exit code 1 (e.g. `FileNotFound`, `ParseError` with `line`, `InvalidInput`).
**Conflicts** return `{"status":"conflict","error":"...","options":[...]}` with
exit code 2, where `options` lists the resolutions to choose from.

Read-only commands (`inspect`, `lint`, `groups list`, `keys check`,
`metadata list`, `files check`, `journals check`, `capabilities`) return
`status`, `action`, `file`, plus command-specific data (e.g. `issues`,
`duplicate_keys`, `groups`, `metadata`).

### Projection envelopes (`merge`, `split`)

The projection commands read inputs read-only and create new files, so instead
of the single-`file` / `modified` envelope they report `inputs` and the files
they produce. `merge`:

```json
{
  "status": "success",
  "action": "merge",
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

`split` reports one entry per output bucket and how many entries matched no rule:

```json
{
  "status": "success",
  "action": "split",
  "inputs": ["1.bib", "2.bib"],
  "dry_run": false,
  "copy": false,
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
