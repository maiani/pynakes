# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Applications built on top of it (capture, reading, a
UI, sync) remain separate companion projects rather than layers inside the core
engine. This plan may track their integration milestones, but they must consume
the same pinned public API instead of adding a second parser, data model, or
source of truth.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Road to 1.0

### v0.7 — CLI beta, editor alpha

v0.7.0 moves the **CLI** to beta: its command syntax, options, JSON envelope,
exit codes, and error codes become a contract that changes only through a
documented deprecation. The **VS Code editor** ships alongside it as an
**alpha** pre-release — usable, with no compatibility promise of its own, and a
consumer of nothing but the beta envelope. The Python API keeps its current
status — the intended public surface in
[docs/guides/public-api.md](docs/guides/public-api.md), with breaking changes
documented but not deprecated — until 1.0 pins it.

The plan below comes from a pre-beta audit (2026-09-30) of CLI consistency,
error paths, documentation, security, data integrity, platforms and packaging,
and dead code. The work runs as seven stages in order, each closed by a gate.
Stage 1 ships as a 0.6.x patch because it affects current users; every later
stage lands in 0.7.0.

#### The beta promise

What 0.7.0 commits to, and what every gate below tests for:

- **A frozen surface, with deprecation.** From 0.7.0, removing or renaming a
  command, option, envelope key, `action` value, exit-code meaning, or error
  code takes one minor release in which the old form still works and emits a
  structured warning (`{"type": "deprecated", "old": ..., "new": ...}`) before
  it is removed. Additions may ship in any minor release; patches fix bugs only.
- **No known data-loss bugs.** No command silently changes bytes outside the
  entries it edits, writes an unparseable file, reports a failed write as a
  success, or leaves a multi-file operation half-applied.
- **No tracebacks.** Every failure is a JSON error carrying a catalogued code.
- **Tested where advertised.** Every operating system and Python version the
  package metadata claims runs the suite in CI, as do the declared dependency
  floors.
- **Docs describe the real surface**, with a command reference generated from
  the live CLI.

#### Stage 1 — Stop-ship fixes → 0.6.5

Done: the fixes are recorded in CHANGELOG under 0.6.5, and 0.6.4 and 0.6.5 were
published on 2026-10-01. The local-only `v0.6.2` tag was never released; retire
it or leave it unpushed.

**Gate 1** (met): 0.6.5 is on PyPI.

#### Stage 2 — CI, release pipeline, platforms

Done: every later stage is now tested everywhere the beta claims to run.
The work is recorded in CHANGELOG under Unreleased: Python 3.12 as the floor, the
three-OS matrix with 3.15 allowed to fail, a lowest-dependency job, release
checks and wheel tests before publishing, PyPI before the GitHub release,
dependabot, the two Windows fixes, and mypy at a recorded baseline (the
`[[tool.mypy.overrides]]` list in `pyproject.toml`, to shrink and never grow).
Actions are referenced by major version tag, by choice, rather than pinned by
commit SHA. Running the release workflow by hand is a dry run; its TestPyPI
option needs a `testpypi` environment and a trusted publisher on test.pypi.org
first.

**Gate 2** (met, 2026-10-01): the full matrix is green, the lowest-dependency
job included; a release dry run passed every new check.

#### Stage 3 — Cleanup before the freeze

Shrink the surface before promising it: deleting a public name costs nothing
now and a deprecation cycle later.

- **Delete** (no callers): `group_tree.add_to_group_tree` and
  `remove_from_group_tree` (byte-identical to `groups.add_to_group` and
  `remove_from_group`); `cli_commands.groups._tree_mod`;
  `canonical._align_width`; `filestore.write_erratum_pdf`;
  `acl_anthology.DOI_PREFIX`; the unused `child_type` parameter of
  `inheritance._crossref_fields`; the `interchange.FORMATS` and
  `metadata.library_database_type` back-compat aliases; and
  `importer.IDENTIFIER_KINDS`, `arxiv_entry`, and `fetch_arxiv_record` (a
  public module, so each removal gets a CHANGELOG line).
- **Remove or fold test-only helpers** into what they wrap:
  `keys.has_duplicate_keys`, `keys.duplicate_key_counts`,
  `importer.extract_doi_from_journal_url`, `importer.entry_from_bibtex`,
  `group_tree.resolve_effective_groups`, `filestore.set_preprint_canonical`,
  `provider_cache.stats`.
- **Decide the `Bibliography` methods the CLI never calls**: `expand_journals`
  (no caller, no test), `import_doi` (superseded by `import_reference`, though
  the API docs say it remains), `journals_check`, `abbreviate_journals`,
  `rename_citekey`. Keep `from_bibfile`, which is documented, and give it a
  test.
- **Consolidate duplicates** into one home each: the arXiv DOI prefix (four
  copies), an entry's arXiv id (two), title similarity (two), case-insensitive
  field lookup (four), the `journal`/`journaltitle` container getter (five),
  the two TeX file walkers in `usage`, the duplicated group helpers and
  delimiters, and the thirteen read-only commands that call `json.dumps`
  instead of the shared emitter.
- **Rename leftover modules**: `cli_commands/used.py` implements `tex scan`;
  `cli_commands/files.py` implements `asset check`.
- **Split before the 1000-line cap**: move the Pinax manifest code out of
  `filestore` (953 lines) and the arXiv section out of `importer`; find seams
  for `canonical` (985), `lint` (942), and `metadata/jabref` (888).
- **Fix a stale docstring**: `keys usage` still refers to a removed `used scan`.

**Gate 3**: no module over 800 lines; vulture at 80% confidence reports only
reviewed false positives; the suite and the coverage floor hold.

#### Stage 4 — Freeze the surface

The one deliberate batch of breaking CLI changes, so the promise starts from a
consistent surface. Where an old form can be recognized unambiguously, it keeps
working through 0.7.x with a `deprecated` warning and is removed in 0.8.0; where
a flag's meaning changes, the old use fails with an error naming the
replacement.

- **One positional convention.** There are six today: library first (about 30
  commands); operand first (`ref show/edit/compare/add`, `asset fetch`,
  `search`); either order (`keys generate`); library only through `--file`
  (`ref import`, `tex list/add/remove/clear`); sources as a required `--path`
  option (`keys usage`); and several files (`lint`, `verify`, `dedupe check`,
  `keys check`, `asset check`, `corpus combine/split`). Adopt library first,
  plus a `--file` option on every single-library command. Stop choosing the
  library slot by `Path.is_file()` — `tex scan paper.tex` parses the `.tex` as
  the library — and reject a `.bib`-looking token in the wrong slot with an
  error that says so.
- **One meaning per flag.** `-f` is `--field` in `ref add/edit` but `--file` in
  `ref import` and `tex`. Rename the outliers of `--to` (`convert` format vs
  `corpus split` routing rule), `--from` (`convert` format vs `init` profile),
  `--type` (`init` dialect vs entry type), `--keys` (`normalize` mode vs
  `ref show` selection), `--field` (four meanings), `--force` (overwrite vs
  ignore missing TeX), and `--published` (three meanings).
- **One flag per concept**: `--abstract` and `--show-abstract`; `--title-field`
  and `--field`; TeX sources given as positionals, `PATHS`, `--path`, or
  `--tex/--aux`; `--out`, `--stdout`, and `--to` for output; `--strict` and
  `--check` for gating; `--bestpdf`; `--keep-field` beside `--keep-fields`.
- **Enumerated options become `click.Choice`**, so help and `capabilities` list
  their values: `normalize` (ten options), `init --type`, `--key-source`,
  `--namespace`, `lint --category`, `--context`.
- **Envelope.**
  - `action` is the command path joined by `_` (`ref_edit`, `tex_scan`,
    `asset_check`), replacing four naming schemes that include the legacy
    `used` and `files_check`; check modes report `check: true` rather than a
    separate `format-check` action.
  - `warnings` is always a list of objects: the `lint`/`verify` counts move to
    `summary`, and `info`/`infos` settle on one spelling.
  - `file` is always the input and written paths go in `out`/`outputs`;
    `scrub` and `corpus combine` currently put the output in `file`.
  - `convert` gains the modifying-command keys and honors `--diff`;
    `capabilities` gains `status` and `action`; `tex scan --group/--keyword`
    returns a `plan`.
  - Every envelope reports the fingerprint of the file it read, and modifying
    commands accept it back as a precondition (working name `--expect-sha256`),
    so a caller's preview → approve → commit cannot overwrite an edit made in
    between.
- **Exit codes and errors.**
  - Usage errors exit 1 in both output modes; outside `--json` they currently
    exit 2, Click's default and pynakes's conflict code. Human-mode errors go to
    stderr.
  - Conflicts are classified consistently: an existing group and an existing
    key are both conflicts (exit 2), and a missing group is `KeyNotFound`
    everywhere.
  - One central error-code enum. Catalogue the nine codes emitted but not
    listed, reclassify `OnlineLookupRequired` and `ProviderUnavailable`
    (catalogued as conflicts, emitted with exit 1), merge `NoTeXSources` into
    `NoSources`, and stop emitting Python class names such as
    `FileNotFoundError`.
- **Overwrite policy**: an existing output file requires `--force` everywhere,
  as `init` already does — `convert --out`, `tex scan --out`,
  `corpus split --to`, `corpus combine --out`. An output naming one of the
  command's inputs is refused outright since 0.6.5; requiring `--force` for
  every other existing file waited for the freeze because it breaks scripts
  that regenerate their outputs.
- **Validation**: `groups move-group --parent` and `groups add-entry` refuse a
  group that does not exist; `ref compare` without `--online` stops telling CLI
  users to "pass online=True".
- **Decisions to record before the gate**: whether `asset check --fix` gains
  `--dry-run`/`--diff`; whether `keys check` stays beside `lint`'s
  `duplicate_key` finding; whether `ref remove KEY` removes every duplicate
  sharing that key; where `verify` and `enrich` live. `keys usage` and
  `tex scan` both stay — neither is a subset of the other.

**Gate 4**: contract tests enforce the surface instead of sampling it — a table
test of every command's positional signature; a sweep asserting that each flag
spelling has one meaning; an envelope-schema test over every command's `--json`
output; a test that every emitted error code is catalogued with its exit code;
and a `capabilities` test covering option types, choices, and error codes. The
editor passes against the new envelope (see the editor track).

#### Stage 5 — Hardening and scale

- **Finish the audit.** Not yet covered: the full hostile-input matrix (deep
  nesting, `@string` and `crossref` cycles, invalid and UTF-16 encodings, binary
  input, a closed stdout, invalid option values); the interchange readers (RIS,
  MODS, EndNote, CSV); symlink-following in `corpus combine`'s material copy;
  and the JSON output of `ref import` and `asset fetch`. Any data-loss or
  security finding ships as a 0.6.x patch without waiting for this stage.
- **Scale.** The parser is quadratic — 8,000 entries take 25 s and 20,000 time
  out — through whole-prefix line counting (`_text_utils._line_number`) and a
  linear `EntryStore.__contains__`. This is v0.9's linear parser path, pulled
  forward because real libraries are this size. Also: `normalize` loads 66,000
  journal rows even with journal styling off (about 2.5 s per run), and
  `format` takes 36 s on a single 2 MB field.
- **`scrub` completeness.** `scrub --check` passes a file containing comments
  between entries, `%` lines inside entries, JabRef `comment-<user>` fields
  (which name the user), BibDesk and Mendeley fields (`date-added`,
  `date-modified`, `read`, `rating`, `mendeley-*`), `localfile`,
  `attachments`, `file://` URLs, or home-directory paths in `note`, `@string`,
  or `@preamble`.
- **Pinax keys as paths**: reject `:` (drive-relative on Windows), NUL, reserved
  device names, and over-long keys; detect keys that differ only in case, which
  share one material file on macOS and Windows.
- **Network limits**: an overall deadline beside the per-operation timeouts,
  a size cap on metadata responses (downloads are capped since 0.6.5),
  http(s)-only redirects, refusal of private and loopback addresses, a warning
  on an https → http downgrade, and an arXiv-id shape check before a URL is
  built from one.
- **Durability**: consider `fsync` before the replace; no write path syncs
  today.
- **Correctness gaps**:
  - `keys rename` leaves `crossref`, `xdata`, and `related` pointing at the old
    key.
  - User-supplied values with unbalanced braces are accepted.
  - A mostly-UTF-8 file with one bad byte silently decodes as latin-1; a UTF-16
    file parses as zero entries.
  - A mixed-ending file gains a CRLF at EOF, a CRLF file without a final newline
    gains one, and a whitespace-only file becomes empty.
  - `--backup` overwrites the previous backup.
  - `*notes.bib` is skipped by auto-discovery with a misleading error.
- **Property tests** for invariants the suite currently samples: whole-file
  byte equality including CRLF, BOM, and inter-entry text; a one-field edit
  changes one entry; commit output always parses; `format` and `normalize` are
  idempotent; combine then split round-trips.
- **Test hygiene**: three tests sleep 5 s in real retry backoff; the shared
  HTTP layer (`providers/_http`) sits at 79% coverage.

**Gate 5**: the hostile-input matrix runs in CI with zero tracebacks and zero
invalid JSON; profiling shows no quadratic path in parsing, `lint`, or
`format --check`, and a 20,000-entry library completes each (timings recorded,
not asserted in the correctness suite); the property tests above pass.

#### Stage 6 — Documentation and policy

- **Policy**: the beta promise above, written into
  [docs/guides/public-api.md](docs/guides/public-api.md); a "Breaking" and
  "Deprecated" convention in CHANGELOG (a breaking change shipped in patch
  0.6.2); a stable/experimental marker per command in `capabilities` and in the
  reference.
- **Generated reference**: build the command reference from the live Click tree
  or `capabilities --json`, replacing the hand-maintained parts of
  [docs/guides/usage.md](docs/guides/usage.md). It then covers what is
  documented nowhere today: `metadata remove`, `tex list/remove/clear`,
  `ref remove --keep-files`, `corpus batch --ops-file`, `init --agent-guide`
  (also missing from CHANGELOG), and many options.
- **False claims**: `asset check` does not verify checksums; default
  `normalize` does not abbreviate journals, and the quickstart's table example
  also needs `--journal-style abbreviated`; architecture.md says Pinax is not
  implemented; pinax.md's `add --fetch` and "not a per-invocation flag";
  usage.md's "`--online` is required for every command that reaches the
  network"; the FAQ's "responses are cached"; "`asset check` repair planned".
- **Contract docs** in [docs/guides/llm-integration.md](docs/guides/llm-integration.md):
  the conflict example's `options` shape, the nonexistent `DuplicateDOI` code,
  the nonexistent `out` field, and everything Stage 4 changes.
- **Stale status**: README (twice), docs/index.md, public-api.md,
  installation.md, faq.md (three places), pinax.md, and the `rev: v0.5.0` pin in
  git-workflows.md.
- **Network and privacy page**: what each online command sends and to whom
  (`ref find` sends its free text to Crossref), the User-Agent, the `mailto` the
  docs promise but the client never sends, and `PYNAKES_APS_API_TOKEN`.
- **Smaller fixes**: the completion docs pass a shell name Typer ignores; the
  mkdocs `site_url` is a placeholder and no docs deployment exists; README
  relative links break on PyPI; the README claims conformance "verified against
  TeX Live" while those oracle tests skip in CI; fifteen help texts show literal
  RST double backticks; the agent-evaluation guide moves out of the user
  navigation.

**Gate 6**: `mkdocs build --strict` green; every offline shell example in the
README, quickstart, and usage guide runs in a CI doc test; the command reference
is generated; no document reports an alpha version or status.

#### Stage 7 — Release candidate → 0.7.0

- Publish `0.7.0rc1` to PyPI with the `Development Status :: 4 - Beta`
  classifier and the README status updated.
- Run the agent evaluation harness and dogfood the candidate on real libraries
  (locally; nothing derived from them is committed).
- Between the candidate and 0.7.0, fix regressions only; anything else waits for
  0.7.1 or v0.8.

**Done when**: every stage gate holds; the candidate has run without a data-loss
or contract regression; the editor alpha is published; CHANGELOG updated;
version bumped to 0.7.0.

#### Editor track (alpha)

The extension ships with 0.7.0 as an alpha: a pre-release `.vsix`, labeled alpha
in its README and listing, with no compatibility promise of its own. It is the
first graphical client and the consumer that makes the envelope load-bearing;
its scope is a bibliography belonging to a document or repository being edited,
not library-scoped exploration. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).
The track runs in parallel with the stages above.

- **Move to the beta envelope in the same change as Stage 4**, so the client
  never depends on a form the engine is deprecating — including the `tex scan`
  `action` value it reads today.
- **Use the precondition.** Pass the fingerprint from the preview back on
  commit, so an edit made while the approval dialog is open is not overwritten.
  Treat a `conflict` envelope as not applied: today only `status == "error"`
  counts as a failure, so a conflicted staged edit is silently dropped. Commit
  several staged entries as one `corpus batch` instead of one `ref edit` per
  entry.
- **Thin-client discipline** — no BibTeX parser, metadata schema, or source of
  truth in the client. When the view needs something the engine does not
  expose, the engine grows it; a workaround in TypeScript is a regression even
  when it works.
- **Concurrent development** — until the library-scoped client starts, the CLI
  and the extension evolve together in this repository, so an engine gap and
  its client consumer land in one reviewable change. A second client is what
  would justify splitting them apart.
- **Feature work that does not gate 0.7.0**: group *hierarchy* editing in the
  sidebar (add, rename, move, remove — `groups add-group`, `rename-group`,
  `move-group`, `remove-group`, and `update-group` already exist with
  `--dry-run --diff`), and `asset fetch` from the view under the
  `pynakes.allowOnlineLookups` switch that already covers compare and import.
  Whatever is unfinished carries into v0.8.

**Editor alpha gate**: the `.vsix` is published as a pre-release; its checks run
in CI against the beta envelope; every gap it surfaced was closed in the engine
rather than worked around in the client.

---

### v0.8 — Multi-bib setup, Library, Catalogue, and MCP server

- **`Library` (corpus)**: `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the
  work-matching evidence from v0.6. A Library holds many `.bib` files (many
  pinakes).
- **Cross-library entry operations** — the motions single-file mode can't
  express, built on the `Library` + v0.6 work-matching evidence:
  - **`corpus pick`** — cross-library entry cherry-pick, the missing verb:
    `corpus pick SRC.bib… --keys K1,K2,… --into DEST.bib [--with-materials]
    [--strip-groups | --map-group "Src=Dest"] [--dedupe]`. Pull a focused subset
    out of one or more larger libraries into a target library in a single
    reviewable command, replacing a harvest→strip→combine→re-group script. This
    is the operation the "seed a new library from neighbors" workflow is built on
    and the one entry-level motion with no path today.
  - **`corpus search`** — one query across N libraries with a `[file]` column
    ("which of my libraries already has this?"), surfacing `Library.search` at
    the CLI.
  - **`corpus dedupe` / `dedupe --against other.bib`** — cross-file
    duplicate/identity check so entries are vetted against siblings before a
    transplant.
  - **`ref import --from sibling.bib KEY`** — pull a single entry from a sibling
    library by key without first digging out its DOI (a lighter cousin of
    `corpus pick`).
- **Mirrored-bibliography rename propagation** — pynakes treats every `.bib` in
  isolation, but a common layout keeps a superset bibliography (e.g.
  `bibliography/`) and a working subset copy (e.g. `manuscript/`) that must
  track it; renaming a key in the superset has no way to propagate to the
  mirror today. Needs a declared mirror relationship (naming still open —
  avoid overloading "corpus") and a propagation step for `keys rename` (and any
  other key-changing operation) once that relationship exists. Moved from v0.7,
  where it would have added surface during the freeze.
- **`Catalogue` (index)**: a derived, rebuildable search index (e.g. SQLite FTS)
  over the Library; strictly derived, never a competing source of truth.
- **Single-bibliography analysis**: add a public `pynakes.analysis` API
  namespace and a read-only `analyze` command returning typed and JSON-friendly
  reports for one `BibFile`/`Bibliography`. Start with deterministic descriptive
  measures: entries by type and year, author/journal frequencies, identifier
  and required-field coverage, lint finding counts, group membership, and
  declared linked-file coverage. The report composes the existing
  `lint`/`files`/`filestore`/`identity` result objects rather than
  reimplementing their checks, and is sectioned so the library-wide rollup
  below aggregates it without redesign. Keep analysis offline and separate from
  mutation; do not turn heuristic scores into quality judgments. Deferred here
  from v0.6.
- **Library-wide analysis**: lift the single-bibliography analysis reports over
  `Library`, retaining per-file provenance while adding corpus-wide rollups and
  cross-library coverage/duplication views. Reuse the same typed results rather
  than creating an unrelated statistics implementation.
- **Further import paths**: candidates not yet in the inventory, ordered by the
  size of the community whose canonical identifier is not a DOI: NASA ADS
  (bibcodes; needs a user-supplied API token), RePEc/IDEAS handles, MathSciNet
  review numbers, institutional-repository URN resolvers such as DiVA, and
  SciELO; then ISBN coverage beyond Open Library through a catalogue such as
  WorldCat (Google Books and the Library of Congress are out of scope, per
  [docs/guides/import-providers.md](docs/guides/import-providers.md)).
  OpenReview is held back rather than planned: its public API answers a bot
  challenge to non-browser clients, so importing from it would mean defeating
  that challenge. Revisit only if a documented, key-based API path appears.
- **MCP server**: a thin [Model Context Protocol](https://modelcontextprotocol.io)
  companion on the pinned pynakes API, allowing agents to interrogate a personal
  corpus conversationally — "find papers by X on topic Y", "which entries are
  missing PDFs", etc. Query-only layer over the `Library`/`Catalogue`.
- **Agent surface polish**:
  - **Plan-and-approve workflow**: extend `corpus batch`, which already
    previews and commits a sequence of bibliography operations as one, to
    material and network steps (e.g. "dedupe these → normalize → fetch PDFs"),
    so a whole multi-step plan is approved once.
  - **Post-hoc change summary**: the change plan already counts added, removed,
    renamed, and modified entries; add operation-level counts — "3 keys
    renamed, 12 fields normalized, 2 entries enriched" — so an agent can report
    what happened without re-parsing the diff.
- **`Catalogue`-backed rich query CLI**: `search` gains full-text queries
  against the index; its existing field-scoped terms carry over.
- **Editor toward beta**: whatever of the v0.7 alpha feature work remains, plus
  the library-scoped reads the `Library` makes possible. The extension may
  *read* library-scoped things; it never owns or curates them.
- **Deprecation removals**: the forms deprecated in 0.7.x by the surface freeze
  are removed in 0.8.0, as the beta promise schedules.

**Done when**: `Library`, `Catalogue`, single-bibliography and library-wide
analysis, and the
cross-library entry operations (`corpus pick`/`search`/`dedupe`) shipped with
tests and docs; MCP server published as a companion package; agent-plan and
change-summary features shipped; `pytest && ruff` green; CHANGELOG updated;
version bumped to 0.8.0.

---

### v0.9 — Performance and scale

Measure and improve the offline paths that become important once v0.8 can work
across many bibliographies. Performance claims must be backed by reproducible
results, not estimates. The linear parser path moved to v0.7 Stage 5, because a
single real library already reaches the sizes where it matters.

- **Reproducible benchmark suite**: add generated and fixture-backed corpora at
  documented sizes; measure parse, unchanged write, lint, search, dedupe,
  canonical formatting, bulk surgical edits, Library queries, and Catalogue
  builds. Record the Python version, platform, corpus shape, and peak memory
  alongside timing results.
- **Blocked identity and dedupe matching**: use the shared work-matching
  evidence from v0.6 to build candidate sets by stable identifiers and metadata
  fingerprints; do not compare every unrelated pair with fuzzy title matching.
- **Single-pass bulk edits**: apply recorded source spans in source order rather
  than repeatedly searching and copying the entire bibliography for every
  changed entry.
- **Library and Catalogue profiling**: measure index construction, refresh,
  cross-file search, and identity reconciliation from v0.8; optimize only
  profiles that show material cost.
- **Regression budgets**: establish benchmark baselines before choosing
  thresholds, then gate material regressions in representative offline
  operations without using brittle wall-clock assertions in the correctness
  suite.
- **Evidence-based documentation**: publish only measurements produced by the
  benchmark suite, with their environment and corpus; document known scaling
  limits and do not infer an untested maximum library size.

**Done when**: the benchmark suite and baseline report are published; common
offline paths have no known accidental quadratic scans; dedupe avoids exhaustive
pairwise fuzzy comparison for ordinary nonmatching corpora; benchmarked
regression budgets are enforced; correctness, round-trip, and duplicate-key
tests remain green; CHANGELOG updated; version bumped to 0.9.0.

---

### v0.10 — Ingestion and hygiene breadth

Close the gaps that a cross-check against JabRef and Zotero shows are
conspicuous in a single-file engine: getting an entry *in* from something that
is not already an identifier, and the value-level cleanups both tools ship. All
of it stays single-bibliography work, so it lands before the 1.0 pin rather than
after it. Network access remains explicit and opt-in per the existing rule.

- **`ref from-pdf`** — build an entry from a PDF. Layered cheapest-first: read
  embedded BibTeX and XMP metadata, then a DOI/arXiv id found in the document
  text, then fall back to resolving what was found through the existing
  provider registry. This is the reverse of `ref import` and the most commonly
  cited gap against both tools. Text extraction needs a PDF dependency, so it
  ships as an optional extra rather than a core requirement, and a scanned PDF
  with no extractable identifier must fail honestly instead of guessing.
- **`ref from-text`** — build an entry from a pasted reference string. Offline
  and dependency-free, reporting which fields it recognized and which it could
  not, so a partial parse is visible rather than silently thin. Never emit a
  confident entry from an ambiguous string; leave the uncertain fields out.
- **Journal abbreviation coverage** — the current LTWA seed table plus
  `--ltwa-table` covers the mechanism but not the data. Ship a curated
  abbreviation database so correct behavior is not conditional on the user
  finding a CSV, and widen `JOURNAL_STYLES` beyond `abbreviated`/`full`/`none`
  to the forms competitors expose (e.g. MEDLINE, shortest-unique). Title lists
  are data, not logic: keep them versioned and inspectable.
- **Further `normalize` formatters** — the most-used value-level cleanups from
  JabRef's save actions: HTML entities and markup to LaTeX, Unicode to LaTeX
  and back, and LaTeX markup tidying. These belong to `normalize` because they
  change bibliographic *values*; `format` stays layout-only and must not
  acquire any of them.
- **`asset link`** — scan a directory and match existing files to entries by
  citation key, then by a documented name heuristic, and report the matches for
  approval before writing any link. The batch counterpart to today's
  per-material workflow, and the answer to "I have 500 PDFs and a `.bib`".
  Ambiguous matches are reported, never silently resolved.
- **Richer `dedupe merge` conflict resolution** — JabRef resolves a merge with a
  visual field-by-field diff, which a headless tool cannot copy directly. The
  equivalent is better evidence and finer control: per-field provenance in the
  merge report, an explicit field-level choice rather than whole-entry
  precedence, and a refusal to auto-merge when the evidence is weak. Build it on
  the v0.6 work-matching evidence instead of a second similarity implementation.
- **`saved-search`** — persist a named predicate query in the `pynakes-meta`
  namespace and re-run it on demand, so a `--where` expression becomes a
  durable view instead of shell history. A saved search is a stored query, never
  a stored result set, and never a second source of truth about membership.

**Done when**: `ref from-pdf` and `ref from-text` ship with an optional-extra
boundary for the PDF dependency; the curated abbreviation database and widened
journal styles are in place; the added `normalize` formatters leave `format`
layout-only; `asset link` and `saved-search` ship with tests and docs;
`pytest && ruff` green; CHANGELOG updated; version bumped to 0.10.0.

---

### v1.0 — Launch

**A polished single-file maintenance engine, losslessly JabRef-compatible, with
a pinned public API, released as 1.0.0 on PyPI.** The unit of work is one
`Bibliography` (one `.bib`). The multi-bib `Library`, `Catalogue`, and MCP
server ship in v0.8 as optional companions.

- Stable API, semver promise: the CLI contract, in beta since 0.7.0, and the
  Python API both fall under the semantic-versioning policy in
  [docs/guides/public-api.md](docs/guides/public-api.md).
- All [core architecture invariants](docs/guides/architecture.md#core-invariants)
  intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Beyond 1.0

The data and analysis items stay **in pynakes** as pure bib-file mechanisms.
The remaining GUI item is a separately distributed companion tracked here
because it exercises the pinned integration boundary. Clients divide by
**scope**, not by feature: the project-scoped editor ships as an alpha in v0.7,
and what remains here is the library-scoped client — one serves a bibliography
belonging to a document you are editing, the other a library belonging to no
project at all. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).

- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation.
- **Additional interchange formats** — import/export beyond the existing
  CSL-JSON/RIS/MODS/EndNote/CSV codecs, building on `pynakes.interchange`. The
  cross-check against JabRef and Zotero puts TEI first (digital humanities),
  then Markdown and HTML for documentation workflows, then Wikidata Quick
  Statements for linked-open-data export. Export breadth is additive and low
  risk: each codec is a pure projection that never touches the write path.
  User-definable format filters, as JabRef offers them, are not planned as a
  separate mechanism: pynakes is a library, so `pynakes.interchange` is already
  the extension point for a format we do not ship.
- **Linked-material reference graph** — extract bibliography/reference lists
  from linked paper source or PDFs, resolve their identifiers conservatively,
  and expose the result as a derived citation graph for analysis. Preserve
  provenance and uncertainty; never write inferred references into the source
  `.bib` automatically.
- **Typed entry relationships** — a way to record non-hierarchical links between
  entries ("is review of", "is response to", "extends") that BibTeX's `crossref`
  and `xdata` inheritance cannot express. Zotero's related-items feature is the
  precedent. It needs a metadata model in the `pynakes-meta` namespace and must
  survive round-tripping, which is why it waits for the reference graph above
  rather than arriving as a loose field convention.
- **Material metadata writing** — `asset embed-xmp`: write an entry's
  bibliographic metadata into its linked PDF as XMP, making the file
  self-describing for sharing and archival, and the natural companion to
  reading metadata *out* of a PDF in v0.10. This one modifies a material rather
  than the `.bib`, so it needs the same preview-and-approve treatment as a
  bibliography edit and must never be implied by another command.
- **Further material formats** — EPUB metadata extraction alongside PDF, as
  open-access monographs become common. Lower priority than PDF by usage, and
  it shares the v0.10 extraction pipeline rather than duplicating it.
- **Content-intelligence layers** — full-text extraction, content search,
  RAG/embeddings, and rich agent notes/memory, as an opt-in extra never on the
  bibliography write path.
- **Library-scoped GUI (Bimas, working name)** — a standalone application for
  exploring a generic library: one that belongs to no particular project and
  outlives any workspace. It is *not* a fallback for the extension proving too
  confining. A VS Code custom editor binds a view to a single owned document, so
  library scope is out of the extension's reach however capable it becomes.
  Bimas reuses the same envelope and service boundary rather than gaining a
  bibliography implementation of its own. Starting it is the point at which the
  client layer earns its own repository, and the point by which the integration
  boundary must already be pinned — two clients cannot share an unversioned
  contract.

**Done when**: the core 2.0.0 release is on PyPI with its mechanisms documented.
Bimas is not a 2.0 gate: it begins once the integration boundary is pinned,
which the project-scoped editor in v0.7 is what first forces.

---

## Deliberately out of scope

A cross-check of JabRef and Zotero surfaced features that are **not** planned, so
that their absence reads as a decision rather than an oversight. They are
rejected on fit, not on merit — several are the reason people choose those tools.

- **Shared SQL database backend** (JabRef: PostgreSQL/MySQL with live sync). The
  file is the single source of truth and git is the collaboration story. A
  second authoritative store would contradict the core invariant.
- **Sync services and group libraries with permissions** (Zotero). Same reason:
  version control already provides history, merging, and sharing for plain text.
- **Word processor plugins** (both: Word, LibreOffice, Google Docs). Citation
  *rendering* against CSL styles is a different problem from bibliography
  maintenance, and it is already well served. pynakes stays on the `.bib` side
  of that line; the TeX-facing half is `tex ... scan` and citation navigation.
- **Browser extension with site translators** (Zotero's several thousand
  publisher scrapers). This is genuinely Zotero's strongest feature and it
  requires a browser runtime plus a scraper corpus maintained per publisher.
  `ref import` covers the identifier- and URL-addressable path instead.
- **Reading and annotation UI** (Zotero: PDF/EPUB reader, highlights, notes,
  read-aloud, reflowable view) and **mobile applications**. A different product
  category; nothing about them belongs in a bib-file engine.
- **RSS/journal feed subscriptions** (Zotero). Awareness of new literature is
  adjacent to, not part of, maintaining a bibliography.
- **Quick one-off bibliography generator** (ZoteroBib). A different audience:
  users who explicitly do not want a library to maintain.
- **Configurable material filename patterns** (JabRef's `[citationkey] - [title]`
  style patterns; Zotero's continuous renaming as metadata changes). Pinax
  addresses materials *by citation key* — `<key>.<kind>` is the lookup, not a
  cosmetic default — so user-defined naming would remove the property the whole
  store depends on, and renaming on every metadata edit would make the file
  layout a moving target under version control. The legitimate want beneath it,
  human-readable filenames for sharing, belongs to an export or copy operation
  that names files on the way out, leaving the store addressable.
- **Cite-as-you-write HTTP daemon on a fixed port** (JabRef, port 23119). The
  need is real, but the MCP server in v0.8 and the editor in v0.7 both address
  it over boundaries that already exist, without a background service listening
  on a well-known port.
