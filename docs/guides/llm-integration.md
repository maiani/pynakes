# LLM & automation integration

Pynakes exposes bibliography inspection and editing commands that scripts and
LLM-assisted tools can call without rewriting BibTeX directly. It provides
validation, previews, structured results, and conflict reporting; callers
remain responsible for deciding which changes to request and accept.

This guide defines how an LLM or automation workflow should drive that engine:
command discovery, the preview-and-commit workflow, exit codes, and the structured JSON
contract. For command-by-command tutorials, see the [usage guide](usage.md).

> Working *on* the pynakes codebase instead of using it? See `AGENTS.md` at the
> repository root.

## Automation behavior

- **Explicit network access.** Network use is limited to `ref import`, `asset
  fetch`, `ref import --fetch`, `verify --online`, and `enrich --online`.
- **Reviewable edits.** Ordinary modifying commands support `--dry-run` and
  `--diff`. The maintenance operation `asset check --fix` is the exception: it
  writes directly and can retain the prior manifest with `--backup`.
- **Structured output.** Use `--json`; do not parse human-readable output.
- **Explicit conflicts.** A blocked operation exits `2` and returns resolution
  options instead of choosing one.
- **Validated replacement.** Commits prepare a temporary file, re-parse it, and
  replace the destination. Surgical edits leave untouched entries byte-for-byte
  identical. `--backup` retains a `<file>.bak` copy where supported. These
  mechanisms reduce common failure risks but are not formal durability
  guarantees.

## Discover the command surface

Start every integration with:

```bash
pynakes capabilities --json
```

Treat this output, rather than a copied command list, as the source of truth.
It includes:

- `command_groups` and `command_schemas`: the live commands, arguments,
  options, types, defaults, and help text.
- `error_codes`: the error and conflict codes on which a caller can branch.
- `predicate_grammar`: expressions accepted by `fields --where`,
  `search --where`, and `corpus split --to`.
- `search_query_grammar`: term, phrase, field, and ranking behavior.
- `batch_operations`: the operation vocabulary accepted by `corpus batch`.

Use the schema to construct calls and `pynakes <command> --help` for a focused
human-readable view. The [usage guide](usage.md) explains the individual
commands and their semantics.

## Preview and apply workflow

1. Inspect the library and run the relevant checks.

   ```bash
   pynakes inspect refs.bib --json
   pynakes lint refs.bib --json
   ```

2. Preview a change and inspect `status`, `plan`, and optionally `diff`.

   ```bash
   pynakes normalize refs.bib --dry-run --diff --json
   ```

3. Apply the same command without `--dry-run` only after accepting the plan.

   ```bash
   pynakes normalize refs.bib --json
   ```

4. Run the checks affected by the edit. A complete local validation pass is:

   ```bash
   pynakes lint refs.bib --json
   pynakes keys check refs.bib --json
   pynakes dedupe check refs.bib --json
   pynakes tex scan refs.bib paper.tex --json
   pynakes asset check refs.bib --json
   pynakes verify refs.bib --json
   ```

Only add `verify --online` when provider lookups are intentionally allowed.
For several related edits, use `corpus batch`: it stages all operations in
memory and commits them atomically, or writes nothing if one fails. Discover
its operation vocabulary through `capabilities`.

## Choosing the right operation

- Use `ref show <key>` to read one uniquely keyed reference.
- Use `ref edit <key>` for a multi-field patch to one reference.
- Use `fields` with `--where` for bulk field operations over a selection.
- Use `ref add` for a fully local, manually supplied reference.
- Use `ref import` for network-backed DOI, repository, preprint, and
  working-paper metadata resolution.
- Use `format` for layout only and `normalize` for bibliographic conventions.
- Use `keys rename` when a key change must also update TeX citations; use
  `keys generate` to apply the configured key pattern.

`ref show` and `ref edit` require the key to identify exactly one entry. If it
is duplicated, repair the duplicate keys or select entries with a bulk
`fields --where` operation instead of guessing.

### Agent-assisted classification

pynakes deliberately has no built-in semantic classifier. To classify an
imported entry, the calling agent should:

1. Import the reference and retain its returned key.
2. Read it with `ref show <key> --json`.
3. Read candidate groups with `groups tree --json`; descriptions provide the
   semantic context.
4. Choose a group, preview `groups add-entry` with `--dry-run --diff --json`,
   and then apply it.

This choice belongs to the caller rather than to a pynakes operation.

## Exit codes

- `0`: success.
- `1`: error, including parse, validation, and I/O failures.
- `2`: conflict. Read and report `options`; do not retry by guessing.

Gate commands may also use exit `1` for findings when `--strict` is enabled.
`format --check` exits `1` when formatting is needed, but its JSON still has
`status: "success"` and `modified: true`. A genuine failure has
`status: "error"` and an `error` code.

Always evaluate both the process exit code and the JSON `status`.

## JSON contract

Ordinary modifying commands return this common envelope:

```json
{
  "status": "success",
  "action": "normalize",
  "file": "refs.bib",
  "dry_run": true,
  "modified": true,
  "modified_entries": 3,
  "warnings": [],
  "plan": {
    "summary": {
      "added": 0,
      "removed": 0,
      "renamed": 0,
      "modified": 3,
      "metadata_changed": 0
    },
    "entries": [],
    "metadata": []
  },
  "diff": "--- refs.bib\n+++ refs.bib\n..."
}
```

Common fields:

- `status`: `success`, `error`, or `conflict`.
- `action`: the operation name.
- `file`: the target `.bib` path.
- `dry_run`: whether the operation was a preview.
- `modified`: whether content would change or did change.
- `modified_entries`: the number of changed entries.
- `warnings`: always an array, including when empty.
- `plan`: a structured description of staged changes.
- `diff`: included when requested and a textual change exists.

Commands add operation-specific fields alongside this envelope. Read-only
commands retain `status` and `action`, then return their command-specific data.
Multi-file gate commands return a `files` collection and aggregate `summary`.

### The `plan` object

`plan` is the machine-readable counterpart to `diff`. Prefer it when deciding
whether to approve a change. A dry run and the corresponding real run compute
the plan against the same pre-change state.

Each `entries` item is one of:

- `added` or `removed`, with `key`.
- `renamed`, with `from` and `to`.
- `modified`, with field-level `old` and `new` values and, when relevant, an
  entry-type change.

`metadata` contains top-level metadata changes. Duplicate citation keys are
compared best-effort.

### Errors and conflicts

Errors exit `1`:

```json
{"status":"error","error":"InvalidInput","message":"..."}
```

Conflicts exit `2` and include resolutions:

```json
{"status":"conflict","error":"DuplicateCitationKey","options":["..."]}
```

Branch on `error`, not on message text. Discover the current code inventory
from `capabilities.error_codes`.

### Commands that create files

`init`, `corpus combine`, and `corpus split` create or project files rather
than editing one existing library. Their envelopes therefore report fields
such as `inputs`, `out`, `outputs`, `written`, `entries`, and `unrouted` instead
of the ordinary single-file mutation fields. They retain the same
`status`/exit-code rules and support `--dry-run`, `--diff`, and `--json`.

For `corpus split`, inspect every output bucket and `unrouted`; warnings report
duplicate or unrouted entries. With `--dedupe`, incompatible same-key entries
produce a standard exit-`2` conflict.

## Integration rules

- Discover commands and error codes; do not embed a manually maintained list.
- Use `--json` and keep stdout machine-readable. Human progress is written to
  stderr by commands that report it.
- Inspect before assuming that keys, groups, fields, or metadata exist.
- Preview modifications and reason over `plan`; request `diff` when a human
  also needs to review the textual edit.
- Never ignore exit `2` or choose a conflict resolution without authority.
- Let pynakes parse and write BibTeX instead of editing it as plain text.
- Keep network access explicit and operations focused.
