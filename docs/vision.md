# Vision

**pynakes is a tool for humans and machines collaborating creatively on
research, over a corpus of `.bib` files collected across a lifetime.**

Your personal reference database is not an app or a service — it is the set of
bibliography files you accumulate over your career, kept in version control.
pynakes is the engine that keeps that corpus clean, consistent, and safe to edit,
for both you and the agents working alongside you.

## Scope & sequencing: pynakes vs BiMaS

This document describes the long-term destination. It does **not** expand the
scope of pynakes itself.

- **pynakes** is a standalone Python library + CLI — the deterministic bib-file
  engine. It is complete and valuable on its own (researchers, scripts, agents),
  with no dependency on anything above it. It provides *mechanisms* over `.bib`
  files: parse/edit/lint/convert/normalize, and the cross-file `Collection` /
  `Library` / search / dedup / subset operations — all pure bibfile work, no UI,
  capture, PDF, or sync.
- **BiMaS** (working name) is a **separate, downstream project built on top of
  pynakes' public API.** It owns *policy, workflow, and experience*: capture
  (web/DOI/PDF), reading/annotation, UI, sync orchestration, and the
  lifelong-corpus workflow (inbox → canonical → projections, provenance as a
  product feature).
- **Sequencing.** pynakes must be **stable and complete first.** No BiMaS work
  begins until pynakes' standalone roadmap is done and its engine API is pinned.
  The vision flows in one direction only: it informs how pynakes' API is shaped
  so BiMaS can build on it cleanly — it never pulls BiMaS scope into pynakes.

## The substrate: bibfiles in git

The database *is* a git repository of `.bib` files. This is a deliberate choice,
not a limitation:

- **Longevity & ownership.** A lifelong database cannot depend on any app,
  vendor, format, or schema surviving. Plain-text bibfiles are readable in fifty
  years — by JabRef, Zotero, `grep`, or your future self. You own the files.
- **Git is the infrastructure, for free.** History, diff, blame, branching,
  backup, and cross-device sync come from version control. pynakes does not
  build a sync server; you `git pull`.
- **Meaningful diffs.** Because pynakes round-trips unmodified entries
  byte-for-byte and edits surgically, changing one field is a one-line git diff —
  not a reformatted file. This is what makes "the database is bibfiles in git"
  actually livable, and it is the property most tools that touch `.bib` files
  destroy.

## Humans and machines, collaborating

The machine is a **co-author** of the corpus, not just an automation. That makes
two things load-bearing:

- **Reviewability is the substrate of trust.** Dry-run, unified diffs, atomic
  validated writes, and *reporting conflicts instead of guessing* are what make
  it safe for an agent to add, merge, and enrich entries in a database you care
  about. Every machine action is previewable and reversible.
- **Provenance.** A corpus that machines write to for years must record *who or
  what* added or changed each entry, and from what source. Git captures the
  timeline; entry-level provenance metadata captures the rest.

"Creatively" means the corpus is a **thinking substrate**, not just storage to
maintain: the machine surfaces related work, fills gaps, and connects ideas
across everything you have read.

## The shape

```
capture          new refs arrive (DOI, browser, PDF) → an inbox
   │
   ▼
canonical store  the deduplicated master corpus — sharded bibfiles in git,
   │             one stable identity (DOI / arXiv / OpenAlex) per work
   ▼
projections      per-project / per-paper bibfiles, derived from the store
                 (today: `pynakes used --out` exports the cited subset)
```

Project bibfiles are **views, not copies** of the canonical store; pynakes keeps
them consistent.

## Vocabulary & engine trajectory

Three nested units — **entry ⊂ collection ⊂ library**:

- **Entry** — one bib record.
- **Collection** — one `.bib` file (a single πίναξ): the load → stage → preview →
  commit lifecycle with external-change detection. See the
  [Architecture guide](guides/architecture.md) for the design and the
  [API reference](api/index.md) for the implemented `Collection` API.
- **Library** — the collection: a git repo of collections. This is your *Pinakes* —
  the catalog. Its API adds global search, cross-file identity and dedup,
  "which collections use this key", and promotion between inbox / canonical /
  projections, backed by a **derived index** (rebuildable from the files, never
  a competing source of truth). It is planned for [Beyond 1.0](../DEVPLAN.md).

The tool, `pynakes`, is the librarian; the `Library` is what it tends.

## Principles & non-goals

- **The file is the single source of truth.** Any index, cache, or app state is
  derived and rebuildable; nothing ever competes with the files.
- **Preserve, don't impose.** The store never rejects or rewrites data on its
  own. Structure (required fields, identifiers) is *advisory* — enforced by
  `lint`/`normalize` only when asked — because a lifelong schema will drift.
- **Not a reference-manager replacement.** No database of record, no GUI, no
  sync server, no PDF library, no cloud. Capture and reading sit on top and own
  their own state; pynakes stays the deterministic kernel.
