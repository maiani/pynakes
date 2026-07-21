# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Any application built on top of it (capture, reading,
a UI, sync) is a **separate, downstream project** and is explicitly not in this
plan.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Current state (v0.5 alpha — pre-release)

v0.5 is the first public alpha release. The single-file engine has broad coverage,
but v0.5 is not feature-complete until the bibliography-formatting gate below is
closed. Input conformance is verified against the TeX Live 2026 baseline (BibTeX
0.99d, BibLaTeX 3.21, Biber 2.21). Until v1.0, pynakes does **not** guarantee
backward compatibility for the Python API, CLI syntax, or JSON envelopes.

Key shipped capabilities:
- **Parser/writer**: byte-for-byte round-trip fidelity; atomic, re-parse-validated
  writes; surgical minimal-diff editing. Handles all BibTeX/BibLaTeX constructs
  including `crossref`/`xdata`/`xref`/sets inheritance.
- **`engine.Bibliography`**: load → stage → preview/diff → commit lifecycle;
  external-change detection.
- **Operations**: `init`, `inspect`, `lint`, `groups`, `keys`, `fields`,
  `convert`, `format`, `normalize`, `ref add`/`ref import`, `search`, `tex scan`,
  `dedupe`, `verify`/`enrich`, `asset check`/`fetch`, `remove`, `metadata
  list`/`set`, `corpus combine`/`split`/`batch`.
- **Pinax corpus mode**: `FileStore`, arXiv download, provenance manifest,
  open-access PDFs, DOI→arXiv backfill, material merge on dedupe, coordinated
  key edits, pinax-aware combine/split.
- **JabRef v5.15 interop**: metadata vocabulary near-full (16 exact + 3 prefix
  keys recognized; rare/missing keys preserved verbatim); `saveActions` formatter
  suite includes the offline-compatible v5.15 formatters (`short_doi` is
  intentionally unsupported because JabRef implements it via shortdoi.org);
  key patterns include `authorlast`, `authIniN`, `authorIni`, and `authorsN`;
  formatters-as-modifiers remain partial; group management is at full parity (all four group
  types with native `group-tree` metadata and dynamic expression evaluation);
  `saveOrderConfig` sort includes duplicate-safe BibTeX crossref ordering.
- **Agent-native surface**: structured JSON envelope + exit codes, `--dry-run`/
  `--diff`/`--json`, structured `plan` objects, `capabilities`, multi-file
  `--strict` gates, `.pre-commit-hooks.yaml`, shell completion.
- **Parser conformance**: versioned corpus pinned to TeX Live 2026; differential
  tests against BibTeX 0.99d and Biber 2.21; property-based tests (Hypothesis).
- **Quality**: ~1227 tests, coverage ≥90%, `ruff` clean, docs site builds.

---

## Remaining v0.5 work (pre-ship)

All of these block the v0.5.0 tag.

- [x] **Complete bibliography formatting.** pynakes must be sufficient as the
      final formatting and maintenance tool for a `.bib` file; requiring a
      second formatter such as tex-fmt is not acceptable for v0.5. This is an
      explicit, parser-aware formatting path, separate from the default
      preservation behavior.
  - [x] Add canonical layout formatting as the dedicated top-level `format`
        command. `normalize` remains content-only, while ordinary commands
        retain byte-for-byte round-trip fidelity and surgical diffs.
  - [x] Canonical layout controls indentation, spaces versus tabs, one field
        per line, spacing around `=`, trailing
        commas, blank lines between entries, and deterministic entry/field
        layout. Field ordering and alignment are configurable through CLI flags.
        Values are deliberately not wrapped.
  - [x] Formatting is BibTeX/BibLaTeX- and TeX-aware: it does not change brace
        grouping, capitalization protection, macros, quoted/braced atoms,
        concatenation with `#`, names, URLs, or field meaning.
  - [x] Canonical formatting preserves and deterministically places comments,
        `@string`, `@preamble`, duplicate citation keys, unknown entry/field
        types, BibLaTeX constructs, and pynakes/JabRef metadata. It must not
        rebuild solely from a lossy field dictionary.
  - [x] Provide formatter workflow parity needed by editors and CI: check-only
        mode with a meaningful exit status, stdout/print mode, stdin support,
        recursive or explicit multi-file operation, dry-run, unified diff,
        JSON reporting, and atomic writes with backups.
  - [x] Formatting is deterministic and idempotent: a second run produces no
        changes. Parse -> format -> parse must preserve the bibliography's
        semantics under both BibTeX and Biber validation.
  - [x] Add golden and fixture-wide tests for
        operational/layout parity, while improving on tex-fmt with semantic
        parsing. Cover malformed-input failures without tracebacks and protect
        every existing round-trip/minimal-diff invariant in preserve mode.
  - [x] Document the deliberate boundary: canonical layout is an explicitly
        requested whole-file rewrite; all other modifying operations continue
        to use surgical edits and preserve unrelated source text.
- [ ] **Finish JabRef bibliography-formatting parity.** Implement and test all
      remaining v5.15 `saveActions` field formatters, formatter ordering and
      formatter-as-modifier behavior, remaining key-pattern markers/modifiers,
      and crossref-parent ordering for `saveOrderConfig`. Use upstream JabRef
      implementations, tests, and golden vectors as the behavioral oracle;
      unsupported future formatter names still produce structured warnings.

- [x] **Group tree CLI — `groups list-entries` with descendant propagation.**
      Wired as `groups list-entries <name>` with descendant propagation as
      default (`--strict` opt-in for exact-match only). Dynamic groups
      (KeywordGroup/SearchGroup) are evaluated at query time.
      (`cli_commands/groups.py`)
- [x] **`metadata remove` command.** `metadata remove <key> [file]` deletes a
      single `pynakes-meta` or `jabref-meta` entry, auto-detecting the target
      namespace or accepting an explicit `--namespace`. Reports which namespace
      the key was removed from.
      (`cli_commands/metadata.py`)
- [x] **`init --json` is fully non-interactive.** The `--json` flag is marked
      `is_eager=True` to ensure error output is always JSON when requested.
      All configurable options have a non-interactive CLI path.
      (`cli_commands/init.py`)
- [x] **`verify`/`enrich` help and docs clarify the split.** `verify` checks
      entries against authoritative online sources without modifying the file.
      `enrich` updates entries from those sources. Both accept `--published`
      and `--online` but with different intent. Ensure `--help` and the LLM
      integration guide make this distinction explicit.
- [x] **Bug: metadata-only `groups` changes never commit.** `groups add-group`
      (and `remove`/`move`/`rename-group`) reported success on a fresh
      `group-tree` but wrote nothing: the surgical renderer emits only staged
      `(old_raw, new_raw)` metadata replacements, and group-tree CRUD mutated the
      model without staging (`--json` showed `modified: false`,
      `metadata_changed: 1`). Fixed at the root: the engine snapshots raw comments
      alongside entries and derives metadata edits at render time, so supported
      metadata mutations cannot be omitted by a caller that forgets separate
      staging bookkeeping and the CLI can bootstrap a tree.
- [x] **Bug: identical source blocks lose positional identity during edits.**
      Surgical rendering used first-match string replacement, so editing the
      second byte-identical duplicate entry could rewrite the first even though
      `change_plan()` identified the second occurrence. The engine now snapshots
      exact source spans for entries and comments and applies validated edits by
      offset. `is_dirty` is likewise derived from actual output or pending Pinax
      transactions, avoiding false dirty state after semantic no-ops.
- [x] **Bug: `corpus combine --out X` fails when `X` is also an input.**
      Self-combine aborted with a `SameFileError` copying a pinax material onto
      itself. Fixed: `FileStore.copy_materials_from` skips a copy whose source
      and destination resolve to the same file (`filestore.py`); a self-combine
      keeps the input's own `files-dir` instead of deriving it from `--out`, and
      a non-self combine that changes `files-dir` now warns
      (`cli_commands/setops.py`).
- [x] **Bug/UX: `keys rename`/`generate` hard-fails with no TeX sources.** Fixed:
      the flawed `require_sources` gate is gone — no configured sources is a
      zero-update success with a warning, while explicitly passing sources that
      resolve to no `.tex` files still errors (`cli_commands/keys.py`).
- [x] **Bug: `groups add-entry` left orphan memberships out of the tree.** Adding
      an entry to a group absent from an existing `group-tree` wrote the entry's
      `groups={}` field but never registered the group as a node, so the
      membership was invisible to `groups tree`, `groups list` (which defers to
      the tree), and JabRef — with no warning. Fixed: when a tree exists,
      `add-entry` registers the group as a node so the views agree
      (`_engine_groups.py`); flat, tree-less libraries keep entry-field-only
      groups.
- [ ] **Final changelog and version bump.** Tag v0.5.0.
- [x] **JabRef parity audit correction.** README.md's "full JabRef metadata
      parity" replaced with "broad JabRef metadata interop" and a component
      breakdown. DEVPLAN.md and `capabilities.py` already reflected the actual
      state accurately (no "full parity" overclaim). Groups continue to be
      described at full parity (accurate — all four group types with native
      metadata and dynamic evaluation).

**Done when**: all items checked off; preserve mode remains byte-for-byte and
minimal-diff; canonical formatting is idempotent and BibTeX/Biber-equivalent;
the complete CLI/JSON/check workflow is documented; `pytest && ruff` green;
CHANGELOG updated; version bumped to 0.5.0.

---

## Road to 1.0

### v0.6 — Generalization and consolidation

Generalize import paths beyond DOI/arXiv and consolidate the engine's
cross-cutting patterns.

- **New import paths**: PubMed PMID/PMCID, ISBN, SSRN ID, NBER ID, generalized
  journal-URL resolver table covering common publisher patterns.
- **Generalized URL import**: `ref import <url>` auto-detects identifier type
  from any supported publisher/catalog URL (DOI, arXiv, PubMed, SSRN, NBER,
  ISBN, nature.com, journals.aps.org, plus the new Elsevier/Springer/Wiley/PLOS
  patterns) and resolves it through the appropriate provider, normalizing the
  result into a uniform metadata dict.
- **Richer `search` + `--where` grammar**: fuzzy title matching, date-range
  filtering, "entries missing field X" queries, search-result JSON with match
  explanations. Extend the `--where` grammar (shared by `search`, `fields`, and
  `corpus split`) beyond single predicates to boolean `and`/`or`, `key in [...]`,
  and numeric comparison (`year >= 2025`) — covers common agent facepalms
  without writing ad-hoc grep.
- **Multi-entry triage view**: `ref show --keys k1,k2,… [--abstract]` (or
  `search --show-abstract`) to scan a set of candidate entries in one call
  instead of one invocation per key.
- **`metadata doctor [--fix]` + metadata-aware `lint`**: rename known-legacy
  metadata keys to their current spelling, validate enum *values* (catch typo'd
  policy tokens), flag `[pynakes:unknown:*]` keys, and collapse duplicate
  metadata blocks — today metadata drift passes silently.
- **`init --from` / `metadata adopt-profile`**: `init --from other.bib` on an
  existing pinax file should merge in the missing maintenance-profile keys
  (dialect, key-pattern, normalize-keys, sort-order) rather than no-op;
  alternatively add `metadata adopt-profile --from other.bib` for coherent
  multi-library setups.
- **Quieter `lint` consistency heuristic**: scope the "missing field X vs peers"
  check within entry-type *and* identity class (preprint/published/book/code),
  or gate it behind `lint --consistency`, so healthy libraries don't bury real
  issues under peer-consistency noise.
- **`asset fetch`/`check` file targeting**: a `--all`/`--file` form to operate
  on every entry in a specific library when sibling `.bib` files share the
  directory (today the first positional is read as a citation key, and bare
  auto-detect fails with multiple `.bib` files present).
- **Cross-cutting consolidation**: unify interface patterns, reduce duplication
  across import, identity, and metadata pathways.

**Done when**: broader import paths, richer `search`/`--where`, `metadata
doctor`, and the `lint`/`groups`/`asset` UX fixes implemented, tested, and
documented; `pytest && ruff` green; CHANGELOG updated; version bumped to 0.6.0.

---

### v0.7 — Shared identity

Promote the DOI / arXiv / OpenAlex / ORCID / title machinery (currently spread
across `dedupe`, `verify`, and `add`) into one explicit, tested primitive. This
is the foundation for dedup, the `Library`, Catalogue, and projection
reconciliation — everything keys off a single notion of "the same work".

**Must include**:
- **Identity primitive**: a `Work` type that unifies identifier resolution
  (DOI, arXiv, OpenAlex ID, ORCID) with metadata fingerprinting (title hashing,
  author normalization) so any consumer answers "is this the same work?" through
  one tested path.
- **Refactor consumers**: `dedupe` uses the primitive for its similarity
  heuristic; `verify`/`enrich` use it for online-lookup routing; `ref import`
  uses it to reconcile metadata from multiple sources.

**Done when**: identity primitive shipped with tests and docs; consumers in
`dedupe`, `verify`, and `add` refactored to use it; `pytest && ruff` green;
CHANGELOG updated; version bumped to 0.7.0.

---

### v0.8 — Multi-bib setup, Library, Catalogue, and MCP server

- **`Library` (corpus)**: `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the identity
  primitive from v0.7. A Library holds many `.bib` files (many pinakes).
- **Cross-library entry operations** — the motions single-file mode can't
  express, built on the `Library` + v0.7 identity primitive:
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
- **`Catalogue` (index)**: a derived, rebuildable search index (e.g. SQLite FTS)
  over the Library; strictly derived, never a competing source of truth.
- **MCP server**: a thin [Model Context Protocol](https://modelcontextprotocol.io)
  companion on the pinned pynakes API, allowing agents to interrogate a personal
  corpus conversationally — "find papers by X on topic Y", "which entries are
  missing PDFs", etc. Query-only layer over the `Library`/`Catalogue`.
- **Agent surface polish**:
  - **Plan-and-approve workflow**: allow composing multi-step operations
    (e.g. "dedupe these → normalize → fetch PDFs") into a single structured
    `plan` that the user approves once.
  - **Post-hoc change summary**: every mutating command emits a human-readable
    and machine-parseable summary alongside the diff — "3 keys renamed,
    12 fields normalized, 2 entries enriched" — so an agent can report what
    happened without re-parsing the diff.
- **`Catalogue`-backed rich query CLI**: `search` gains full-text and
  field-scoped queries against the index, not just raw entry iteration.

**Done when**: `Library`, `Catalogue`, and the cross-library entry operations
(`corpus pick`/`search`/`dedupe`) shipped with tests and docs; MCP server
published as a companion package; agent-plan and change-summary features
shipped; `pytest && ruff` green; CHANGELOG updated; version bumped to 0.8.0.

---

### v0.9 — Testing release

- **First stable pre-release**: bump to **0.9.0**, sync `capabilities.VERSION`,
  `twine upload`, tag `v0.9.0`, point the pre-commit hook `rev:` in docs at it.
  Gather feedback before committing to the 1.0 API.
- A 30-second demo (asciinema/GIF): "messy `.bib` → clean `.bib` with a
  reviewable diff", and an agent cleaning a bibliography via pynakes.
- Lead the README/launch with the agent-tool + reviewable-diff story.
- Zenodo DOI and JOSS submission deferred to after traction.

**Done when**: 0.9.0 is on PyPI with a demo and the launch posts are out.

---

### v1.0 — Launch

- Stable API, semver promise.
- All eight guiding principles intact; coverage ≥90%; `ruff` clean.

**Done when**: 1.0.0 is on PyPI.

---

## Guiding principles (non-negotiable)

Invariants from [docs/guides/architecture.md](docs/guides/architecture.md) and
[CLAUDE.md](CLAUDE.md):

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte unless
   the user explicitly requests canonical whole-file layout formatting.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve by default, and impose a
   canonical layout only when explicitly requested.**
7. **Determinism** — no time/randomness/ordering in core logic; network is
   opt-in and isolated.

**What "pynakes 1.0" is**

**A polished, deterministic, single-file maintenance engine — agent-safe,
losslessly JabRef-compatible — with a pinned public API, released on PyPI.** The
unit of work is one `Bibliography` (one `.bib`). 1.0 means: it does single-file
maintenance excellently, covers the JabRef bib-file feature set, promises API
stability (semver), and is installable. The multi-bib `Library`, `Catalogue`,
and MCP server ship in v0.8 as optional companions — they extend reach without
changing the core.

**Beyond 1.0** (deferred to [v2.0](#v20--beyond-10)): projections as `Library`
views with reconciliation, additional interchange formats,
content-intelligence layers, and the Bimas GUI.

## v2.0 — Beyond 1.0

These stay **in pynakes** — pure bib-file mechanisms, no application scope —
but together they are the cross-file corpus layer a downstream application builds
directly on.

- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation.
- **Additional interchange formats** — any import/export formats beyond the
  existing CSL-JSON/RIS/MODS/EndNote quartet, building on `pynakes.interchange`.
- **Content-intelligence layers** — full-text extraction, content search,
  RAG/embeddings, and rich agent notes/memory, as an opt-in extra never on the
  deterministic write path.
- **Thin `pynakes` Bimas GUI** — a lightweight desktop GUI built on the pinned
  API, reading/writing `.bib` files through the library, not the CLI.

**Done when**: 2.0.0 is on PyPI with all of the above shipped and documented.
