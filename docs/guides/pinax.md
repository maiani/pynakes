# Pinax — a bibliography and its materials

> **Status: core Pinax layer implemented including open-access published PDF
> import.** This document specifies the optional *Pinax* layer (a bibliography
> plus its materials) without replacing the plain `.bib` maintenance engine, and
> scopes what is deliberately deferred. For the engine it builds on, see
> [Architecture](architecture.md); for philosophy, [vision](../vision.md); for
> sequencing, [DEVPLAN](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

## Identity

**pynakes is first a deterministic `.bib` maintenance engine.** That identity
stays intact: a plain `.bib` remains first-class, offline, reviewable, and free
of material-management behavior. Pinax is the optional corpus mode layered on
top: the `.bib` file remains the source of truth and center of gravity, while the
*corpus* is that file **plus the materials it points to** — PDFs and source
bundles — addressed by citation key. pynakes keeps the references and their
materials consistent, deterministically and reviewably. It is **not** a
knowledge base.

The name is the project's own: *pynakes* is the *pinakes* (πίνακες) Callimachus
compiled for the Library of Alexandria — an index bound to the holdings it
indexes. A `.bib` file is the index card; a **pinax** is the card together with
the shelf it points at.

### What is in, and what is deferred

One litmus decides scope: *does the feature stay anchored to, and addressed by,
the `.bib`?*

| In — on-identity | Deferred — needs more thought |
| --- | --- |
| Entries, fields, metadata, groups, citation keys | Full-text **extraction** from PDFs |
| **Materials keyed by citekey**: fetch, attach, resolve, verify presence | **Search over PDF content**; a derived index |
| Provenance of those materials (source, hash) | **RAG / embeddings**; an agent vector store |
| Reconciling references ↔ materials | Rich **notes / annotation / agent memory** |

Everything in the right column builds a *derived intelligence layer over the
content* of the materials. Such layers do not treat the `.bib` as their source
of truth, they are often non-deterministic and dependency-heavy, and they are
genuinely hard to get right. They are **deferred, not forbidden**: when they
come, they live *above or beside* the deterministic, bib-file-centric core — as
an opt-in extra (e.g. `pynakes[…]`) or a separate tool — so the core keeps its
guarantees. See [Deliberately deferred](#deliberately-deferred).

> **Notes are the honest edge case.** A note *about* a paper is bib-adjacent, and
> a file-centric form would fit the identity cleanly — a `<citekey>.md` beside
> `<citekey>.pdf`, or a `note` field on the entry. That much is on-identity and
> cheap. What is deferred is the richer human+agent annotation/memory system;
> that is the knowledge-base direction and deserves its own design.

## The pinax: a mode, not a tool

**A pinax is a bibliography that also owns a directory of its materials.** It is
not a new file format, a new object, or a new command namespace — it is a *mode*
a bibliography enters when its `pynakes-meta` declares a `files-dir`:

- A `.bib` with **no** `files-dir` is a plain bibliography. Nothing changes: no
  material linting, no fetching, no required PDFs, no extra network or filesystem
  expectations.
- A `.bib` **with** a `files-dir` is a pinax: the same file, the same commands,
  but file-aware — keys address materials on disk, and operations keep the
  references and the materials consistent.

```bibtex
@comment{pynakes-meta:
files-dir: refs.files
}
```

That single key is the switch. Set it and the bibliography is a pinax; remove it
and it is a plain `.bib` again, the materials left untouched on disk.

### The switch is `files-dir` — no redundant toggle

`files-dir` alone is the switch; there is deliberately **no** separate
`pinax: true` boolean. Reasons:

1. **Single source of truth, no invalid states.** A separate flag would permit
   contradictions (`pinax: true` with no directory; a `files-dir` with
   `pinax: false`) that then need precedence rules to resolve.
2. **The directory is the substantive fact.** "Is this a corpus?" and "where are
   its materials?" are the same question; the path answers both.
3. **The consequence it adds is self-justifying.** The one thing a pinax changes
   — duplicate keys, already a lint finding, block the file-addressing operations
   (see [invariants](#invariants-the-pinax-mode-adds)) — is *correct and wanted*,
   and a clear message explains it where it bites, so it needs no ceremonial
   second flag to feel intentional.

What a toggle reaches for — explicit intent and zero configuration — belongs at
the UX layer, not as a stored duplicate key:

- A deliberate enable writes the default for you: `pynakes init --pinax refs.bib`
  (or `metadata set files-dir`) records `files-dir: refs.files`, so you opt in on
  purpose and never have to invent a directory name.
- The default directory is **`<stem>.files`** (collision-safe when several `.bib`
  files share a folder). A valueless `files-dir:` means "I am a pinax — use the
  default."

The one future condition that would justify an umbrella flag: if "pinax" ever
means a *bundle* of behaviors toggled independently of whether materials are
present (e.g. an auto-index). Since those are [deferred](#deliberately-deferred),
that day is not here — and keeping such behaviors as their own keys lets an
umbrella appear later without repainting `files-dir`.

## On-disk layout

The materials live in one directory beside the `.bib`, named deterministically
from the citation key:

```text
refs.bib
refs.files/                       ← files-dir, declared in pynakes-meta
  alvarez2019.pdf                 ← published PDF (version of record):  <citekey>.pdf
  alvarez2019_preprint.pdf        ← arXiv PDF:  <citekey>_preprint.pdf
  alvarez2019_preprint/           ← arXiv source bundle:  <citekey>_preprint/
    main.tex
    figures/
  bohr1913_preprint.pdf           ← arXiv-only paper: just a preprint, no published <citekey>.pdf
  curie1898.pdf                   ← published-only paper (no arXiv)
  .pinax/
    manifest.json                 ← provenance sidecar (see Provenance manifest)
```

Two version classes share each citation key. The **published** version of record
is unsuffixed; the **preprint** (arXiv) carries an always-on `_preprint` label, on
both the PDF and the source folder. The filename alone tells you the version — no
manifest lookup — and nothing is renamed when a published version later appears:
you just add `<citekey>.pdf` beside the existing `_preprint` files.

| Shape | Path | Meaning |
| --- | --- | --- |
| **Published PDF** | `<files-dir>/<citekey>.pdf` | The version of record — present when available (often only if open-access). |
| **Preprint PDF** | `<files-dir>/<citekey>_preprint.pdf` | The arXiv PDF. |
| **Preprint source** | `<files-dir>/<citekey>_preprint/` | The arXiv source tree. **Read-only** in v1 — fetched, not authored. |

The filename is *derived* from the citation key, never stored. pynakes discovers
materials by scanning `files-dir` against the keys it already knows; there is no
per-entry `file` field to maintain (see
[Breaking with JabRef's `file` field](#breaking-with-jabrefs-file-field)).

## Three sources of truth

The design separates three concerns that a naive "filename = citekey" scheme
conflates. Each has a different owner, and only one is
authoritative-and-irreplaceable:

| Concern | Question | Source of truth | Rebuildable? |
| --- | --- | --- | --- |
| **Presence** | "Is there a PDF for `bohr1913`?" | the filesystem — scan `files-dir` | Always. |
| **Addressing** | "Where does `bohr1913` live?" | derived from the citation key | Always — a pure function. |
| **Provenance** | "Where did this come from? Re-fetchable?" | `.pinax/manifest.json` | Partly — see below. |

The load-bearing rule:

> **The manifest records provenance, never presence.** Whether a file *exists* is
> always answered by the live filesystem.

That preserves the engine's first principle — *the file is the source of truth;
indexes are rebuildable*. The presence index rebuilds by scanning. Provenance for
**re-fetchable** files (an arXiv PDF, an open-access DOI PDF) rebuilds by
re-resolving the identifier. The only irreplaceable bit is the provenance of
**precious** files — a manually added PDF, an annotated copy — and that bit is
tiny.

A consequence worth stating plainly: **the basic feature needs no manifest at
all.** Re-fetchability is derivable from the entry's own identifiers (does it
carry an arXiv id? a DOI?). The manifest ([Tier 1](#provenance-manifest-tier-1))
is additive — it earns its place by recording provenance for precious files.

## Invariants the pinax mode adds

These extend — never weaken — the guiding principles in
[Architecture](architecture.md). They apply only when a `files-dir` is set.

1. **Unique keys are a precondition for addressing materials.** Duplicate
   citation keys are already a problem everywhere — the BibTeX/Biber toolchain
   warns and drops the duplicate, and pynakes `lint` flags them. The parser still
   *tolerates* them (it must, so a broken file can be opened and repaired), and
   that tolerance holds for a pinax too. What a pinax changes is the
   *consequence*: because the key now addresses a file (`bohr1913` →
   `bohr1913.pdf`), any operation that resolves materials by key — fetch,
   rename-with-files, the presence scan — refuses to act on a duplicated key and
   reports a conflict until it is resolved. The advisory lint finding becomes a
   hard precondition for those operations.
2. **Materials are addressed, not tracked.** The filename is a pure function of
   the citation key. pynakes derives a path and scans; it records no path per
   entry and writes no `file` field by default. `files-dir` itself must be a
   *relative* path that does not escape the `.bib`'s directory — a pinax never
   reads or writes outside its own tree, so a hand-edited `files-dir: /etc` or
   `../../elsewhere` is rejected.
3. **Presence is the filesystem; the manifest is provenance-only and
   rebuildable** for everything except precious files.
4. **Source bundles are read-only fetched material** in v1. The
   `<citekey>_preprint/` tree is content pynakes downloaded, not a directory it
   authors into.
5. **Material mutations are coordinated, never guessed.** As `editing.py` is the
   only boundary for `.bib` text, all material moves/downloads go through the
   `filestore`/`fetch` mechanism. When references and materials drift apart,
   pynakes **reports** it and offers a reconcile; it never silently resolves it.
6. **Determinism and the offline default hold.** Fetching is network I/O, but it
   only happens when the user runs the explicit `asset fetch` command or passes
   `add --fetch`. Nothing about a pinax introduces hidden time, randomness, or
   network into core logic.
7. **Operations preserve the pinax.** Any operation that produces a `.bib` from a
   pinax produces a *pinax* — carrying the materials and per-entry state for the
   entries it emits. `corpus combine` of pinakes yields a pinax whose files-dir is the
   union; `corpus split` yields several pinakes, each with its entries' materials. These
   stay **non-destructive**: materials are plainly **copied** into the outputs (no
   hardlinks or clever sharing), so inputs remain intact and a wrong result is
   undone by deleting the outputs. To reclaim disk after a `corpus split`, delete the
   source pinax — an explicit, reversible step rather than baked-in destruction.
   Per-entry state (`preprint_canonical`, provenance) is copied alongside, so it
   survives the move between files without having to live on the entry.

## No new command namespace

A pinax is a mode, not a tool, so the CLI gains **no `pinax` namespace** — at most
one new top-level verb (`asset fetch`). Existing commands become file-aware when — and
only when — a `files-dir` is set:

| To… | Use | What changes for a pinax |
| --- | --- | --- |
| Declare the files-dir | `init --pinax`, or `metadata set files-dir` | The only step that "creates" a pinax. |
| See what materials exist | `inspect [--json]` | The report gains per-entry presence and local paths — the [agent surface](#agent-surface). |
| Validate materials | `asset check [--fix]` | Reports missing/orphan/drift between references and `files-dir`; reconciles with `--fix`. |
| Rename / regenerate keys | `keys rename`, `keys generate`, `keys repair` | Every material sharing the key — `<citekey>.pdf`, `<citekey>_preprint.pdf`, `<citekey>_preprint/` — moves with it (see [Coordinated edits](#coordinated-edits-and-atomicity)). |
| Download missing materials | `asset fetch` (the one new download verb) | See [Fetch](#fetch-the-first-slice). |
| Combine / split | `corpus combine`, `corpus split` | Produce pinakes; each output entry's materials are copied into the output's files-dir. Non-destructive — inputs untouched. |

Everything else keeps working unchanged and simply *gains* file-awareness the
moment the metadata key is present. That is the whole point of making a pinax a
property of the data rather than a separate command.

### Library-side shape

The same principle holds in the Python API: **a pinax is a mode of
`Bibliography`, not a wrapper class.** A bibliography opened from a `.bib` with a
`files-dir` exposes a `files` handle (a `FileStore`); one without exposes `None`.
The lifecycle object does not change.

```python
bib = Bibliography.open("refs.bib")
if bib.files:                       # truthy ⇔ this bibliography is a pinax
    report = bib.fetch_materials("alvarez2019")   # download into files-dir
```

The mechanics stay out of the text engine: path computation, scanning, and moves
live in a new `filestore.py` (pure filesystem, no bib semantics); downloading
lives in `fetch.py` (network, mirroring `importer.py`'s injectable-fetcher
pattern). `engine.py` gains only an optional `FileStore` and the coordinating
methods; the `.bib` text-rendering path is untouched, so round-trip fidelity is
unaffected.

## Fetch — the first slice

`asset fetch` is the first concrete brick, and it sits dead-center on the identity:
materials, addressed by citekey, with the `.bib` staying authoritative,
deterministic, reviewable, and no content-intelligence.

Given an arXiv entry, it downloads the PDF and the source bundle into the right
place:

```text
pynakes asset fetch alvarez2019 refs.bib  →  refs.files/alvarez2019_preprint.pdf
                                             refs.files/alvarez2019_preprint/
```

(arXiv yields the preprint; a published `<citekey>.pdf` lands only when an
open-access published PDF is found — see [Preprint and published
versions](#preprint-and-published-versions).)

It obeys the existing [network boundary](architecture.md#network-boundary):

- **Opt-in and deterministic.** Network access is explicit; the default test
  suite never touches it (fetchers are injectable, as in `importer.py`).
- **Sources.** arXiv first — an entry's arXiv id (via `importer.entry_arxiv_id`)
  yields the preprint PDF at `arxiv.org/pdf/<id>` and the source tarball at
  `arxiv.org/e-print/<id>`, stored as the `_preprint` artifacts. An open-access
  published PDF (resolved from the entry's DOI) lands as the unsuffixed
  `<citekey>.pdf`. Both come behind the same opt-in.
- **Zero-config.** If the `.bib` is not yet a pinax, `asset fetch` records the default
  `files-dir` (`<stem>.files`) and creates it — one command bootstraps the corpus.
- **Atomic writes.** A download lands in a temporary name inside `files-dir` and
  is atomically renamed into place; a partial download never leaves a half-file
  under a citation key. Source tarballs extract safely (no path traversal, no
  symlinks) into `<citekey>_preprint/`.
- **Bytes only, never extraction.** `asset fetch` retrieves and stores files. It does
  **not** parse PDF content — that is [deferred](#deliberately-deferred).
- **Graceful gaps.** `asset fetch` stores only what exists and never errors on a gap.
  An entry with no arXiv id and no resolvable open-access DOI simply has nothing
  to fetch — it lands in `skipped` with a reason, not `failed`. A PDF-only e-print
  (no source tree) skips the source step, so no empty `<citekey>_preprint/` is
  created. `failed` is reserved for an actual download or I/O error.
- **Envelope.** `asset fetch` extends the standard JSON envelope with `fetched` /
  `skipped` / `failed` lists; `modified` reflects whether the `.bib` changed (e.g.
  a `files-dir` was recorded), not the downloads themselves.

What `asset fetch` downloads is **governed by metadata**, not a per-invocation flag —
what a pinax fetches is part of its configuration. Three per-pinax policy keys,
one per artifact, select it (and they never trigger network access on their own
during offline operations):

```bibtex
@comment{pynakes-meta:
files-dir: refs.files
fetch-preprint: true
fetch-source: true
fetch-published: false
}
```

### Preprint and published versions

A single work is one entry with one citation key — pynakes keeps the published
metadata (`doi`, `journal`, …) and the arXiv `eprint` on the *same* entry, and
`dedupe` / `verify --published` push toward that. So the key addresses the work,
and the two version classes hang off it by name:

- `<citekey>.pdf` — the **published** version of record (unsuffixed).
- `<citekey>_preprint.pdf` and `<citekey>_preprint/` — the **arXiv** PDF and source.

The three `fetch-*` keys select what `asset fetch` downloads: `fetch-preprint` the arXiv
PDF, `fetch-source` the arXiv source tree, `fetch-published` the unsuffixed
published PDF — set in metadata, not per invocation. Because
published PDFs are usually paywalled, the preprint is what reliably arrives; the
published `<citekey>.pdf` shows up only when it is open-access.

**Two roles come apart, and a boolean picks the canonical.** The unsuffixed
`<citekey>.pdf` is the *version of record* (what you cite). The **canonical**
artifact (what you read and work from) is chosen by a simple per-entry boolean,
`preprint_canonical` (default `false`):

- `false` → canonical is the published `<citekey>.pdf` (falling back to the
  preprint if there is no published PDF).
- `true` → canonical is `<citekey>_preprint.pdf` together with its
  `<citekey>_preprint/` source.

Set `preprint_canonical: true` when the arXiv version is the one to trust — most
often because the authors revised it *after* publication, and because it carries
**source** (LaTeX) the published PDF does not. It is a deliberate, explicit flag,
not an inferred rule: `asset fetch` may initialize it (e.g. when the arXiv `updated`
date postdates publication), but the stored truth is just the boolean and you can
flip it. Filenames stay fixed to the version *class* — they never flip — so only
the `canonical` pointer changes.

If a work is split across two *entries* (a separate `@misc` arXiv and an
`@article` published), that is a duplicate for `dedupe` — and merging it in a
pinax must reconcile their materials onto the surviving key, the same
coordinated-edit machinery as rename.

### Recovering the arXiv source for published papers (DOI to arXiv backfill)

The source bundle is only ever reachable through the **arXiv id**: a published
PDF carries no LaTeX. So the rule that a published entry keeps *both* its `doi`
and its arXiv `eprint` is what makes the source fetchable at all. Two directions
have to hold it:

- **Preprint → published** is already additive. `enrich --published` adds `doi`
  / `journal` and promotes `@misc`/`@online` → `@article` **without ever
  removing `eprint`** (`integrity._apply_published_candidate`), so a promoted
  entry stays a valid `fetch-source` target.
- **Published → arXiv is the gap.** A paper entered by its publisher DOI
  (`add 10.1103/…`) never had an arXiv id — Crossref metadata does not carry one
  — so its source is unreachable. This is the real "we lose the arXiv".

The fix is a **DOI → arXiv back-resolution** folded into the online published
pass, so `enrich --published --online` reconciles identity *both* ways: for an
entry that has a publisher DOI but no resolvable arXiv id
(`importer.entry_arxiv_id` returns `None`), it looks the work up by DOI and, when
a preprint exists, backfills the arXiv id.

- **Sources: OpenAlex first, Semantic Scholar fallback.** OpenAlex
  (`https://api.openalex.org/works/doi:<doi>`) needs no API key, its data is CC0,
  and it is already the identity backbone named for
  [v0.7](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md). OpenAlex
  represents arXiv as a *location*, not an id field, so the resolver scans the
  work's `locations[]` for an `arxiv.org/abs/<id>` URL and parses it with the
  shared identifier helpers. When OpenAlex has the work but not the arXiv
  location, the resolver falls back to Semantic Scholar's `externalIds.ArXiv`.
- **Network boundary.** Behind `--online`, provider fetchers are injectable
  exactly like `importer.fetch_arxiv_atom`, with the same deterministic on-disk
  cache (`integrity._cache_path`). The default test suite never touches the
  network.
- **Fields written**, dialect-aware (via `library_dialect`), through the
  surgical `editing.set_entry_field` and never overwriting an existing value:
  - biblatex → `eprint = {<id>}`, `eprinttype = {arxiv}`
  - bibtex → `eprint = {<id>}`, `archiveprefix = {arXiv}`

  Both pairs are read back by `entry_arxiv_id`, so either makes `fetch-source`
  work; the dialect choice is only about idiomatic output.
- **Graceful gaps.** No provider record, or records with no arXiv id, is a skip
  with a reason — never an error. The backfill only *adds* an identifier; it
  never changes the citation identity (`doi` / `journal` / type stay put).
- **Envelope.** It reuses `enrich`'s existing `updates` (a `FieldUpdate` per
  `eprint`/`eprinttype` written) and `changed_entries` / `changed_fields`; no new
  top-level keys. No provenance manifest entry — the recovered id lives on the
  entry, which *is* its provenance.

Once `eprint` is present, the existing `fetch-source` machinery downloads the
`<citekey>_preprint/` tree unchanged; `preprint_canonical: true` then lets you
read the arXiv source while still citing the version of record. This is distinct
from [step 9](#implementation-steps) (open-access *published PDF* bytes): this
step recovers the *identifier linkage*, and is useful to any library, pinax or
not.

## Coordinated edits and atomicity

Renaming a key in a pinax must move its materials — the one genuinely hard
mechanic, because a `.bib` text commit and a binary file move cannot be one
atomic transaction.

The rule: **filesystem first (it is reversible), then the `.bib` commit; roll
back the moves if the commit fails.** `asset check --fix` is the backstop: if a
process dies mid-operation or a user renames a file by hand, the references and
materials drift, and `asset check` reports the drift and reconciles it — never by
guessing, always by reporting first. Accepting this reconcile step is the honest
cost of addressing materials by citation key, and it is acceptable because the
drift is always detectable and the fix always reviewable.

Rename is the **only in-place** material operation, and so the riskiest: it
mutates an existing files-dir rather than writing fresh outputs the way `corpus combine`
/ `corpus split` do (where a failure just discards a half-written output). It warrants
its own focused design pass before implementation.

## Provenance manifest (Tier 1)

The manifest is additive and optional, at `<files-dir>/.pinax/manifest.json`, and
records **provenance only**:

```json
{
  "version": 1,
  "files": {
    "alvarez2019": {
      "preprint_canonical": true,
      "published_pdf":   { "source": "https://doi.org/10.1103/xxxx",         "fetched_date": "2026-06-27", "sha256": "…", "refetchable": true },
      "preprint_pdf":    { "source": "https://arxiv.org/pdf/1903.01234",     "fetched_date": "2026-06-27", "sha256": "…", "refetchable": true },
      "preprint_source": { "source": "https://arxiv.org/e-print/1903.01234", "fetched_date": "2026-06-27", "sha256": "…", "refetchable": true }
    },
    "bohr1913": {
      "published_pdf": { "source": "manual", "added_date": "2026-05-01", "sha256": "…", "refetchable": false }
    }
  }
}
```

- **Keyed by citation key** for human-diffability and to mirror the filenames; a
  `keys rename` re-keys the row (a cheap JSON edit that cannot half-fail like a
  binary move). The durable identity lives *inside* each row (`source`), so even a
  botched rename is recoverable.
- It never records presence. A row may exist for a deleted file; that is drift,
  surfaced by `asset check`, not a second source of truth.
- `refetchable: false` marks a precious file — the one thing in `.pinax/` worth
  keeping for its own sake.
- `preprint_canonical` (per entry, default `false`) marks the preprint as the
  canonical content to read; `canonical_*` resolves from it. `false` → the
  published `<citekey>.pdf` (or the preprint if there is no published PDF);
  `true` → the `_preprint` artifacts. See [Preprint and published
  versions](#preprint-and-published-versions).
- Each artifact records when it was obtained — `fetched_date` (downloaded by
  `asset fetch`) or `added_date` (manually placed) — as provenance. It is not a
  canonical-selection input; `preprint_canonical` decides that.

## Agent surface

A pinax is meant to be read by machines as much as humans. `inspect --json` on a
pinax annotates every entry with what is available locally:

```json
{
  "key": "alvarez2019",
  "published_pdf": "refs.files/alvarez2019.pdf",
  "preprint_pdf": "refs.files/alvarez2019_preprint.pdf",
  "preprint_source": "refs.files/alvarez2019_preprint/",
  "canonical_pdf": "refs.files/alvarez2019_preprint.pdf",
  "canonical_source": "refs.files/alvarez2019_preprint/",
  "refetchable": true
}
```

This is the contract that lets an agent working in the repository **resolve a
local path and read the paper without re-downloading it** — it reads
`canonical_pdf` (here the arXiv version, because `preprint_canonical` is set,
which also brings `canonical_source`) — and knows, for what is missing, whether a
`asset fetch` could retrieve it. It is a derived view over the
filesystem scan, emitted through the same documented JSON envelope as every other
command.

## Breaking with JabRef's `file` field

JabRef records attachments in a per-entry `file` field. A pinax deliberately does
**not** use it as the source of truth: the convention (`<citekey>.pdf`) is
canonical, so there is no per-entry path to drift from the filesystem. This is a
conscious break with JabRef compatibility for this one relationship — acceptable
for a materials directory driven by pynakes and read by agents.

Because the convention is canonical, the `file` field is *derivable*. A future
opt-in (e.g. `files export-links`) can emit `file` descriptors for JabRef users on
demand, without ever putting that field on the core write path — so it can never
silently orphan a material.

## Deliberately deferred

These are **not in the near-term identity** and deserve dedicated thought. They
are deferred, not forbidden; when they arrive they sit *above or beside* the
deterministic, bib-file-centric core — as an opt-in extra (e.g. `pynakes[…]`, and
a "bimas" experience layer may live here) or a separate tool — never woven into
the core write path.

- **Full-text extraction** of PDF/source content into text.
- **Search over content** and any derived index (e.g. SQLite FTS) — distinct from
  today's `search` over `.bib` fields.
- **RAG / embeddings** and an agent vector store.
- **Rich notes / annotation / agent memory** (beyond a simple file-centric
  `<citekey>.md` or `note` field, which would be on-identity).
- A GUI, a database of record, cloud sync, and capture pipelines (browser/PDF
  ingestion).

The discipline that protects the core: a deferred feature must not make the
`.bib` stop being the source of truth, must not introduce nondeterminism into
core logic, and must not require its dependencies for a base install.

## Implementation steps

The corpus layer ships as a sequence of small, independently committable steps —
each is code + tests + a `CHANGELOG.md` entry and ends green on
`pytest && ruff check src tests`. This is the build order; the spec above is what
each step conforms to, and
[DEVPLAN](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md) tracks it as a
checklist.

1. **`files-dir` + `FileStore` foundation (offline).** Recognize the `files-dir`
   `pynakes-meta` key; add `filestore.py` with the deterministic version-class
   paths (`<citekey>.pdf`, `<citekey>_preprint.pdf`, `<citekey>_preprint/`),
   directory scan, and presence checks; expose `Bibliography.files`
   (`FileStore | None`). No network.
2. **arXiv download core.** Add `fetch.py`: injectable `fetch_arxiv_pdf` /
   `fetch_arxiv_source`, the URL builders, and safe tar extraction; add the
   `FileStore` atomic writers for the preprint PDF and the extracted source.
   Unit-tested with fixtures, no real network. *(Implemented.)*
3. **The `asset fetch` command.** `pynakes asset fetch [target] [file]
   [--dry-run] [--cache-dir DIR] [--json]`, with what-to-download governed by
   the `fetch-preprint` / `fetch-source` / `fetch-published` metadata keys;
   `Bibliography.ensure_files_dir` + `fetch_materials`; the zero-config default
   `files-dir`; the JSON envelope; registration in `cli.py` and
   `capabilities.py`. *(The first end-to-end useful slice — "given an arXiv
   entry, download the PDF and source into the right place.")*
4. **Agent surface.** `inspect --json` reports per-entry `published_pdf` /
   `preprint_pdf` / `preprint_source` / `canonical_pdf`; `asset check` reports
   presence, orphans, and drift, and enforces the unique-key precondition for
   file-addressing operations. *(Implemented.)*
5. **`preprint_canonical` + provenance manifest (Tier 1).** `.pinax/manifest.json`
   with `source` / `fetched_date` / `sha256` / `refetchable` per artifact and the
   per-entry `preprint_canonical` boolean (default `false`); `asset fetch` writes it and
   may initialize the boolean; `canonical_*` resolves from it. *(Implemented.)*
6. **Pinax-aware `corpus combine` / `corpus split`.** Each output is a pinax; an output entry's
   materials and per-entry state are copied into its files-dir. Non-destructive —
   inputs untouched. (Lower-risk than rename: outputs are fresh, so a failure just
   discards a half-written output.) *(Implemented.)*
7. **Coordinated key edits (own design pass).** `keys rename` / `generate` /
   `repair` move every `<citekey>*` material *in place* (filesystem first, then
   commit, rollback on failure); `asset check --fix` reconciles drift. The only
   in-place material operation, so the riskiest. *(Implemented.)*
8. **`add --fetch` for arXiv Pinax materials.** One-step import-and-download for
   arXiv references, using the existing Pinax fetch policy for preprint
   PDF/source materials. *(Implemented.)*
9. **Open-access published PDFs.** DOI → open-access resolver landing the
    published version at `<citekey>.pdf`, when a resolvable open-access copy
    exists. *(Implemented.)*
10. **Dedupe material merge.** `dedupe` merge reconciles Pinax materials onto the
    surviving key, preserving moved provenance and refusing ambiguous material
    overwrites. *(Implemented.)*
11. **DOI → arXiv backfill.** `enrich --published --online` reconciles identity
    both ways: when an entry has a publisher DOI but no arXiv id, resolve the
    work via OpenAlex and backfill `eprint` (+ `eprinttype`/`archiveprefix` per
    dialect), so a published-first entry becomes a `fetch-source` target. See
    [Recovering the arXiv source for published papers](#recovering-the-arxiv-source-for-published-papers-doi-to-arxiv-backfill).
    Lands in `integrity.py`; useful to any library, pinax or not.
    *(Implemented.)*

## Decisions and open questions

Settled in discussion:

- **`asset fetch` is a top-level command** (like `add` / `normalize`), not a new
  namespace.
- **What to fetch is metadata-driven** — the `fetch-preprint` / `fetch-source` /
  `fetch-published` keys, not a per-invocation flag.
- **`add --fetch` is a convenience trigger** — it imports the reference, then
  runs the same metadata-driven fetch policy for the new key.
- **Canonical is a per-entry `preprint_canonical` boolean**, default `false`.
- **PDF-only e-prints** are handled gracefully (the source step is skipped).
- **Operations preserve the pinax** — `corpus combine` / `corpus split` produce pinakes,
  **plainly copying** materials into the outputs (no hardlinks); both stay
  non-destructive, and you delete the source pinax to reclaim disk after a split.
  `preprint_canonical` and provenance travel as copied per-entry state.
- **`files-dir` is constrained** — relative, never escaping the `.bib`'s directory.
- **Metadata format stays `pynakes-meta`** for now; a TOML sidecar in the
  files-dir is the planned home for corpus config when it outgrows flat scalars
  (never TOML-in-`@comment{}`).

Still open:

1. **Default fetch-policy values** — sensible defaults for `fetch-preprint` /
   `fetch-source` / `fetch-published`, and whether `fetch-published` should mean
   "fetch when an open-access copy is resolvable." Leaning: preprint PDF + source
   on, published attempted when an OA copy is found.
2. **Command-surface migration** — how `asset check` reports both legacy JabRef
   `file` fields and Pinax `files-dir` materials without confusing plain `.bib`
   users. Leaning: file-awareness is gated on `files-dir`, so a plain `.bib` sees
   `asset check` exactly as today; a pinax adds a separate, clearly-labeled
   materials section (presence / orphans / drift) while still validating any
   legacy `file` descriptors it finds.
