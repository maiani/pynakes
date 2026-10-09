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
  fetch`, `ref import --fetch`, `verify --online`, `enrich --online`,
  `ref compare --online`, and `ref find --online`.
- **Reviewable edits.** Modifying commands support `--dry-run` and `--diff`,
  including `asset repair`, whose diff is of the Pinax manifest it reconciles.
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
- `predicate_grammar`: the one selector grammar every entry-addressable
  command accepts (`fields`, `search`, `format`, `corpus combine --where`, and
  `corpus split --to`), including boolean composition and its operator table.
  Its `key_selector` entry documents `--key`, the no-grammar shorthand for
  selecting by citation key that every `--where` command also accepts.
- `search_query_grammar`: term, phrase, field, fuzzy, ranking, and
  match-explanation behavior.
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

   When time passes between the preview and the write — a person reviewing the
   diff, an agent waiting on approval — pass the preview's `source_sha256` back
   as `--expect-sha256`. If the file changed in between, the command writes
   nothing and exits `2` with an `ExternalModification` conflict instead of
   applying the approved change on top of an edit nobody reviewed:

   ```bash
   pynakes corpus batch refs.bib --dry-run --diff --json --ops-file ops.json
   # ... review; then, with the source_sha256 from that preview:
   pynakes corpus batch refs.bib --json --ops-file ops.json \
     --expect-sha256 9a6660d44e528fcd22a29a915bddea03a86d6587f6c708a39b19a5f734afb786
   ```

   `capabilities.write_precondition.commands` lists the commands that accept
   it: today `ref edit`, `ref add`, `ref import`, `ref remove`, `groups
   add-entry`, `groups remove-entry`, `dedupe merge`, and `corpus batch`.

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
memory and commits them atomically, or writes nothing if one fails. This is the
right shape for anything proposed as a set — add these two, drop that one,
retag the rest — because it is previewed as one diff and approved as one
decision rather than as a sequence of writes that can half-apply:

```bash
pynakes corpus batch refs.bib --dry-run --diff --json --ops '[
  {"op": "ref.add", "key": "Newton1687", "entry_type": "book",
   "fields": {"title": "Principia", "author": "Newton, Isaac", "year": "1687"}},
  {"op": "ref.remove", "key": "Fabricated2021"},
  {"op": "fields.set", "field": "keywords", "value": "to-read",
   "where": "year >= 2024"}
]'
```

Discover the operation vocabulary through `capabilities`; it covers the
`fields`, `groups`, `keys`, `metadata`, `ref`, and `dedupe` families. Two
boundaries are deliberate:

- `ref.import` is **not** a batch operation. It reaches the network, so what it
  returns depends on when it was asked, and a batch that cannot be replayed to
  the same result is not something a single approval can stand for. Import
  first, then batch what follows.
- `ref.remove` in a batch leaves any Pinax materials on disk. Deleting them is a
  filesystem act and a batch stages only in memory, so it cannot join the same
  atomic commit. The `ref remove` command deletes them by default.

An operation that refuses — `ref.add` on a taken key, `dedupe.merge` on an
irreconcilable cluster — aborts the whole batch with nothing written, which is
the all-or-nothing guarantee rather than an exception to it.

## Choosing the right operation

- Use `ref show <key>` to read one uniquely keyed reference, and
  `ref show --keys k1,k2,… [--abstract]` to triage a candidate set in one call
  instead of one invocation per key.
- Use `ref edit <key>` for a multi-field patch to one reference.
- Use `ref directive ignore <finding> --key <key> --reason "..."` to accept a lint
  finding a human has judged unfixable for one entry (a venue with no DOIs),
  rather than inventing a value to silence it. Record the reason; `lint`
  reports the waiver as `unused_entry_directive` once it no longer applies.
- Use `ref compare <key> --online` to check one reference's DOI (or, absent a
  DOI, its arXiv id) against provider metadata, or `ref compare <key> --with
  <other-key>` to compare it against another entry already in the library
  (e.g. a candidate duplicate) with no network access. Either way it's
  read-only and reports only the fields where a non-empty value on the other
  side differs from the local one — review the `fields` list, then apply the
  ones you want with `ref edit <key> --field name=value` (repeatable). Use
  `enrich --online` and `verify --online` instead for whole-library,
  always-fill or always-report operations; `ref compare` is for one entry at a
  time with a human choosing per field.
- Use `fields` with `--where` for bulk field operations over a selection. The
  same selector works on `search`, `format`, and the corpus operations, so
  scope a set once — `'year >= 2025 and doi missing'` — and reuse the
  expression rather than filtering with `grep`.
- Use `ref add` for a fully local, manually supplied reference, or `ref.add`
  inside a `corpus batch` when it is one of several related changes.
- Use `ref import` for network-backed DOI, repository, preprint, and
  working-paper metadata resolution; give it several identifiers, or pipe them
  with `-`, when a whole list has to resolve.
- Use `ref find "<reference text>" --online` when a reference arrives written
  out rather than as an identifier, and you need to know whether it describes
  anything real before importing it. Read-only. It reports candidates with the
  index's own relevance score and marks those that plainly match; it never
  decides. Treat an empty result as evidence rather than proof — an obscure or
  very recent work also matches nothing.
- Use `format` for layout only and `normalize` for bibliographic conventions.
- Use `scrub` before a library leaves the author's machine — an arXiv upload, a
  submission bundle, a public repository. It writes a copy (`--out`) without
  private entry fields, metadata blocks, or free comments, and leaves the source
  untouched; `--check` reports and exits `1` instead of writing. Chain it after
  `tex scan --out` to release only the cited entries. Do not approximate it with
  `fields clear`: that reaches the fields but not the group tree, the metadata
  blocks, or the comments.
- Use `keys rename` when a key change must also update TeX citations; use
  `keys generate` to apply the configured key pattern.
- Before renaming a key, check its blast radius with
  `keys usage <key> --path <dir>`: a read-only `.tex` scan for `\cite`-family
  macros citing that key. It takes no `.bib` file and ignores `tex-sources`
  metadata, so it also covers sources `tex add` was never pointed at — a
  frozen snapshot, a generated diff, a collaborator's copy.

`ref show` and `ref edit` require the key to identify exactly one entry. If it
is duplicated, repair the duplicate keys or select entries with a bulk
`fields --where` operation instead of guessing.

To find candidates from a half-remembered title, `search --fuzzy` matches near
misses and reports, per hit, which field matched, whether the match was exact or
fuzzy, its score, and the matching excerpt — enough to decide without reading
each entry. Add `--show-abstract` when the excerpt is not enough to separate
the candidates, then summarize the survivors with one
`ref show --keys k1,k2,… --abstract --json` call: each entry reports its
`entry_type` and a `summary` of title, creator, date, venue, and identifiers,
with `abstract: null` where none is stored. Read a chosen entry in full with a
single-key `ref show <key> --json`.

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
`format --check` exits `1` when formatting is needed, and `scrub --check` exits
`1` when private content is present, but their JSON still has
`status: "success"` (with `modified: true` and `clean: false` respectively). A genuine failure has
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
  "source_sha256": "9a6660d44e528fcd22a29a915bddea03a86d6587f6c708a39b19a5f734afb786",
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
- `source_sha256`: the sha256 of the file as this invocation read it — before
  the write, also on a real run. Pass it back as `--expect-sha256` to make a
  later write conditional on the file being unchanged.
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

A conflict means nothing was written. A refused `--expect-sha256` is an
`ExternalModification` conflict that also carries `expected_sha256` (what you
passed) and `source_sha256` (what the file holds now); re-read the file and
preview again rather than retrying with the new digest unreviewed.

Branch on `error`, not on message text. Discover the current code inventory
from `capabilities.error_codes`.

### Commands that create files

`init`, `scrub`, `corpus combine`, and `corpus split` create or project files
rather than editing one existing library. Their envelopes therefore report
fields such as `inputs`, `out`, `outputs`, `written`, `entries`, `source`,
`removed`, and `unrouted` instead of the ordinary single-file mutation fields. They retain the same
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
