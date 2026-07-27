# Philosophy

**pynakes makes explicit, reviewable changes to bibliography files while
preserving source text it does not modify.**

It is a maintenance engine, not a bibliography application. These are the
design beliefs that shape it.

Pynakes supplies bounded operations, inspection, validation, previews, conflict
handling, and atomic writes. The same commands are directly useful to humans,
scripts, CI, and LLM-assisted tools.

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
- **The file is the single source of truth.** In-memory state is a derived
  working view; there is no database or persistent sidecar of record. Any index
  or cache is rebuildable and never competes with the files.

## Reviewable automation

Scripts and LLM-assisted tools can use pynakes without directly generating
BibTeX:

- **Preview before commit.** Dry-run and unified diffs expose planned edits;
  ambiguous operations report conflicts instead of choosing silently.
- **Preserve unless asked to transform.** Normalization and formatting happen
  only through explicit commands. Lint findings are advisory unless strict mode
  is requested.
- **Explicit side effects.** Network access is limited to `ref import`, `asset
  fetch`, and operations invoked with `--online`.

## In JabRef's lineage

pynakes is strongly influenced by JabRef. JabRef is the program that treated a
`.bib` file as something worth curating with care, and pynakes carries that
conviction forward in a headless, git-oriented tool. It is a descendant, not a
rival: it speaks JabRef's metadata vocabulary fluently and reads JabRef's
configuration as guidance, honoring `saveOrderConfig`, `saveActions`, and key
patterns whenever a library carries them.

The kinship is interop, not imitation. pynakes keeps its own settings in a
`pynakes-meta` namespace and treats `jabref-meta` as a projection it maintains on
JabRef's behalf — already present in libraries that use it, and added to a
pynakes-native file only when you opt in with `metadata adopt-jabref`. It follows
JabRef's intent rather than its byte-for-byte output, so the two can evolve on
their own schedules and either can still open the file and find it whole.

## Scope

pynakes is a **standalone `.bib` maintenance engine**: the base unit of work is
one `Bibliography` (one `.bib` file), with a load → stage → preview → commit
lifecycle. It is complete and valuable on its own — for researchers, scripts,
CI, and agents — with no dependency on any application above it.

The optional Pinax mode keeps that base intact while letting a bibliography own a
`pinax-files-dir` of citation-key-addressed materials. No `pinax-files-dir` means no Pinax
behavior. Cross-file corpus work — a `Library` over many pinakes, a derived
`Catalogue` index — is on the post-1.0 roadmap; see
[DEVPLAN.md](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

The name points past the single file. The *Pinakes* was Callimachus's catalog of
the Library of Alexandria — an index over an entire corpus, not one shelf.
pynakes begins as a single-file engine and grows toward that catalog: the
trustworthy, version-controllable layer a larger AI-assisted research system can
build on. Compatibility with the tools it grew from — JabRef, and the
BibTeX/BibLaTeX it speaks natively — is a guarantee it keeps along the way, not
the boundary of what it aims to be.
