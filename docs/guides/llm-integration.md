# LLM & automation integration

This guide describes how an LLM or automation workflow should drive the
`pynakes` CLI: the command surface, the safe edit workflow, exit codes, and the
structured JSON contract. It is written for a program (or an agent) that calls
`pynakes` as a tool.

> Working *on* the pynakes codebase instead of using it? See `AGENTS.md` at the
> repository root.

## Why pynakes is automation-friendly

- **Deterministic.** The same input always produces the same output (the one
  exception is `doi import`, which makes a network call).
- **Preview before writing.** Every modifying command supports `--dry-run`.
- **Structured output.** `--json` returns a stable envelope (see below).
- **Conflicts return options, not guesses.** Blocked operations exit `2` with a
  list of resolutions.
- **Safe writes.** Modifications are atomic (temp file → re-parse validation →
  rename) with an automatic `.bak` backup, and edits are surgical so unmodified
  entries stay byte-for-byte identical.

## Capabilities introspection

Discover the supported operations and exit-code semantics before acting:

```bash
pynakes capabilities --json
```

## Command surface

Read-only:

- `pynakes inspect <file> [--json]`
- `pynakes lint <file> [--json]`
- `pynakes groups list <file> [--json]`
- `pynakes keys check <file> [--json]`
- `pynakes capabilities [--json]`

Modifying (all support `--dry-run`, `--diff`, `--json`):

- `pynakes groups add-entry <file> <key> <group>`
- `pynakes groups remove-entry <file> <key> <group>`
- `pynakes keys generate <file>` — regenerate every key (`AuthorYearTitle`)
- `pynakes keys repair <file>` — make duplicate keys unique
- `pynakes fields rename <file> <old> <new> [--where ...]`
- `pynakes fields move <file> <old> <new> [--where ...]`
- `pynakes fields append <file> <field> <value> [--where ...]`
- `pynakes fields clear <file> <field> [--where ...]`
- `pynakes fields protect-title <file> [--field ...] [--term ...] [--where ...]`
- `pynakes doi import <file> <doi> [--key ...] [--key-source generated|provider]`
- `pynakes normalize <file>`
- `pynakes used <bib-file> <source>... [--out ...] [--group ...] [--keyword ...]`

Planned (not implemented): `convert`, dedicated `journals` commands, `entries`,
`dedupe`, `merge`.

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

### Import a DOI

```bash
pynakes doi import refs.bib 10.1145/3377811.3380368 --dry-run --diff --json
pynakes doi import refs.bib 10.1145/3377811.3380368 --json
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

### Add entries to a group

```bash
pynakes groups list refs.bib --json
pynakes groups add-entry refs.bib Smith2020 "CBDC" --dry-run --diff --json
pynakes groups add-entry refs.bib Smith2020 "CBDC" --json
```

### Protect title capitalization

```bash
pynakes fields protect-title refs.bib --dry-run --diff --json
pynakes fields protect-title refs.bib --term OpenAI --term iOS --json
```

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

**Every modifying command** (`groups`, `keys`, `fields`, `normalize`, `doi`,
`used`) shares one envelope:

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
- `diff`: present only when `--diff` was passed and there is a change.

Command-specific keys are added alongside these (e.g. `renames` for
`keys generate`/`repair`, `report`/`tagged`/`exported` for `used`,
`operations` for `normalize`).

**Errors** return `{"status":"error","error":"<Type>","message":"..."}` with
exit code 1 (e.g. `FileNotFound`, `ParseError` with `line`, `InvalidInput`).
**Conflicts** return `{"status":"conflict","error":"...","options":[...]}` with
exit code 2, where `options` lists the resolutions to choose from.

Read-only commands (`inspect`, `lint`, `groups list`, `keys check`,
`capabilities`) return `status`, `action`, `file`, plus command-specific data
(e.g. `issues`, `duplicate_keys`, `groups`).

## Best practices

- Use `--dry-run --diff --json` before modifying files.
- Always check `status` and the process exit code; never ignore exit `2`.
- Inspect the file before assuming keys, groups, or fields exist.
- Let `pynakes` parse and write BibTeX instead of editing entries by hand.
- Keep operations focused and report the diff when asking for confirmation.
