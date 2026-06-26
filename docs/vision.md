# Philosophy

**pynakes makes small, explicit, reviewable changes to bibliography files —
without reformatting, reordering, or corrupting the metadata a human or
reference manager curated.**

It is a deterministic engine, not an application. These are the design beliefs
that shape it.

## Bibfiles in plain text, in git

A bibliography you keep for years cannot depend on any app, vendor, format, or
schema surviving. Plain-text `.bib` files are readable in fifty years — by
JabRef, Zotero, `grep`, or your future self. You own the files.

That choice pays off only if the files stay diff-friendly:

- **Round-trip fidelity.** An entry you don't touch is written back
  byte-for-byte. pynakes never normalizes whitespace, reorders fields, or
  re-quotes values behind your back.
- **Surgical edits.** Changing one field is a one-line diff — not a reformatted
  file. This is the property most tools that touch `.bib` files destroy, and the
  one that makes keeping your bibliography in version control actually livable.
- **The file is the single source of truth.** In-memory state is a derived
  working view; there is no database or persistent sidecar of record. Any index
  or cache is rebuildable and never competes with the files.

## Safe for humans and machines

pynakes is built so that a script or an LLM agent can edit a database you care
about without you having to trust it blindly:

- **Reviewability is the substrate of trust.** Dry-run, unified diffs, atomic
  validated writes, and *reporting conflicts instead of guessing* make every
  machine action previewable and reversible.
- **Preserve, don't impose.** The engine never rejects or rewrites data on its
  own. Structure (required fields, identifiers) is *advisory* — enforced by
  `lint` / `normalize` only when asked.
- **Deterministic by default.** No time, randomness, or hidden ordering in core
  logic. Network access is explicit (`--online` where supported) and isolated.

## Scope

pynakes is a **standalone single-file maintenance engine**: the unit of work is
one `Collection` (one `.bib` file), with a load → stage → preview → commit
lifecycle. It is complete and valuable on its own — for researchers, scripts,
CI, and agents — with no dependency on any application above it.

Cross-file corpus work (a `Library` over many collections, a derived search
index, projections, format interop) is on the post-1.0 roadmap; see
[DEVPLAN.md](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

The name points past the single file. The *Pinakes* was Callimachus's catalog of
the Library of Alexandria — an index over an entire corpus, not one shelf.
pynakes begins as a single-file engine and grows toward that catalog: the
trustworthy, version-controllable layer a larger AI-assisted research system can
build on. Compatibility with existing tools (JabRef, the BibTeX/BibLaTeX
toolchain) is a guarantee it keeps along the way — a substrate it interoperates
with losslessly, not the boundary of what it aims to be.
