# Philosophy

**pynakes is a reference management engine for BibTeX and BibLaTeX bibliographies and their research materials.**

The ambition is to support the lifetime of a research library: acquiring
references, curating and comparing records, keeping materials traceable,
assembling project bibliographies, maintaining manuscript citations, and
preparing public release copies. Researchers, applications and automation
should be able to do this through the same engine.

Its foundation is deliberate: authoritative BibTeX/BibLaTeX files, preservation
of untouched source, reviewable changes and explicit conflicts. The current
Python API and CLI implement bibliography operations and optional Pinax material
management. The v0.10 development `Library` API adds direct cross-file lookup and
search, plus reviewed routing of new records to member bibliographies.
Reconciliation, analysis rollups and a derived
`Catalogue` remain planned. The roadmap separates those plans from implemented
features.

## Bibfiles in plain text, in git

A bibliography you keep for years cannot depend on any app, vendor, format, or
schema surviving. Plain-text `.bib` files are readable in fifty years — by
JabRef, Zotero, `grep`, or your future self. You own the files.

That choice pays off only if the files stay diff-friendly:

- **Round-trip fidelity.** An entry you don't touch is written back
  byte-for-byte. pynakes never normalizes whitespace, reorders fields, or
  re-quotes values behind your back.
- **Surgical edits.** Field and key changes use localized source edits instead
  of reformatting the whole entry.
- **The bibliography file is authoritative.** For `Bibliography` and the
  file-backed Library, bibliographic records and settings live in `.bib` files.
  In-memory views and indexes are derived and never compete with those files.

## Library authority and backend choice

The [accepted Library backend design](design/library-backends.md) separates the
reference collection interface from its storage. The implemented Library is
file-backed; the common interface and optional Zotero backend remain planned.
Users choosing a Zotero-backed Library would keep their records and attachments
in Zotero and select references into independent project bibliographies without
first migrating the whole collection into `.bib` members or Pinax.

The selected backend is authoritative. Common views and indexes are rebuildable;
authored notes, accepted decisions and synchronization baselines are persistent
records with explicit ownership, not disposable caches. Their new storage schemas
must be settled before the corresponding writes ship. Backend-specific placement,
mutation and material capabilities must not weaken Bibliography's source-fidelity
guarantees.

Zotero support is conditional on tested public API behavior. It may remain
read-only, support a limited version range, or be dropped if compatibility would
require unreliable operations or invasive exceptions in the engine. Native
Library development remains independent.

## Reviewable automation

Scripts and LLM-assisted tools can use pynakes without directly generating
BibTeX:

- **Preview before commit.** Dry-run and unified diffs expose planned edits;
  ambiguous operations report conflicts instead of choosing silently.
- **Preserve unless asked to transform.** Normalization and formatting happen
  only through explicit commands. Lint findings are advisory unless strict mode
  is requested, and strict mode accepts only findings the bibliography explicitly
  suppresses.
- **Explicit side effects.** Network access is limited to commands whose
  purpose is a request — `ref import`, `ref lookup`, `asset fetch`, and
  `--fetch` on `ref add` / `ref import` — and to operations invoked with
  `--online`.
- **Every setting three ways.** Each behaviour a command can be configured
  into is selectable per run (CLI flag or Python API parameter), storable in
  the bibliography as a metadata setting, and that setting is itself editable
  through the CLI and API (`metadata set`), never only by hand. A bibliography's
  profile therefore reproduces its behaviour from the file alone, and any run
  can override it in either direction. Three things are deliberately not
  settings: how one run is carried out (`--json`, `--dry-run`, `--diff`,
  paging, the `--where`/`--key` selection, output paths, one-off views such as
  `analyze --section` or `convert --to`); whether the network is used
  (`--online`, `--fetch` stay explicit — a setting may choose *which* lookup a
  network command makes, never *whether* one is made); and the terms of a
  single search (`--in`, `--fuzzy`, `--case-sensitive`).
- **File-backed Library placement has Library scope.** Membership and routing
  rules live in the Library manifest, since they choose among bibliographies. They are
  deliberately outside `pynakes-meta` and `metadata set`; the manifest is their
  current editing surface. `library add --destination` and the Python
  `destination=` parameter override placement for one addition. Formatting and
  normalization preferences remain bibliography settings with all three forms.

## In JabRef's lineage

JabRef helped establish the value of curating a `.bib` as a durable library of
references.
pynakes carries that conviction into programmable reference management: it
preserves JabRef metadata and understands its save-order, normalization and
citation-key conventions wherever a bibliography uses them.

The kinship is interop, not imitation. pynakes keeps its own settings in a
`pynakes-meta` namespace and treats `jabref-meta` as a projection it maintains on
JabRef's behalf — already present in bibliographies that use it, and added to a
pynakes-native file only when you opt in with `metadata adopt-jabref`. It follows
JabRef's intent rather than its byte-for-byte output, so the two can evolve on
their own schedules and either can still open the file and find it whole.

## Scope

pynakes is a **standalone reference management engine**: the base unit of work is
one `Bibliography` (one `.bib` file), with a load → stage → preview → commit
lifecycle. It is complete and valuable on its own — for researchers, scripts,
CI, and agents — with no dependency on any application above it.

The optional Pinax mode keeps that base intact while letting a bibliography own a
`pinax-files-dir` of citation-key-addressed materials. No `pinax-files-dir` means no Pinax
behavior. The v0.10 development `Library` API reads across member bibliographies;
work identity, rollups and a derived `Catalogue` index remain planned; see
[DEVPLAN.md](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

The name points past the single file. The *Pinakes* was Callimachus's catalog of
the Library of Alexandria — an index over an entire corpus, not one shelf.
pynakes begins as a single-file engine and grows toward that catalog: the
trustworthy, version-controllable layer a larger AI-assisted research system can
build on. Compatibility with the tools it grew from — JabRef, and the
BibTeX/BibLaTeX it speaks natively — is a guarantee it keeps along the way, not
the boundary of what it aims to be.

## Graphical clients and their scope

The engine expects more than one graphical client above it, and the line between
them is **scope**, not feature count.

The **VS Code extension** in [editor/](https://github.com/maiani/pynakes/tree/main/editor)
is the GUI for a bibliography that belongs to something you are editing — a
paper, a thesis, a repository. That framing is not a product preference; the host
imposes it. A custom text editor in VS Code owns exactly one document as the
source of truth, with the buffer, dirty state, external-change events, and undo
all keyed to it. There is no document for a whole library to hang from, so the
extension is at home with a project's bibliography and structurally unsuited to
being a library browser.

**Bimas** (working name) is the planned standalone application for the other
scope: exploring a generic library that belongs to no particular project and
outlives any workspace. It is not a fallback in case the extension proves too
confining. It exists because library scope is somewhere the extension cannot
follow.

Single file versus many files is a frequent *symptom* of that boundary, not the
boundary itself. A personal master library is often one `.bib` — one file, and
still squarely library-scoped. Scanning citations across a paper's sources spans
one `.bib` and many `.tex` files — many files, and squarely project-scoped. Sort
clients by whose bibliography it is, not by how many files are open.

The boundary is also permeable in one direction. A project-scoped client may
freely *read* library-scoped things: compare a paper's bibliography against a
master library, or import an entry from it. What it does not do is own or curate
them.

Both clients stay thin consumers of the same JSON envelope, with no BibTeX
parser, metadata schema, or source of truth of their own. That is what makes two
clients affordable — and it is also why the envelope has to be pinned and
versioned before the second one exists, rather than after.
