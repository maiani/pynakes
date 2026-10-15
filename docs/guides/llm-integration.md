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
  identical. `--backup` retains a `<file>.bak` copy where supported, or
  `<file>.bak.1`, `.bak.2`, ... once one exists, so an earlier backup is never
  overwritten. These mechanisms reduce common failure risks but are not formal
  durability guarantees.

## Discover the command surface

Start every integration with:

```bash
pynakes capabilities --json
```

Treat this output, rather than a copied command list, as the source of truth.
It includes:

- `command_groups` and `command_schemas`: the live commands, arguments,
  options, types, defaults, help text and per-command `stability` markers.
- `error_codes`: the error and conflict codes on which a caller can branch.
- `predicate_grammar`: the one selector grammar every entry-addressable
  command accepts, including boolean composition and its operator table. Its
  `used_by` list is read from the live commands (`normalize`, `enrich`,
  `fields`, `format`, `search`, and the rest), plus `corpus split --route`.
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
   it. Every modifying command accepts it; use the generated inventory rather
   than maintaining a partial command list.

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
  `ref show --key k1,k2,… [--abstract]` to triage a candidate set in one call
  instead of one invocation per key. Use the
  [bounded-read options](#bounded-reads) to compare the set within a budget.
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
  untouched; `--check` reports and exits `1` instead of writing. Add
  `--where used` to release only the cited entries. Do not approximate it with
  `fields clear`: that reaches the fields but not the group tree, the metadata
  blocks, or the comments.
- Use `keys rename` when a key change must also update TeX citations; use
  `keys generate` to apply the configured key pattern.
- Before renaming a key, check its blast radius with
  `keys usage <key> <dir>...`: a read-only `.tex` scan for `\cite`-family
  macros citing that key. It takes no `.bib` file and ignores `tex-sources`
  metadata, so it also covers sources `tex add` was never pointed at — a
  frozen snapshot, a generated diff, a collaborator's copy.

`ref show` and `ref edit` require the key to identify exactly one entry. If it
is duplicated, repair the duplicate keys or select entries with a bulk
`fields --where` operation instead of guessing.

To find candidates from a half-remembered title, `search --fuzzy` matches near
misses and reports, per hit, which field matched, whether the match was exact or
fuzzy, its score, and the matching excerpt — enough to decide without reading
each entry. Add `--abstract` when the excerpt is not enough to separate
the candidates, then summarize the survivors with one
`ref show --key k1,k2,… --abstract --json` call: each entry reports its
`entry_type` and a `summary` of title, creator, date, venue, and identifiers,
with `abstract: null` where none is stored. Read a chosen entry in full with a
single-key `ref show <key> --json`.

### Bounded reads

Comparing a set of papers needs their abstracts, what can be read for each, and
where it came from, within a response budget. Two options decide what each
entry reports:

- `--select f1,f2` returns exactly those stored fields — `abstract` is one —
  under `fields`, in place of the triage `summary` (on `search`, as each
  match's `fields`; `search --in` separately chooses the fields searched).
- `--include materials,provenance` adds what the library records outside the
  entry's fields, each part under its own key. `materials`: the Pinax materials
  present for the key (`pinax.configured` is `false` without
  `pinax-files-dir`) and the BibLaTeX `file` links with their status.
  `provenance`: the Pinax manifest record of each material (source, dates,
  access) and the directives above the entry with their reasons.

For example, `ref show --key k1,k2,… --select title,abstract --include
materials --json`. Everything comes from existing records, offline; nothing in
a record is a judgment about the work.

Keep the response bounded with the same options on `ref show --key`,
`ref show --where`, and `search`:

- `--limit N` returns at most `N` entries; `page.total` counts the whole
  selection and `--limit 0` reports only that count.
- `--cursor` resumes with `page.next_cursor` until `page.complete` is `true`.
  The cursor is bound to the library snapshot: if the file changes between
  pages, the next page is refused with the `StaleCursor` conflict (exit 2), so
  pages never silently skip or repeat entries. Restart from the first page.
- `--max-chars N` cuts every text value to `N` characters (characters of the
  stored text, never tokens) and lists each cut under the entry's `truncated`
  with its full and returned lengths. `retrieve_full` names the keys to
  re-read in full.

Keep missing and omitted apart when you report on a selection. *Missing* means
the library has nothing: a selected field is `null` and listed in
`missing_fields`, and an included part with nothing recorded is listed in
`missing`. *Omitted* means a value exists but was left out: `omitted_fields`
names stored fields outside `--select`, and `truncated` names cut values. Say
that a summary was based on truncated text rather than presenting it as
complete.

### Saved queries and analysis

A selection worth repeating can be saved in the library:
`query set refs.bib to-read 'abstract exists and not group "Read"'` stores a
`query-to-read` line in `pynakes-meta`, validated with the `--where` grammar.
A saved query is a `--where` predicate: `ref show refs.bib --where 'query
"to-read"' --json` evaluates it against the entries as they are now, so it
reflects every later edit, and returns pages under the bounded-read options
above. Every command that takes `--where` runs it the same way and can narrow
it (`--where 'query "to-read" and year >= 1900'`). `query list` reports
whether each stored query still parses; `lint` reports one that does not.

`analyze refs.bib --json` describes a library with offline counts in named
`sections`: entries and duplicate keys, types, years, the most frequent
authors and venues (`--top`), identifier and field coverage, groups, `lint`
findings, and linked-file and Pinax materials. The `lint` section is exactly
`lint`'s summary, and every per-entry section counts each entry once. Use
`--section` to read only what you need. The counts describe the records; do
not present them as a measure of scientific quality.

### Collecting materials

One command collects the best available PDF for a library and says whether the
collection is complete:

```bash
pynakes asset fetch refs.bib --material best-pdf --access institutional \
  --discover --progress jsonl --json > fetch.json
```

- **Completeness.** `summary` counts what the run did; `coverage` answers the
  research question: `entries`, `with_pdf`, `without_pdf`, and `missing`, one
  item per entry still lacking a requested PDF with the `reason` this run
  recorded. `complete` is `false` while anything is missing or failed, even
  though `status` is `"success"` and the exit code is `0` without `--strict`.
- **Progress.** `--progress jsonl` writes one JSON event per line on stderr
  while stdout keeps the final envelope: `entry` (with `entry_index` and
  `entry_total`), `artifact_start`, `artifact_done`, `artifact_skip`, `skip`,
  `fail`, and `retry` (with `retry_in` seconds and the `attempt` that follows).
  Read the stream instead of polling the files directory.
- **Attempts.** Every skipped or failed item lists its requests, including the
  lookups made before any PDF link existed: `stage` is `resolve` (a DOI landing
  page or open-access index, named by `lookup`, with its `error`) or
  `download`, and `retryable` says whether running again later can succeed.
- **Preprints stay preprints.** A PDF served by arXiv is stored as
  `preprint_pdf` (`artifact`, `classified_by: "source_host"`, `source`), and an
  arXiv DOI (`10.48550/arXiv.*`) is read as the arXiv id it encodes, never as a
  published version. `asset check` reports files stored as published that the
  evidence says are preprints (`misclassified`, with `source_host`,
  `arxiv_doi`, or `pdf_arxiv_stamp` evidence); `asset repair --reclassify`
  moves them, with their manifest records.
- **Missing arXiv ids.** `--discover` looks one up by DOI when a preprint is
  needed, then checks it against arXiv's record (the DOI arXiv records, or a
  matching title). `discovered` reports each lookup: `linked` (used, and written
  as `eprint` only when the entry has none), `ambiguous` (reported, not used),
  `not_found`, or `not_checked` (with `retryable`).
- **Resuming.** Each material is recorded as it lands, so an interrupted run
  is resumed by running the same command: present materials are skipped.

To apply part of an enrichment after reviewing it, preview with
`enrich refs.bib --online --dry-run --json`, then run the same command with
`--only-field eprint,archiveprefix --expect-sha256 <source_sha256>`. A failed
provider lookup is reported with `checked: false` and listed under
`lookups.not_checked`; it is never a "no match". `lookups.retry` gives the
arguments that rerun only the retryable ones, at a lower concurrency when a
provider throttled the run.

To move reviewed references from a scratch library into a project library with
their materials, run
`corpus combine project.bib scratch.bib --out project.bib --force --dry-run --json`:
the project keeps its `pinax-files-dir`, and `pinax_materials` names every file
that would be copied. Run it again without `--dry-run` to apply.

For compact reads, `lint --summary` keeps every count (`by_category`,
`by_type`) without listing each finding, and `lint --severity warning` leaves
out informational ones. `ref show --key K --select title,doi` returns only the
fields named, so abstracts stay out unless selected.

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
On `asset fetch`, `--strict` gates completeness rather than findings: it exits
`1` when any requested material failed to download or was unavailable (an entry
with nothing to fetch it by counts; a material already present does not). The
full envelope is still emitted with `status: "success"`, so read `summary`,
`fetched`, `skipped`, and `failed` to see what did land. Without `--strict`, a
partial run exits `0`: check `summary.failed` and `summary.unavailable` rather
than `modified`, which describes only the `.bib`.
`format --check` exits `1` when formatting is needed, and `scrub --check` exits
`1` when private content is present, but their JSON still has
`status: "success"` (with `modified: true` and `clean: false` respectively). A genuine failure has
`status: "error"` and an `error` code.

Always evaluate both the process exit code and the JSON `status`.

## JSON contract

Every `--json` envelope belongs to one of five families. The family fixes the
keys a caller can rely on; each command adds its own fields alongside them.
`tests/test_contract.py` checks every command against its family, and from
0.7.0 removing or renaming one of these keys is a breaking change.

| Family | Commands | Keys always present on success |
|---|---|---|
| modify | edits one library in place (`normalize`, `ref edit`, `fields set`, `tex add`, …) | `status`, `action`, `file`, `dry_run`, `modified`, `modified_entries`, `warnings`, `source_sha256` |
| create | writes new files (`init`, `scrub`, `corpus combine`, `corpus split`) | `status`, `action`, `dry_run`, `warnings`, plus `out`/`written` or `outputs` |
| read | reports without writing (`ref show`, `search`, `inspect`, `tex list`, …) | `status`, `action`, `warnings`, `source_sha256` |
| check | gates a library (`lint`, `verify`, `keys check`, `dedupe check`, `asset check`) | `status`, `action`, `file`, `warnings`, `source_sha256`, `strict` |
| error | any failure or conflict | `status`, `error`, `message` |

Shared rules:

- `status` is `success`, `error`, or `conflict`.
- `action` is the command path with spaces and hyphens as underscores:
  `ref show` reports `ref_show`, `groups add-entry` reports `groups_add_entry`.
- `warnings` is always an array of objects, each with at least `type` and
  `message`. Branch on `type`.
- `source_sha256` is the sha256 of the library as this invocation read it —
  before the write, also on a real run. Pass it back as `--expect-sha256` to
  make a later write conditional on the file being unchanged. A create command
  reports it for the library it read, or `sources_sha256` when it read several;
  `init`, `capabilities`, and `keys usage` read no library and omit it.
- `diff` is included when `--diff` was passed and a textual change exists.

A modify envelope looks like this:

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

`modified` says whether content would change or did change, `modified_entries`
counts the changed entries, and `plan` describes the staged changes (below).

A check envelope puts its counts under `summary` and its findings beside it
(`issues` for `lint`). Given several libraries, a check reports them under
`files`, one object per library, with an aggregate `summary` that also counts
`files` and `failed_files`; the top level then has no `file` or
`source_sha256`, and each item carries its own.

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
{"status":"error","error":"KeyNotFound","message":"No reference with key 'Nope'","action":"ref_show"}
```

Conflicts exit `2` and include resolutions:

```json
{"status":"conflict","error":"DuplicateReference","action":"ref_import",
 "message":"Reference already exists", "identifier":"10.5555/example",
 "existing_keys":["Example1900"],
 "options":[{"id":"keep_existing","description":"Do not import a duplicate reference"},
            {"id":"allow_duplicate","description":"Retry with --allow-duplicate"}]}
```

Each `error` code has one status and one exit code wherever it is raised; both
come from a single catalogue, which `capabilities.error_codes` publishes.

A conflict means nothing was written. A refused `--expect-sha256` is an
`ExternalModification` conflict that also carries `expected_sha256` (what you
passed) and `source_sha256` (what the file holds now); re-read the file and
preview again rather than retrying with the new digest unreviewed.

Branch on `error`, not on message text. Discover the current code inventory
from `capabilities.error_codes`.

### Commands that create files

File-producing commands retain the common envelope where applicable.
`scrub` and `corpus combine` report the input in `file` and the destination
in `out`; `corpus split` reports destinations as `outputs` objects with `path`.
Command-specific fields include `inputs`, `entries`, `removed` and `unrouted`.
Do not assume every file-producing command has an `out` key or omits `modified`
and `plan`. The `status` and exit-code rules are the same, and every create command
supports `--dry-run`, `--diff`, and `--json`.

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

### Metadata value choices

`inspect --json` includes `metadata_value_choices`, a mapping from lower-case
metadata keys to accepted values for finite, single-valued settings. It applies
to either metadata namespace and shares the engine's validation registries.
The standard Boolean metadata values are `true` and `false`, so those are the
only Boolean choices advertised. Other supported spellings are nonstandard
compatibility aliases and remain accepted on input.
Clients can use it for dropdowns, including when adding a new metadata block.
List-valued settings, numbers, and free-form values are omitted. Existing raw
values can have different casing or a trailing terminator; reading the choices
must not silently replace them. Older engines may omit the map, in which case
clients can retain free-form editing and rely on `metadata set` validation.

### Shared inspection reports

`inspect refs.bib --display --insights --json` includes an `insights` object
with `groups_tree`, `groups_list`, and `lint` envelopes equivalent to their
individual commands (lint is advisory, with `strict: false`). All use the same
parsed bibliography and source fingerprint. Each supplementary read can return
an error envelope independently while inspection succeeds. The option adds data
only to JSON output; ordinary inspection is unchanged. TeX and material checks
remain separate, allowing clients to check a saved bibliography's neighbouring
files while inspecting an unsaved buffer through a temporary file.
