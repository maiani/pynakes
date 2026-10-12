# pynakes development plan

pynakes is a **reference management engine for BibTeX and BibLaTeX bibliographies and their research materials**,
exposed through a Python library and CLI. The product ambition is to support a
research library throughout its life: reference acquisition and curation,
material provenance, project bibliographies, manuscript citation maintenance,
and public release copies.

The current foundation is one authoritative `Bibliography` (`.bib`), optional
Pinax materials, and explicit operations across files. The next planned step
extends that foundation to `Library`, a rebuildable `Catalogue`, and analysis
across collections. Applications for capture, reading, graphical interaction,
and sync consume the same engine; they share its parser, data model and review
contract. Planned integrations are tracked here without being advertised as
implemented features.

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
then-current `[[tool.mypy.overrides]]` list, since replaced by the ty baseline).
Actions are referenced by major version tag, by choice, rather than pinned by
commit SHA. Running the release workflow by hand is a dry run; its TestPyPI
option needs a `testpypi` environment and a trusted publisher on test.pypi.org
first.

**Gate 2** (met, 2026-10-01): the full matrix is green, the lowest-dependency
job included; a release dry run passed every new check.

#### Stage 3 — Cleanup before the freeze

Done: the deletions, consolidations, renames, and splits are recorded in
CHANGELOG under Unreleased. Decisions taken along the way:

- Of the `Bibliography` methods no command calls, only `import_doi` went; the
  Python API is its own interface, and `journals_check`,
  `abbreviate_journals`, `expand_journals`, and `rename_citekey` are
  conveniences nothing else in it covers.
- The Pinax `preprint_canonical` flag was removed rather than finished: nothing
  could set it. A setter is an addition that can return after the freeze.
- `importer` fell to 589 lines with its dead arXiv helpers gone, so its arXiv
  section stayed put.
- Splits keep public names defined in, or listed in `__all__` of, their public
  module, so the generated API reference is unchanged: `canonical` lost its
  field-order table and value wrapping, `lint` its issue type and profile
  checks, `filestore` its manifest (a mixin), `metadata/jabref` its group
  grammar.

**Gate 3** (met, 2026-10-04): no module over 800 lines (the largest is
`fetch.py`, 789); vulture at 80% confidence reports nothing; the suite and the
90% coverage floor hold.

#### Stage 4 — Freeze the surface

The one deliberate batch of breaking CLI changes, so the promise starts from a
consistent surface. The renamed and reordered forms are removed outright in
0.7.0, with no aliases: nobody depends on them yet, and the beta promise —
deprecation before removal — applies from 0.7.0 onward.

**Done** (on branch `stage-4-freeze`, 2026-10-05 to 2026-10-09; recorded in
CHANGELOG under Unreleased): library-first positionals with `--file`/`-f`
on every single-library command and syntactic library detection
(`pynakes.cli_surface`); one meaning per
flag and one flag per concept; enumerated options as Typer choices
(`pynakes.cli_choices`); the beta envelope (`action` naming, warning objects,
`file`/`out`, `summary`, `source_sha256` everywhere, `--expect-sha256` on every
modifying command); usage errors exit 1 and human errors on stderr; one error
catalogue (`pynakes.cli_errors`) that fixes each code's exit code and generates
`capabilities`; the overwrite policy; the group validations; batch error codes.

Decisions taken:

- `--strict` and `--check` stay two flags with one meaning each: `--strict`
  gates a command that is read-only anyway (`lint`, `verify`, `dedupe check`,
  `keys check`, `asset check`); `--check` is the check mode of a transform
  (`format`, `scrub`), which then writes nothing. Envelopes report `strict` or
  `check` accordingly.
- `-f` is `--file` everywhere; `--field` means a `name=value` assignment
  (`ref add`/`ref edit`), and the field-*name* options got distinct names.
- `--published` keeps one meaning, "consider preprints' published versions":
  `verify` reports them, `enrich` applies them; `asset fetch` moved to
  `--material`.
- `--out PATH|-` is the one output flag; `format --stdout` became `--out -`.
- `ref remove KEY` refuses a key shared by several entries
  (`DuplicateCitationKey`), as `ref show`/`ref edit` do; `keys repair` first.
- `groups add-entry` refuses an unknown group unless `--create`, which the
  editor's "New group…" flow needs; batch `groups.add_entry` takes `create`.
- `scrub --out` naming its own input (in-place scrub) needs no `--force`.
- `corpus batch` operations report the standalone command's error codes
  (`KeyNotFound`, `DuplicateCitationKey`, `CitationKeyConflict`) with `index`.
- For lint gating in a commit hook ([#2](https://github.com/maiani/pynakes/issues/2)):
  entry-type case is `format-entry-type-case`, not a `lint-` key — settings are
  named for the command that applies them and `lint` verifies them, as it
  verifies the `normalize-*` keys, so a layout finding fires exactly when
  `format` would change the source (field-name case follows the same rule if it
  ever gets a setting). Rule selection is one `--ignore NAME` taking a finding
  type or a category, mirrored by one `lint-ignore` key; the command applies it,
  and the `lint()` function keeps returning every finding.
- `asset check` is a pure read-only gate; reconciling the Pinax manifest moved
  to `asset repair`, with `--dry-run`/`--diff`, mirroring
  `keys check`/`keys repair`.
- `keys check` stays beside lint's `duplicate_key`: it gates on key uniqueness
  alone, which `lint --strict` no longer can, and is the read side of
  `keys repair`.
- `verify` and `enrich` stay top-level: they are the online counterparts of
  `lint` (diagnose) and `normalize` (change content). `keys usage` and
  `tex scan` both stay — neither is a subset of the other.
- No project-level config (`pynakes.toml`, `[tool.pynakes]`) in 0.7: the `.bib`
  carries its own settings and every client reads them there. Revisit with the
  v0.8 `Library`, whose directory is the natural home for shared defaults.
- The Gate 4 contract tests are in `tests/test_contract.py`, read from the live
  command tree: the positional table, one shape per flag spelling (`--key` and
  `--title-field` are the recorded exceptions), an offline `--json` sample per
  command checked against its envelope family (modify, create, read, check,
  error; `corpus split` reports `outputs`), error codes catalogued both ways,
  and `capabilities` matching the parsed options.
- `lint --strict` fails on any finding left after suppression, not only on
  errors and profile deviations: every other gate already failed on any
  finding, and once findings can be suppressed explicitly, "strict" can mean
  clean. `--where` on `ref directive` is how an existing library adopts it.
- A setting for one entry is a directive comment directly above it
  (`% pynakes: verb args -- reason`), not a `pynakes-*` field: library settings
  already live in a comment, and a field would carry tool instructions into
  exports, interchange formats, and public copies. Both forms survive JabRef
  (checked with JabKit 6.0-beta.1), so JabRef did not decide it. One generic
  `ref directive` writes every verb, so a new directive adds a word to the
  grammar, not a command to the frozen surface.
- The pre-0.7 forms are removed, not deprecated (2026-10-09): an old order or
  spelling is a `UsageError`, and `capabilities` lists no deprecations.
  `tests/test_cli_surface.py` checks that each one fails.
- The editor moved to the library-first order and the beta envelope in the same
  branch, with real-engine contract tests for the calls it makes.

**Gate 4**: contract tests enforce the surface instead of sampling it — a table
test of every command's positional signature; a sweep asserting that each flag
spelling has one meaning; an envelope-schema test over every command's `--json`
output; a test that every emitted error code is catalogued with its exit code;
and a `capabilities` test covering option types, choices, and error codes. The
editor passes against the new envelope (see the editor track).

**Gate 4** (met, 2026-10-09): `tests/test_contract.py` enforces all five; the
editor's real-engine contract tests pass against the 0.7 surface. Behavior
tests the gate did not require moved to Stage 5.

#### Stage 5 — Hardening and scale

**Closed (2026-10-12).** The completed changes are recorded under Unreleased
in CHANGELOG.

**Done and verified locally:**

- **Scale:** the linear parser/key-index fixes remain in place. The latest
  `scripts/bench_scale.py` run on synthetic libraries measured:

  | Entries | Parse | Lint | `format --check` |
  | ---: | ---: | ---: | ---: |
  | 4,000 | 0.40 s | 1.40 s | 2.31 s |
  | 20,000 | 2.00 s | 6.97 s | 11.56 s |

  These are measurements from one machine, not timing assertions. Each path
  scales approximately with the entry count. Constant-factor work remains for
  v0.9; the previous large-field measurement is recorded in the git history.
- **Scrub:** remove additional JabRef, BibDesk and Mendeley private fields,
  recognizable local paths in fields/strings/preambles, plain inter-entry
  working text, and comment lines inside entries. Preserve literal percent
  signs in values and the explicit keep switches. Repeated staged scrubs use
  original source positions. Regression tests exercise preview and commit.
- **Pinax paths:** refuse drive-relative and invalid Windows names, NUL/control
  characters, reserved devices and over-long keys; refuse case-colliding
  citation keys. Material copying refuses source-tree and destination artifact
  symlinks before copying. Source-directory installation also refuses symlinks.
- **Network policy:** default HTTP transport validates every redirect, refuses
  non-HTTP(S), credentials, private/loopback destinations and mixed DNS results,
  pins the validated IP while retaining Host/TLS names, and warns on HTTPS to
  HTTP redirects. Metadata responses have an 8 MiB cap; material downloads retain
  their 512 MiB cap. Retry/redirect/stream progress checks share a deadline.
  arXiv URL helpers validate modern and historical identifier shapes.
- **Durability:** sync files and directories inside a source tree before its
  atomic installation; use a synced, atomic, numbered manifest backup.
- **Correctness:** rename fully braced entry references; make wrapping's brace
  accounting agree with the parser; validate externally supplied field values
  before mutation/entry construction. Completion and previous-output diffs use
  detected library encodings; interchange imports also recognize BOM/Latin-1.
  `asset check` already uses `Bibliography.open`, so its library read was fixed.
- **CLI behavior tests:** overwrite refusal and `--force` for every output
  command, `format --out` and stdout, conversion import diffs/digests with
  encoded inputs, ambiguous `ref remove`, multi-file catalogued error codes,
  invalid option choices, and closed stdout without a second error-envelope
  attempt. Existing import/fetch JSON tests remain passing.
- **Property tests:** whole-file byte equality with CRLF/BOM/encodings; one field
  edit changes one entry; committed edits reparse; format/normalize idempotence;
  combine then split preserves entries and their raw source. These extend the
  existing arbitrary-input parser properties.
- **Module sizes:** source-span handling moved out of `_engine_helpers.py`;
  scrub source staging lives in a focused helper. Every Python module remains
  below 800 lines. `fetch.py` and `normalize.py` are still near the limit and
  must be split before adding substantial behavior there.
- **Python 3.15:** declared supported, required on Linux/Windows/macOS in CI,
  and included in release wheel testing. A locally built final Python 3.15.0
  ran the complete suite and coverage gate. Remote CI has not been run for
  these uncommitted changes.
- **Type checker:** ty replaces mypy in the dev extra, CI, pre-commit and
  developer instructions. Ty 0.0.86 is pinned and passes with a per-module,
  per-rule baseline of 118 existing diagnostics across 30 modules. The initial
  trial found 134 diagnostics; annotation corrections and removal of an
  unreachable compatibility fallback reduced it. The baseline must shrink,
  never grow; see [the type-checking guide](docs/guides/type-checking.md).

- **Hostile-input matrix:** `tests/test_hostile_input.py` runs Hypothesis
  properties over CSL-JSON, RIS, EndNote and MODS of arbitrary shape. Each
  importer returns a reparseable library or raises `ValueError`, and nothing
  else. The file also covers specific refused and tolerated files through
  `convert --from`, CSV's export-only boundary (now documented in usage), and
  13 failed provider responses through `ref import`, plus a recovered throttle
  and a mixed batch. Every case must yield a JSON envelope with no traceback
  and leave the library untouched. The audit found and fixed `TypeError`,
  `RecursionError` and raw XML parse errors. XML with entity declarations is
  refused in MODS, arXiv and NCBI responses.
- **Network deadline:** DNS resolution runs on a daemon thread bounded by the
  deadline. A deadline-aware httpcore network backend gives each socket read
  and write only the time left, so trickled headers end at the deadline. A
  socket-pair test hangs without the backend. Injected openers are read in
  bounded `read(size)` chunks: the cap holds without buffering the whole body,
  and the deadline is checked between chunks. The architecture guide documents
  this contract.
- **HTTP-layer tests:** `tests/test_http_layer.py` covers cached-JSON
  failures, metadata status and stream failures, opener caps and deadlines,
  and retry boundaries. `_http.py` coverage rose from 83% to 89%.

- **Remote CI:** CI run 38228820300 (commit 8085707) is green on all 17
  jobs. They cover Python 3.12–3.15 on Linux, Windows and macOS, the
  lowest-dependency job, lint and ty, strict docs, distribution, and the
  editor extension. The first run found Windows-only failures, all fixed: a
  source-tree sync that failed with `EBADF` (a real bug), and tests that
  assumed POSIX directory syncs, untranslated newlines, or short test ids.

**Gate 5** (met, 2026-10-12): the full hostile-input matrix runs in CI on
every platform, with zero tracebacks and valid JSON whenever stdout is
available. The scale and property-test requirements pass. Closed stdout
deliberately exits 1, because no envelope can reach a reader that has gone
away.

#### Stage 6 — Documentation and policy

Implemented (2026-10-12): compatibility and CHANGELOG deprecation conventions,
per-command stability markers, a command reference generated from the live
Click tree, executable offline documentation walkthroughs, and a network/privacy
guide. Current engine docs describe the beta target and the actual normalization,
Pinax, network, cache and JSON behavior. README links work outside the repository;
shell completion and terminal help no longer carry misleading syntax. The
placeholder site URL was removed; no hosted documentation deployment is claimed.
See [CHANGELOG.md](CHANGELOG.md) for the completed changes.

**Gate 6** (met, 2026-10-12): `mkdocs build --strict` passes;
every offline shell example in README, quickstart and usage runs in
`tests/test_doc_examples.py` with network access blocked; the generated command
reference is checked for drift; current engine documents report no alpha status.
The CI documentation job runs these tests before building. Commit `3a8642d`
passed all 17 jobs in [CI run 38232952387](https://github.com/maiani/pynakes/actions/runs/38232952387),
including the full platform matrix, lowest dependencies and editor checks.

#### Stage 7 — Engine readiness, then editor, then coordinated publication

- Prepare **pynakes 0.7.0 Beta** first: Beta metadata, release notes, built-wheel
  CLI contract/workflow tests, and disposable-copy dogfooding. Local RC builds
  may support validation; no separate PyPI RC publication is required.
- Once engine readiness is established, move to the editor and finish the
  **0.1.0 Alpha** acceptance and packaging gates against that engine.
- Publish **0.7.0 Beta and editor 0.1.0 Alpha together**, after both are ready.
  Do not publish the engine while editor readiness is still open.
- Record manual agent acceptance independently of automated engine tests. The
  former hand-run agent evaluation harness was deliberately removed in
  `0ef2951`; it is not an available release check.
- During release-candidate observation, fix regressions only; new features wait
  for 0.7.1 or 0.8.

**Done when**: every stage gate holds; candidate use has shown no data-loss or
contract regression; both distributions are published in the coordinated
release; CHANGELOG updated; the engine tag names 0.7.0.

**Preparation**: Beta metadata, release notes and the checklist are in
[RELEASE.md](RELEASE.md). Local builds use temporary setuptools-scm overrides;
preparation creates no release tag. Manual acceptance, remaining editor work,
and coordinated publication remain open.

**Local engine preflight (2026-10-12)**: the installed 0.7.0rc1 wheel passed
all 2,921 tests without a checkout source tree. Disposable copies of two real
libraries (272 entries total) passed round-trip, layout semantic equality and
normalization idempotence checks; originals stayed unchanged. Final-version
0.7.0 Beta rehearsal wheel/sdist metadata and version checks passed. Source
Ruff, formatting, ty and strict docs passed. The built-wheel audit exposed and
fixed a test that had assumed `src/` was present. Logs, hashes and artifacts
remain local under `.cache/stage7/`. This is scoped automated/agent-driven
smoke validation, not a formal agent benchmark or a publication claim.

**Next**: review/commit these preparation changes when authorized and validate
that commit in CI, then finish editor acceptance and remaining work. An early
editor packaging rehearsal passed 82 tests and produced a verified 0.1.0
prerelease VSIX bundling the RC. A second rehearsal (2026-10-12) bundled the
engine as 0.7.0, built with Python 3.12, and verified the pre-release and
preview markers, the bundle's reported version, and the launcher. A third
rehearsal, after the alpha features and the bug-fix audit, passed 114 editor
tests and 3,025 engine tests and verified the same markers. All are drafts,
not the editor release: it must be rebuilt from the clean release commit
against the ready 0.7.0 Beta engine.

#### Editor track (alpha)

The extension ships with 0.7.0 as an alpha: a pre-release `.vsix`, labeled alpha
in its README and listing, with no compatibility promise of its own. It is the
first graphical client and the consumer that makes the envelope load-bearing;
its scope is a bibliography belonging to a document or repository being edited,
not library-scoped exploration. See
[Graphical clients and their scope](docs/vision.md#graphical-clients-and-their-scope).
The track runs in parallel with the stages above.

- **Move to the beta envelope in the same change as Stage 4.** *(Done on
  `stage-4-freeze`: library-first arguments, the renamed actions, `lint` counts
  under `summary`, and `groups add-entry --create`.)*
- **Thin-client discipline** — no BibTeX parser, metadata schema, or source of
  truth in the client. When the view needs something the engine does not
  expose, the engine grows it; a workaround in TypeScript is a regression even
  when it works.
- **Concurrent development** — until the library-scoped client starts, the CLI
  and the extension evolve together in this repository, so an engine gap and
  its client consumer land in one reviewable change. A second client is what
  would justify splitting them apart.
- **Alpha feature work** *(done for 0.1.0; see CHANGELOG)*: group hierarchy
  editing in the sidebar, with renames carrying members
  (`groups rename-group --members`), and `asset fetch` from the view under
  `pynakes.allowOnlineLookups`.
- **Open after the 0.1.0 audit** (not gating the alpha unless noted):
  - *Groups-field separator:* pynakes reads and writes `groups` memberships on
    `;`, while JabRef's default keyword separator is `,`. A multi-group entry
    from a default JabRef setup reads as one group. Decide how the separator
    is declared or detected before 1.0.
  - *Opening materials:* a `file`-field path is handed to the OS handler; on
    Windows an executable named by an untrusted `.bib` could run. Decide on an
    allow-list or a confirmation.
  - *Fetch progress:* the engine reports no per-file progress in `--json`
    mode, and the view does not offer `--access institutional`.

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
- **More per-entry directives.** `% pynakes: ignore` shipped with the
  `ref directive` writer (see CHANGELOG); each further verb is a word in the
  same grammar, not a new command. Candidates, each the per-entry form of a
  library setting or a recurring false positive: `distinct-from KEY` for a pair
  `dedupe check` flags but that are different works (the same commit-hook
  problem #2 raised for lint); `no-fetch` or a per-entry fetch policy for
  `asset fetch`; `keep-key` against key regeneration; and an opt-out from
  `enrich` when a provider's record for the work is wrong. `ref show` could list
  an entry's directives.
- **Type spelling of new entries** (only if asked for): under
  `format-entry-type-case: preserve`, `ref add` and `ref import` still write
  `@book`, so a JabRef library mixes spellings until JabRef next saves it. A
  JabRef spelling value for the setting, or a `consistency` finding for mixed
  spellings of one type, would close that.
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

**A reference management engine with a pinned public API and a dependable
workflow from reference acquisition to project bibliography and release copy.**
Published as 1.0.0 on PyPI, it preserves authoritative files and interoperates
with JabRef. `Bibliography` remains the basic working unit; the planned v0.8
`Library`, `Catalogue` and MCP integration extend its reach across collections.

The launch must document and exercise the complete workflows, including
reference curation, material provenance and manuscript citation maintenance,
through the same Python API and CLI. Release claims follow verified behavior
and completed gates.

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
