# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Any application built on top of it (capture, reading,
a UI, sync) is a **separate, downstream project** and is explicitly not in this
plan.

This document is the **road to 1.0** and the cross-file corpus bridge beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Current state (v0.4.0)

v0.4 is the first public pre-release. The single-file engine is feature-complete
for the 0.4 scope; input conformance is verified against the TeX Live 2025
baseline (BibTeX 0.99d, BibLaTeX 3.20, Biber 2.20).

- **Parser/writer**: byte-for-byte round-trip fidelity; atomic, re-parse-validated
  writes; surgical minimal-diff editing. Handles `{…}`/`(…)` entry forms, all
  `@string`/`@preamble`/`@comment` constructs, Unicode, BibLaTeX inheritance
  (`crossref`, `xdata`, `xref`, sets), and arbitrary entry types and custom fields.
- **`engine.Bibliography`**: load → stage → preview/diff → commit lifecycle;
  external-change detection; `reset()`/`reload()`.
- **Operations**: `init`, `inspect`, `lint`, `groups`, `keys`
  (generate/check/repair/rename + JabRef key patterns), `fields` (with `--where`),
  `convert` (BibTeX↔BibLaTeX + CSL-JSON/RIS/MODS/EndNote), `files check`, `normalize`
  (authors, DOIs, months, journals, `saveActions` pipeline), `add`
  (DOI/arXiv/journal-URL), `search`, `used`, `dedupe`, `verify`/`enrich`
  (opt-in `--online`; `--published` folds in preprint promotion), `combine`,
  `split`, `batch`.
- **JabRef v5.15 parity**: full `saveActions` formatter suite, complete metadata
  vocabulary, JabRef key patterns, group management.
- **Agent-native surface**: stable JSON envelope + exit codes (0/1/2),
  `--dry-run`/`--diff`/`--json`, structured `plan` objects, self-describing
  `capabilities`, multi-file `--strict` gate checks, `.pre-commit-hooks.yaml`.
- **Parser conformance**: versioned corpus pinned to TeX Live 2025; differential
  tests against BibTeX 0.99d and Biber 2.20; property-based tests (Hypothesis).
- **Quality**: ~870 tests, coverage ≥90%, `ruff` clean, docs site builds.

## 0.5 — remaining interchange formats and scope decision

Status:

1. **Remaining interchange formats (done)**: MODS XML and EndNote tagged text
   are implemented alongside CSL-JSON and RIS. `pynakes.interchange` is now a
   package with one codec module per format plus a small public dispatcher;
   import/export still go through `export_library()` / `import_library()` and
   the `convert --to/--from` CLI surface. No new dependency was needed.

2. **Scope decision — PDF / web capture (decided)**: a headless, deterministic,
   opt-in slice *does* enter the engine — fetching a reference's materials (arXiv
   PDF + source) and attaching them by citation-key convention. This is the
   **Pinax** mode, specified in [docs/guides/pinax.md](docs/guides/pinax.md) and
   built via the [Pinax implementation steps](#pinax-implementation-steps). Plain
   `.bib` maintenance remains unchanged unless a `files-dir` is set. What stays
   out: full-text extraction, content search, reading/annotation — derived
   intelligence over the *contents* of those materials.

Remaining near-term implementation work is the Pinax step plan below.

## Guiding principles (non-negotiable)

Invariants from [docs/guides/architecture.md](docs/guides/architecture.md) and
[CLAUDE.md](CLAUDE.md):

1. **Round-trip fidelity** — unmodified entries write back byte-for-byte.
2. **Edits go through `editing.py`** — surgical, minimal-diff.
3. **Operations mutate in place and return a count/report.**
4. **Stable JSON envelope + exit-code contract.**
5. **Duplicate keys tolerated, not an error.**
6. **The file is the single source of truth; preserve, don't impose.**
7. **Determinism** — no time/randomness/ordering in core logic; network is
   opt-in and isolated.
8. **Prefer a native JabRef setting over a pynakes one** — introduce a
   `pynakes-meta` key only where JabRef has no equivalent.

## What "pynakes 1.0" is

**A polished, deterministic, single-file maintenance engine — agent-safe,
losslessly JabRef-compatible — with a pinned public API, released on PyPI.** The
unit of work is one `Bibliography` (one `.bib`). 1.0 means: it does single-file
maintenance excellently, covers the JabRef bib-file feature set, promises API
stability (semver), and is installable.

**Explicitly *not* in 1.0** (deferred to [Beyond 1.0](#beyond-10)): the
multi-file `Library`/`Catalogue` corpus engine, projections as `Library` views,
and first-class shared identity. Pinax may be built earlier because it is an
optional mode of one `Bibliography`; it must not change plain `.bib` behavior.

---

## Road to 1.0

### Milestone E — 0.9 testing release → 1.0.0 launch

- [ ] **First stable release**: bump to **0.9.0** (a pre-1.0 testing release —
      sync `capabilities.VERSION`), `twine upload`, tag `v0.9.0`, and point the
      pre-commit hook `rev:` in docs at it. Gather feedback before committing to
      the 1.0 API.
- [ ] A 30-second demo (asciinema/GIF): "messy `.bib` → clean `.bib` with a
      reviewable diff", and an agent cleaning a bibliography via pynakes.
- [ ] Lead the README/launch with the agent-tool + reviewable-diff story.
- [ ] **Shell completion for citation keys** (moderate effort). Register
      Click shell-completion callbacks on every argument that accepts a citation
      key (`add`, `keys rename`, `fetch`, etc.). The callback auto-detects the
      `.bib` (same logic as `_resolve_input_bib`), parses it, and yields matching
      keys. Usable via `eval "$(pynakes --show-completion bash)"` / `zsh` / `fish`.
- [ ] Deferred to after traction: Zenodo DOI, then JOSS (JOSS requires
      demonstrated use, so it follows adoption).

**Done when**: 1.0.0 is on PyPI with a demo and the launch posts are out.

### Quality gate (cross-cutting, every PR)

- [ ] `pytest && ruff check src tests && ruff format --check src tests` green.
- [ ] Coverage stays ≥90%; new behavior has tests and a `CHANGELOG.md` entry.
- [ ] All eight guiding principles intact; `capabilities`, README, and this plan
      stay honest (no stub described as shipped).

---

## Beyond 1.0

These stay **in pynakes** — pure bib-file mechanisms, no application scope — but
together they are the cross-file corpus layer a downstream application builds
directly on. Out of 1.0, in dependency order:

- **First-class shared identity** — promote the DOI / arXiv / OpenAlex / ORCID /
  title machinery (today spread across `dedupe`, `verify`, and `add`) into one
  explicit, tested primitive. It is the foundation the rest of this list stands
  on: `Library` dedup, the `Catalogue`, and projection reconciliation all key off
  a single notion of "the same work".
- **`Pinax`** (optional corpus mode; formerly "Collection") — a `Bibliography`
  together with its `files-dir` of materials, addressed by citation key. Not a
  wrapper class but a *mode* a bibliography enters when `pynakes-meta` declares a
  `files-dir`. Specified in [docs/guides/pinax.md](docs/guides/pinax.md) and built
  via the [Pinax implementation steps](#pinax-implementation-steps) below; the
  top-level `fetch` command is the first slice. **Being pulled forward as active
  near-term work** because it preserves the single-file engine: no `files-dir`,
  no Pinax behavior.
- **`Library` (corpus)** — `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the identity
  primitive above. A Library holds many pinakes.
- **`Catalogue` (index)** — a derived, rebuildable search index (e.g. SQLite
  FTS) over the Library; strictly derived, never a competing source of truth.
- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation, once the `Library` exists.
- **Interop beyond 0.5** — any import/export formats past the 0.4/0.5 checklists,
  building on `pynakes.interchange`.

## Pinax implementation steps

The corpus layer (see [docs/guides/pinax.md](docs/guides/pinax.md)) ships as
small, independently committable steps — each is code + tests + a `CHANGELOG.md`
entry and ends green on `pytest && ruff check src tests`. Built one at a time,
reviewed, then the next.

- [x] **1. `files-dir` + `FileStore` foundation (offline).** Recognize the
      `files-dir` `pynakes-meta` key; add `filestore.py` (deterministic
      version-class paths `<citekey>.pdf` / `<citekey>_preprint.pdf` /
      `<citekey>_preprint/`, directory scan, presence checks); expose
      `Bibliography.files` (`FileStore | None`). No network.
- [x] **2. arXiv download core.** Add `fetch.py` (injectable
      `fetch_arxiv_pdf`/`fetch_arxiv_source`, URL builders, safe tar extraction)
      and the `FileStore` atomic writers for the preprint PDF and extracted
      source. Unit-tested with fixtures; no real network.
- [x] **3. The top-level `fetch` command.** `pynakes fetch [target] [file]
      [--online] [--dry-run] [--json]`, with what-to-download governed by the
      `fetch-preprint`/`fetch-source`/`fetch-published` metadata keys;
      `Bibliography.ensure_files_dir` + `fetch_materials`; zero-config default
      `files-dir`; JSON envelope; registration in `cli.py` and `capabilities.py`.
      *First end-to-end slice.*
- [ ] **4. Agent surface.** `inspect --json` reports per-entry `published_pdf` /
      `preprint_pdf` / `preprint_source` / `canonical_pdf`; `files check` reports
      presence/orphans/drift and enforces the unique-key precondition for
      file-addressing operations.
- [ ] **5. `preprint_canonical` + provenance manifest (Tier 1).**
      `.pinax/manifest.json` (`source`/`fetched_date`/`sha256`/`refetchable` per
      artifact, per-entry `preprint_canonical` boolean, default `false`); `fetch`
      writes it; `canonical_*` resolves from the boolean.
- [ ] **6. Pinax-aware `combine`/`split`.** Each output is a pinax; output
      entries' materials and per-entry state are plainly copied into their
      files-dir (no hardlinks); non-destructive — inputs untouched, delete the
      source to reclaim disk after a split.
- [ ] **7. Coordinated key edits (own design pass).** `keys
      rename`/`generate`/`repair` move every `<citekey>*` material *in place*
      (filesystem first, then commit, rollback on failure); `files check --fix`
      reconciles drift. The only in-place material op, so the riskiest.
- [ ] **8. (Later) `add --fetch` + open-access published PDFs.** One-step
      import-and-download; DOI → open-access resolver landing `<citekey>.pdf`;
      `dedupe` merge reconciles materials onto the surviving key.

## Out of scope (for the deterministic core)

A database of record, a cloud service, arbitrary shell execution, a GUI, a
reading/annotation experience, and browser/web capture pipelines. Likewise the
derived-intelligence layers over material **contents** — full-text extraction,
content search, RAG/embeddings, and rich agent notes/memory — stay *above or
beside* the core (an opt-in extra such as `pynakes[…]`, or a separate tool),
never on the deterministic write path.

The line, restated: *attaching and resolving* a reference's materials by
citation-key convention — the **Pinax** layer — is in scope; *organizing,
reading, and indexing their contents* is not. See
[docs/guides/pinax.md](docs/guides/pinax.md).

**MCP server — downstream.** An MCP fits an agent interrogating a personal
corpus — queries over the `Library`/`Catalogue`. Manuscript-time edits use the
pynakes CLI directly. The MCP belongs in a thin companion on the pinned API, not
in the lean, deterministic core.

## Risks & mitigations

- **`saveActions` format drift** → JabRef is reworking the format toward embedded
  JSON. Parse tolerantly (regex over `field[formatter]`), keep the pinned JabRef
  v5.15 baseline, and audit v6 only once a stable v6 release ships.
- **Scope creep** → Library/Catalogue and interop stay Beyond 1.0 unless
  consciously pulled forward; no application concerns enter pynakes.

## Definition of done — 1.0

- [ ] Published to PyPI — first as the 0.9 testing release, then 1.0.0 with a demo.
- [ ] All guiding principles intact; coverage ≥90%; `ruff` clean.
