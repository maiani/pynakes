# pynakes development plan

pynakes is a **standalone bib-file engine** — a Python library + CLI, complete
and valuable on its own. Any application built on top of it (capture, reading,
a UI, sync) is a **separate, downstream project** and is explicitly not in this
plan.

This document is the **road to 1.0** and the major releases beyond it.
Completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and the git log.

## Current state (v0.5 alpha candidate)

v0.5 is the first public alpha release. The single-file engine is
feature-complete for this release; input conformance is verified against the TeX
Live 2026 baseline (BibTeX 0.99d, BibLaTeX 3.21, Biber 2.21). Until v1.0,
pynakes does **not** guarantee backward compatibility for the Python API, CLI
syntax, or JSON envelopes.

- **Parser/writer**: byte-for-byte round-trip fidelity; atomic, re-parse-validated
  writes; surgical minimal-diff editing. Handles `{…}`/`(…)` entry forms, all
  `@string`/`@preamble`/`@comment` constructs, Unicode, BibLaTeX inheritance
  (`crossref`, `xdata`, `xref`, sets), and arbitrary entry types and custom fields.
- **`engine.Bibliography`**: load → stage → preview/diff → commit lifecycle;
  external-change detection; `reset()`/`reload()`.
- **Operations**: `init`, `inspect`, `lint`, `groups`, `keys`
  (generate/check/repair/rename + JabRef key patterns), `fields` (with `--where`),
  `convert` (BibTeX↔BibLaTeX + CSL-JSON/RIS/MODS/EndNote), `asset check`, `normalize`
  (authors, DOIs, months, journals, `saveActions` pipeline, `saveOrderConfig`
  entry sorting), `ref add`/`ref import`
  (DOI/arXiv/journal-URL), `search`, `tex scan`, `dedupe`, `verify`/`enrich`
  (opt-in `--online`; `--published` folds in preprint promotion), `corpus combine`,
  `corpus split`, `corpus batch`.
- **Pinax corpus mode (steps 1–8, 10)**: `FileStore`, arXiv download, `asset fetch`
  command, agent surface, provenance manifest, pinax-aware `corpus combine`/`split`,
  coordinated key edits, `ref import --fetch`, dedupe material merge. Step 9 (OA PDFs)
  is deferred.
  See [Pinax implementation steps](#pinax-implementation-steps).
- **JabRef v5.15 parity**: full `saveActions` formatter suite, complete metadata
  vocabulary, JabRef key patterns, group management.
- **Agent-native surface**: structured JSON envelope + exit codes (0/1/2),
  `--dry-run`/`--diff`/`--json`, structured `plan` objects, self-describing
  `capabilities`, multi-file `--strict` gate checks, `.pre-commit-hooks.yaml`.
- **Parser conformance**: versioned corpus pinned to TeX Live 2026; differential
  tests against BibTeX 0.99d and Biber 2.21; property-based tests (Hypothesis).
- **Quality**: ~951 tests, coverage ≥90%, `ruff` clean, docs site builds.
- **Refactoring (post-v0.4 quality pass)**: ``engine.py`` split into ``_engine_helpers.py`` /
  ``_engine_ops.py`` + mixin (~400 lines, within the 500-line convention); ``formatters.py`` split
  into a ``formatters/`` package; ``_text_utils.py`` consolidates the 7+ brace/quote scanner copies
  into one; interchange codec deduplication via ``assign_key`` / ``build_bibfile`` in
  ``_shared.py``; CLI verb-string boilerplate consolidated via ``_verb`` helper; ``BibFile.derive()``
  replaces the duplicated ``_with_entries`` / ``subset_library`` pattern; ``_metadata_value`` /
  ``_metadata_list`` / ``_metadata_bool`` moved from ``lint.py`` / ``normalize.py`` into
  ``metadata.py``; many ``ISSUES.md`` bugs, type-safety issues, and invariant violations addressed.

---

## Road to 1.0

### v0.5 — First public alpha

Release the feature-complete single-file engine publicly as an alpha, with the
core Pinax layer implemented through arXiv PDF/source download. The pinned
conformance baseline is TeX Live 2026. Backward compatibility remains
explicitly unguaranteed until v1.0.

**Deferred Pinax steps**
- [ ] **9. Open-access published PDFs.** DOI → open-access resolver landing the
      published version at `<citekey>.pdf`, when a resolvable open-access copy
      exists. Deferred beyond the public alpha.
- [x] **10. Dedupe material merge.** `dedupe` merge reconciles Pinax materials
      onto the surviving key.

**Agent polish**
- [x] **Citekey shell completion.** Register Click shell-completion callbacks on
      `remove`, `fetch`, `keys rename`, `groups add-entry`, `groups remove-entry`.
      The `.bib`-file completer also shows citekeys alongside the filename when a
      single `.bib` is auto-detectable. Usable via
      `eval "$(pynakes --show-completion bash)"` / `zsh` / `fish`.
- [x] **`remove` command.** `pynakes ref remove <bib> <citekey>... [--keep-files]
      [--dry-run] [--diff] [--json] [--backup]`. Removes entries by citation key
      through the standard lifecycle. In a pinax, removes the entry's materials
      from `files-dir` by default (`--keep-files` opts out). Dry-run correctly
      skips all filesystem side effects.
- [x] **`--backup` flag on all write commands.** Added to `add`, `dedupe_merge`,
      `fetch`, `fields`, `groups`, `keys`, `metadata/set`, `used`,
      `integrity/enrich`. Also fixed `remove` which declared the param but didn't
      wire it through.
- [x] **Output emission consolidation.** Migrated `used`, `combine`, and `split`
      from manual `typer.echo(_json.dumps(...))` to the canonical `_emit()` helper.
- [x] **Optional `file` argument on all single-file commands.** Every command that
      takes a `.bib` file argument now auto-detects a single `.bib` in the current
      directory when omitted.

**Conformance baseline**
- [x] **Bump pinned TeX Live baseline to 2026.** Update the versioned conformance
      corpus, differential test expectations, and CI configuration to match
      TeX Live 2026 (BibTeX 0.99d, BibLaTeX 3.21, Biber 2.21).

**Done when**: alpha scope implemented, tested, and documented;
`pytest && ruff check src tests` passes; CHANGELOG updated; version bumped to
0.5.0.

---

### v0.6 — Cross-discipline import

Broaden `add` beyond DOI and arXiv with dedicated import paths for:

- **PubMed PMID / PMCID** — via NCBI E-utilities (`eutils.ncbi.nlm.nih.gov`).
  Covers biomedicine and life sciences (~35M citations).
- **ISBN** — for books, via Open Library or Google Books API. Covers humanities
  and social sciences where books dominate.
- **SSRN ID** — Social Science Research Network papers; the existing
  `_preprint_identity` already recognizes `ssrn.com` URLs but there is no
  import path.
- **NBER ID** — National Bureau of Economic Research working papers (economics).
- **Generalize journal URL resolver table** — the current
  `_JOURNAL_URL_RESOLVERS` dict has only two entries (nature.com and
  journals.aps.org). Add common publisher patterns (Elsevier, Springer, Wiley,
  PLOS, PubMed Central URLs).
- Many preprint servers (bioRxiv, medRxiv, ChemRxiv, PsyArXiv, etc.) use
  dedicated DOI prefixes and already work through the DOI path — document this
  and add test fixtures.

**Done when**: all import paths implemented, tested, and documented; `pytest &&
ruff` green; CHANGELOG updated; version bumped to 0.6.0.

---

### v0.7 — Shared identity

Promote the DOI / arXiv / OpenAlex / ORCID / title machinery (today spread
across `dedupe`, `verify`, and `add`) into one explicit, tested primitive. It
is the foundation everything else stands on: `Library` dedup, the `Catalogue`,
and projection reconciliation all key off a single notion of "the same work".

**Done when**: identity primitive shipped with tests and docs; consumers in
`dedupe`, `verify`, and `add` refactored to use it; `pytest && ruff` green;
CHANGELOG updated; version bumped to 0.7.0.

---

### v0.8 — MCP server + Library + Catalogue

- **MCP server.** A thin [Model Context Protocol](https://modelcontextprotocol.io)
  companion on the pinned pynakes API, allowing agents to interrogate a personal
  corpus. Manuscript-time edits still use the pynakes CLI directly; the MCP
  server is a query-only layer over the `Library`/`Catalogue`.
- **`Library` (corpus).** `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the identity
  primitive from v0.7. A Library holds many pinakes.
- **`Catalogue` (index).** A derived, rebuildable search index (e.g. SQLite FTS)
  over the Library; strictly derived, never a competing source of truth.

**Done when**: MCP server published as a companion package (or optional extra),
`Library` and `Catalogue` shipped with tests and docs; `pytest && ruff` green;
CHANGELOG updated; version bumped to 0.8.0.

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
- Launch posts, Zenodo DOI, JOSS submission after adoption.

**Done when**: 1.0.0 is on PyPI.

---

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

**Explicitly *not* in 1.0** (deferred to [v2.0](#v20--beyond-10)): the
multi-file `Library`/`Catalogue` corpus engine, the MCP server, projections as
`Library` views, and first-class shared identity. Pinax was built in v0.5
because it is an optional mode of one `Bibliography`; it does not change plain
`.bib` behavior.

---

## v2.0 — Beyond 1.0

These stay **in pynakes** — pure bib-file mechanisms, no application scope —
but together they are the cross-file corpus layer a downstream application
builds directly on.

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

---

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
- [x] **3. The top-level `fetch` command.** `pynakes asset fetch [target] [file]
      [--dry-run] [--json]`, with what-to-download governed by the
      `fetch-preprint`/`fetch-source`/`fetch-published` metadata keys;
      `Bibliography.ensure_files_dir` + `fetch_materials`; zero-config default
      `files-dir`; JSON envelope; registration in `cli.py` and `capabilities.py`.
      *First end-to-end slice.*
- [x] **4. Agent surface.** `inspect --json` reports per-entry `published_pdf` /
      `preprint_pdf` / `preprint_source` / `canonical_pdf`; `files check` reports
      presence/orphans/drift and enforces the unique-key precondition for
      file-addressing operations.
- [x] **5. `preprint_canonical` + provenance manifest (Tier 1).**
      `.pinax/manifest.json` (`source`/`fetched_date`/`sha256`/`refetchable` per
      artifact, per-entry `preprint_canonical` boolean, default `false`); `fetch`
      writes it; `canonical_*` resolves from the boolean.
- [x] **6. Pinax-aware `combine`/`split`.** Each output is a pinax; output
      entries' materials and per-entry state are plainly copied into their
      files-dir (no hardlinks); non-destructive — inputs untouched, delete the
      source to reclaim disk after a split.
- [x] **7. Coordinated key edits (own design pass).** `keys
      rename`/`generate`/`repair` move every `<citekey>*` material *in place*
      (filesystem first, then commit, rollback on failure); `files check --fix`
      reconciles drift. The only in-place material op, so the riskiest.
- [x] **8. `add --fetch` for arXiv Pinax materials.** One-step
      import-and-download for arXiv references, using the existing Pinax fetch
      policy for preprint PDF/source materials.
- [ ] **9. Open-access published PDFs.** (deferred) DOI → open-access resolver
      landing the published version at `<citekey>.pdf`, when a resolvable
      open-access copy exists.
- [x] **10. Dedupe material merge.** `dedupe` merge reconciles Pinax materials
      onto the surviving key.
- [ ] **11. DOI → arXiv backfill.** (deferred) Extend `enrich --published
      --online` to reconcile identity both ways: when an entry has a publisher
      DOI but no resolvable arXiv id, resolve the work via OpenAlex (injectable
      fetcher, deterministic cache) and backfill `eprint` (+ `eprinttype`/
      `archiveprefix` per dialect) so a published-first entry becomes a
      `fetch-source` target — the source is only reachable through the arXiv id.
      Lands in `integrity.py`; useful to any library, pinax or not. Spec:
      [pinax.md](docs/guides/pinax.md) → "Recovering the arXiv source for
      published papers".

## Out of scope (for the deterministic core)

A database of record, a cloud service, arbitrary shell execution, a GUI (the
Bimas GUI ships in v2.0 as a separate application, not in the core), a
reading/annotation experience, and browser/web capture pipelines. Likewise the
derived-intelligence layers over material **contents** — full-text extraction,
content search, RAG/embeddings, and rich agent notes/memory — stay *above or
beside* the core (an opt-in extra such as `pynakes[…]`, or a separate tool),
never on the deterministic write path.

The line, restated: *attaching and resolving* a reference's materials by
citation-key convention — the **Pinax** layer — is in scope; *organizing,
reading, and indexing their contents* is not. See
[docs/guides/pinax.md](docs/guides/pinax.md).

The MCP server is part of v0.8: a thin companion on the pinned API, not in the
core.

## Risks & mitigations

- **`saveActions` format drift** → JabRef is reworking the format toward embedded
  JSON. Parse tolerantly (regex over `field[formatter]`), keep the pinned JabRef
  v5.15 baseline, and audit v6 only once a stable v6 release ships.
- **`saveOrderConfig` sort parity (partial)** → `normalize` honors JabRef's
  order type and `field;descending` criteria, but does **not** yet replicate
  JabRef's rule of hoisting `crossref`-referencing entries ahead of their
  parents (a BibTeX 0.99 processing requirement). A library JabRef would save
  with parents reordered can therefore differ in entry order. Deferred until a
  crossref-aware pass lands; track here rather than claiming full parity. The
  `saveActions` formatter suite and metadata vocabulary remain at full v5.15
  parity.
- **Scope creep** → no application concerns enter the pynakes core. GUIs,
  content-intelligence, and MCP servers ship as optional companions or separate
  releases (v0.8, v2.0).

## Quality gate (cross-cutting, every PR)

- [ ] `pytest && ruff check src tests && ruff format --check src tests` green.
- [ ] Coverage stays ≥90%; new behavior has tests and a `CHANGELOG.md` entry.
- [ ] All eight guiding principles intact; `capabilities`, README, and this plan
      stay honest (no stub described as shipped).

## Definition of done — 1.0

- [ ] Published to PyPI — first as the 0.9 testing release, then 1.0.0 with a demo.
- [ ] All guiding principles intact; coverage ≥90%; `ruff` clean.
