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
  `convert` (BibTeX↔BibLaTeX + CSL-JSON/RIS), `files check`, `normalize`
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
- **Quality**: ~850 tests, coverage ≥90%, `ruff` clean, docs site builds.

## 0.5 — remaining interchange formats and scope decision

Two items for 0.5:

1. **Remaining interchange formats**: MODS and EndNote, building on
   `pynakes.interchange`. Adding a dependency is acceptable when it does the
   heavy lifting better than a hand-rolled codec (the no-`bibtexparser` rule is
   specific to the round-trip BibTeX parser, not a blanket ban on dependencies).

2. **Scope decision — PDF / web capture**: jabkit's **fetch** (web/provider
   capture) and **pdf** (PDF metadata) are adjacent to pynakes' surface but
   involve network and filesystem concerns that are nominally downstream. Decide
   whether any headless, deterministic slice enters the engine or stays in a
   companion package. Not decided here.

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
and first-class shared identity.

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
- **`Collection`** — one `Bibliography` together with its associated directory of
  linked PDFs and source files. `Collection.open(dir)` where `dir` holds a `.bib`
  and its linked file tree. The richer working unit a researcher interacts with
  directly: references plus the materials.
- **`Library` (corpus)** — `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup, reusing the identity
  primitive above. A Library holds many Collections.
- **`Catalogue` (index)** — a derived, rebuildable search index (e.g. SQLite
  FTS) over the Library; strictly derived, never a competing source of truth.
- **Projections** — `combine` and `split` formalized as first-class **views of
  the `Library`**, with reconciliation, once the `Library` exists.
- **Interop beyond 0.5** — any import/export formats past the 0.4/0.5 checklists,
  building on `pynakes.interchange`.

## Out of scope (permanently, for pynakes)

A database of record, a cloud service, a PDF library, arbitrary shell
execution, a GUI, capture (web/DOI/PDF), and reading/annotation.

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
