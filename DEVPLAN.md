# pynakes development plan

This plan is organized around the project [philosophy](docs/vision.md): pynakes
is a **standalone bib-file engine** — a Python library + CLI that is complete and
valuable on its own. Any application built on top of pynakes (capture, reading, a
UI, sync) is a **separate, downstream project** and is explicitly *not* in this
plan.

This document is the **road to 1.0**. Completed work is recorded in
[CHANGELOG.md](CHANGELOG.md) and the git log.

## Current state (v0.3.0)

The single-file engine is feature-rich, but it is **not release-ready** until
the 0.4 **input-conformance hard gate** below is complete. A second 0.4 track —
**jabkit coverage** — is a completeness checklist, not a hard gate: it confirms a
JabRef user can do everything here, without dictating pynakes' own command
surface.

- **Parser/writer** with byte-for-byte round-trip fidelity; atomic,
  re-parse-validated writes with `.bak` backups; surgical minimal-diff editing.
- **`engine.Collection`** — the load → stage → preview/diff → commit lifecycle
  with external-change detection; the CLI is a thin consumer.
- **Operations**: `inspect`, `lint`, `groups`, `keys` (generate/check/repair/
  rename + JabRef key patterns), `fields` (with `--where`), `convert`,
  `files check`, `normalize` (including journal title abbreviation/expansion),
  `add` (DOI/arXiv), `used`, `dedupe`, `verify`/`enrich` (opt-in `--online`,
  cached; `--published` folds in preprint published-version checks/promotion),
  `combine`, `split`, `batch`.
- **JabRef v5.15 parity**: full `saveActions` formatter suite, recognized
  metadata vocabulary, and `saveActions`-driven `normalize` defaults. Golden-
  vector test suite anchored to a pinned JabRef release.
- **Lintable profiles**: `lint` reads the merged `jabref-meta`/`pynakes-meta`
  profile and flags deviations; `lint --strict` makes them fail for CI gating.
- **Agent-native surface**: stable JSON envelope + exit codes (0/1/2),
  `--dry-run`/`--diff`/`--json`, structured `plan` objects, self-describing
  `capabilities`, multi-file `--strict` gate checks, `.pre-commit-hooks.yaml`.
- **Pinned public API**: `Collection`, operation modules, `model.BibFile`/
  `BibEntry`, `metadata` — documented in `docs/guides/api-stability.md` with a
  semver policy.
- **Quality**: ~700 tests, coverage ≥90%, `ruff` clean, docs site builds.

## 0.4 hard gate — BibTeX/BibLaTeX input conformance

Do not describe pynakes as feature-complete or release-ready until every item
in this gate is checked. Compatibility means that pynakes accepts and safely
round-trips valid bibliography input; it does not mean it reimplements Biber's
style engine or a user's custom data-model validation rules.

- [x] Pin the reference inputs: **TeX Live 2025** — **BibTeX 0.99d**,
      **BibLaTeX 3.20** (2024-03-21), and **Biber 2.20**. This pair is the
      conformance baseline; fixtures and CI output must record it.
- [x] Parse every standard top-level construct with every delimiter form the
      BibTeX 0.99d grammar permits, plus nested values, quoted values, escaped
      characters, multiline input, macros, and concatenation. The core corpus
      is validated by BibTeX; `%` comments remain a separately tested permissive
      extension because they are TeX syntax, not valid top-level BibTeX database
      syntax.
- [ ] Preserve arbitrary BibLaTeX entry types and custom data-model fields
      without a closed schema; cover `@set`, `@xdata`, inheritance references,
      and Unicode inputs.
- [x] Define and implement the BibLaTeX inheritance contract for every consumer
      of semantic fields: `crossref`, `xref`, `xdata`, and sets must either
      resolve with documented precedence or remain explicitly opaque. `lint`,
      `normalize`, key generation, and other field readers must have tests that
      prove they do not make incorrect assumptions about inherited data.
      Implemented in `pynakes.inheritance` (own > xdata > crossref, with biber's
      type-dependent title remapping; `xref`/sets opaque) and validated against
      the `biber --tool --output-resolve` oracle.
- [x] Preserve the complete top-level source sequence — comments, `@string`,
      `@preamble`, and entries — so an unmodified whole file writes back
      byte-for-byte. Preserve that ordering when an individual entry is edited.
      The parser records a source layout (block order + inter-block whitespace)
      and the writer renders from it; verified byte-for-byte on every fixture,
      including the vendored `xampl.bib` and `biblatex-examples.bib`.
- [ ] Expand the initial versioned core corpus, which now vendors the full
      upstream `xampl.bib` and `biblatex-examples.bib`, with real-world
      regression files. Every fixture must parse and parse again after write.
- [x] Validate the vendored upstream corpora in CI with the pinned TeX Live 2025
      tools: BibTeX 0.99d for `xampl.bib` and Biber 2.20
      `--tool --validate-datamodel` for `biblatex-examples.bib`.
- [ ] Add differential and property-based tests against the pinned reference
      tools: valid generated inputs accepted by BibTeX/Biber must parse in
      pynakes, and pynakes output must be accepted by the relevant tool.
- [ ] Exercise every modifying operation, serializer fallback, and surgical edit
      path on both `{...}` and `(...)` entries. Validate its output with the
      relevant pinned tool, including files that retain top-level declarations.

## 0.4 coverage checklist — jabkit operations for bib files

jabkit (JabRef's headless CLI) is a useful **completeness reference**: a JabRef
user should be able to do everything here. This is a coverage checklist, **not a
design driver** — pynakes designs its own command surface from first principles
and consults this list only to catch gaps, never to mirror jabkit
command-for-command. 0.4 is about being a reliable, complete bib editor; the
PDF / GUI / capture-app scope question is deliberately deferred to 0.5 (below).
"Covered" means a pynakes command (or documented combination) performs the
equivalent operation with the agent-native JSON envelope and reviewable-diff
workflow.

The jabkit ([docs](https://docs.jabref.org/jabkit)) subcommands that operate on
bib files:

- [x] **generate-citation-keys** — `pynakes keys generate` (honors JabRef
      `keypattern*` metadata).
- [x] **check-integrity** — `pynakes verify` / `enrich` (opt-in `--online`;
      `--published` folds in preprint published-version checks/promotion) plus
      `lint`.
- [x] **generate-bib-from-aux** — `pynakes used <bib> <aux> --out cited.bib`
      produces the cited-only subset.
- [x] **check-consistency** — implemented inside `lint` as the advisory
      `inconsistent_field` finding: a field a strict majority of same-type
      entries define (after crossref/xdata inheritance) but a given entry omits.
      Required and JabRef structural/management fields are excluded. It rides the
      existing `--strict` gate and JSON envelope rather than being a separate
      command.
- [x] **search** — query a library and return matches. pynakes has the
      `--where` field filter and `used`, but no dedicated `search` command with
      a query syntax over the whole library. Add one.
- [x] **convert** — BibTeX↔BibLaTeX dialect conversion plus export/import of
      **CSL-JSON** and **RIS** (`pynakes.interchange`), the dominant interchange
      formats. **MODS** and **EndNote** are deferred to 0.5. Pulled forward from
      [Beyond 1.0](#beyond-10).
- [x] **preferences** — jabkit manages a global, persistent application
      preference store. pynakes deliberately has none: configuration lives in
      the library itself as `jabref-meta`/`pynakes-meta`, managed by
      `pynakes metadata list`/`set` and read as defaults by `normalize`, `lint`,
      and key generation. This is the intended design (principle: the file is
      the single source of truth; no hidden global state), so the parity answer
      is per-library metadata profiles rather than a separate preference file.
      *Open, minor:* a way to copy/share a profile between libraries — additive,
      not blocking.

jabkit subcommands that are **not** bib-file operations are out of 0.4 and feed
the 0.5 scope decision below: **fetch** (capture entries from web providers —
pynakes already imports by DOI/arXiv via `add`) and **pdf** (read/write PDF XMP
metadata).

## 0.5 — scope decision: PDF / GUI / capture

Once 0.4 ships a reliable, complete bib editor, decide how far pynakes goes
toward the remaining jabkit surface and JabRef-app territory. Inputs to the
decision: jabkit's **fetch** (web/provider capture) and **pdf** (PDF metadata),
weighed against the philosophy's stance that capture, a PDF library, and a GUI
are downstream concerns. The outcome may
keep them downstream (a thin companion on the pinned API) or pull specific
headless, deterministic pieces into the engine. Not decided here.

Also for 0.5: the remaining interchange formats — **MODS** and **EndNote**
(and any others jabkit supports) — building on `pynakes.interchange`. Adding a
dependency is acceptable when it does the heavy lifting better than a
hand-rolled codec (the no-`bibtexparser` rule is specific to the round-trip
BibTeX parser, not a blanket ban on dependencies).

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
unit of work is one `Collection` (one `.bib`). 1.0 means: it does single-file
maintenance excellently, covers the JabRef bib-file feature set (the coverage
checklist above), promises API stability (semver), and is installable.

**Explicitly *not* in 1.0** (deferred to [Beyond 1.0](#beyond-10)):
the multi-file `Library`/`Catalogue` corpus engine and CSL-JSON/RIS interop.
These are larger and more corpus-flavored — so 1.0 is not gated on them.

---

## Road to 1.0

### Milestone E — 0.9 testing release → 1.0.0 launch

- [ ] **First public release**: make the GitHub repo public, bump to **0.9.0**
      (a pre-1.0 testing release — sync `capabilities.VERSION`), `twine upload`,
      tag `v0.9.0`, and point the pre-commit hook `rev:` in docs at it. Gather
      feedback before committing to the 1.0 API.
- [ ] A 30-second demo (asciinema/GIF): "messy `.bib` → clean `.bib` with a
      reviewable diff", and an agent cleaning a bibliography via pynakes.
- [ ] Lead the README/launch with the agent-tool + reviewable-diff story.
- [ ] Post where the pain lives: r/LaTeX, JabRef community, LaTeX/academia
      Bluesky/Mastodon, a Show HN once the demo is crisp.
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

Out of 1.0, in roughly this order. The `Library`/`Catalogue` is the bridge from
the single-file engine to a cross-file corpus, and is what any downstream
application would build on.

- **Interoperability** — CSL-JSON import/export (Zotero/pandoc/citeproc lingua
  franca), RIS import/export, and first-class stable identifiers (DOI / arXiv /
  OpenAlex / ORCID) shared by dedup, import, and verify. *(Note: the formats
  jabkit's `convert` supports are pulled forward into the 0.4 jabkit coverage
  checklist; what remains here is interop beyond jabkit's surface.)*
- **`Library` (corpus)** — `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup (reusing the existing
  stable-identity machinery).
- **`Catalogue` (index)** — a derived, rebuildable search index (e.g. SQLite
  FTS) over the Library; strictly derived, never a competing source of truth.
- **Projections** — `combine` and `split` have landed as file-level operations
  (`pynakes.setops`). What remains for Beyond 1.0 is formalizing them as
  first-class **views of the `Library`**, once the `Library` exists.

## Out of scope (permanently, for pynakes)

A database of record, a cloud service, a PDF library, arbitrary shell
execution, a GUI, capture (web/DOI/PDF), and reading/annotation. These belong to
a downstream application, not the engine.

**MCP server — downstream.** An MCP fits an agent interrogating a **personal
corpus** ("what do I already have on X") — i.e. queries over the
`Library`/`Catalogue`. Manuscript-time edits use the pynakes **CLI** directly. So
the MCP belongs downstream (a thin `pynakes-mcp` companion on the pinned API, or
part of a corpus-management application), not in the lean, deterministic core.

## Risks & mitigations

- **`saveActions` format drift** → JabRef is reworking the format toward embedded
  JSON. Parse tolerantly (regex over `field[formatter]`), keep the pinned JabRef
  v5.15 baseline, and audit v6 only once a stable v6 release ships.
- **Scope creep** → Library/Catalogue and interop stay Beyond 1.0 unless
  consciously pulled forward; no application concerns enter pynakes.

## Definition of done — 1.0

- [ ] Published to PyPI — first as the 0.9 testing release, then 1.0.0 with a demo.
- [ ] All guiding principles intact; coverage ≥90%; `ruff` clean.
