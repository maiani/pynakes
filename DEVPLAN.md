# pynakes development plan

This plan is organized around the project [VISION.md](VISION.md): pynakes is a
**standalone bib-file engine** — a Python library + CLI that is complete and
valuable on its own. The lifelong bibliography-management system (**BiMaS**,
working name) is a **separate, downstream project built on top of pynakes** and
is explicitly *not* in this plan.

This document is the **road to 1.0**. Completed phases are summarized in
"Where we are" and recorded in [CHANGELOG.md](CHANGELOG.md) and the git log;
they are no longer tracked here. Everything under "Road to 1.0" is open work.

## Where we are

The single-file engine is feature-rich and released-ready in all but name:

- **Parser/writer** with byte-for-byte round-trip fidelity; atomic,
  re-parse-validated writes with `.bak` backups; surgical minimal-diff editing.
- **`engine.Collection`** — the load → stage → preview/diff → commit lifecycle
  with external-change detection; the CLI is a thin consumer.
- **Operations**: `inspect`, `lint`, `groups`, `keys` (generate/check/repair/
  rename + JabRef key patterns), `fields` (with `--where`), `convert`,
  `journals`, `files check`, `normalize`, `doi import`, `used`, `dedupe`,
  `verify`/`published`/`enrich` (opt-in `--online`, cached, fixture-stubbed).
- **Metadata**: two namespaces — `jabref-meta` and the `pynakes-meta` superset —
  parsed, merged (pynakes wins), and round-tripped; `metadata set` routes by key.
  JabRef `saveActions` already drive `normalize`'s author/DOI defaults.
- **Agent/CI surface**: stable JSON envelope + exit codes (0/1/2), `--dry-run`/
  `--diff`/`--json`, `capabilities`, multi-file `--strict` gate checks, and a
  `.pre-commit-hooks.yaml`.
- **Quality**: 455 tests, coverage ≥90%, `ruff` clean, docs site builds.

What's missing for a credible **1.0** is below: finishing JabRef parity, making
stored preferences a lintable contract, pinning the public API, and releasing.

## Guiding principles (non-negotiable)

Invariants from [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md):

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

**A polished, JabRef-compatible, single-file maintenance engine, with a pinned
public API, released on PyPI.** The unit of work is one `Collection` (one
`.bib`). 1.0 means: it does single-file maintenance excellently, reaches JabRef
feature parity, promises API stability (semver), and is installable.

**Explicitly *not* in 1.0** (deferred to [Beyond 1.0](#beyond-10-toward-bimas)):
the multi-file `Library`/`Catalogue` corpus engine and CSL-JSON/RIS interop.
These are larger, more corpus-flavored, and are the natural bridge to BiMaS — so
1.0 is not gated on them. (If we decide either is essential to "standalone
complete," pull it forward into a milestone below.)

---

## Road to 1.0

Five milestones. Each is independently shippable; A unblocks distribution and
can ship immediately, B is the substantive feature work, C–E close out 1.0.

### Milestone A — 0.2.0 interim release (unblock everything)

Ship the large post-v0.1 surface under a real version so the work is installable
and citable while 1.0 lands. Move-zero; nothing here is hard.

- [x] Set the real repository URL (`github.com/maiani/pynakes`) in
      `[project.urls]`, `zensical.toml`, the pre-commit hook docs, and guides.
- [ ] Bump version to **0.2.0**; sync `capabilities.VERSION`.
- [ ] `python -m build && twine check && twine upload` (fresh-venv install
      already verified; packaging metadata is clean).
- [ ] Tag `v0.2.0`; confirm the pre-commit hook `rev:` in docs points at it.

**Done when**: `pip install pynakes` installs the current engine from PyPI.

### Milestone B — Complete JabRef feature parity (the 1.0 bar)

Finish honoring JabRef's own settings so a JabRef-configured library normalizes
the same way under pynakes. The `saveActions` reader and the author/DOI mappings
already exist; the formatters below are driven per the file's `saveActions`
field map (`pynakes.formatters`, applied in `normalize`). Parity is locked by
golden vectors lifted from JabRef's own tests in `tests/test_jabref_parity.py`.

- [x] `normalize_date` → ISO date normalization (`yyyy-mm-dd` / `yyyy-mm`).
- [x] `normalize_month` → BibTeX `#mmm#` month normalization.
- [x] `normalize_page_numbers` → `--`/comma page-range normalization.
- [x] Golden-vector parity harness (`tests/test_jabref_parity.py`) + the
      `saveActions`-driven `normalize` pass.
- [ ] **`normalize_names` full parity** — pynakes' author normalizer is not yet
      a full JabRef `AuthorList` parser (initials expansion `Smith SH` →
      `Smith, S. H.`, name affixes, LaTeX-brace names, comma-separated lists).
      The gap is captured as `xfail` parity vectors; closing it trips an xpass.
- [ ] Encoding/case formatters: `latex_cleanup`, `unicode_to_latex` /
      `latex_to_unicode`, `html_to_latex` / `html_to_unicode`, the case
      changers, `ordinals_to_superscript`, `units_to_latex`. Apply only the
      formatters the file's `saveActions` actually configures, per field.
- [ ] Audit `KNOWN_EXACT_KEYS`/`KNOWN_PREFIXES` against a **pinned JabRef
      version** so every current JabRef metadata key classifies as `known`
      (record the version checked against).
- [ ] Decide whether `convert` defaults its target from `databaseType` (record
      the decision either way).

**Done when**: a library carrying JabRef `saveActions` round-trips through
`pynakes normalize` with the same field changes JabRef would make on save
(name parity included), and pynakes recognizes the full pinned-version JabRef
metadata vocabulary.

### Milestone C — Preferences as a lintable contract

`normalize` already reads stored preferences (jabref-meta + pynakes-meta merged)
as defaults. Close the loop you asked for: make `lint` honor the same profile so
stored preferences become a checkable contract, pairing with the `lint --strict`
CI gate.

- [ ] `lint` reads the merged metadata profile and flags deviations: journal not
      in the configured style, citation key not matching `keypattern*`, a field
      the profile marks required is missing, title not brace-protected per
      `protect-titles`.
- [ ] Deviations are `warning`-severity by default; `lint --strict` makes them
      fail, so a repo can gate "stays conformant to its own profile."
- [ ] Document the full profile schema (every `pynakes-meta` key + the JabRef
      keys consulted) in one place in `docs/`.

**Done when**: setting a profile and running `lint --strict` fails a
non-conformant library, with a clear per-entry reason.

### Milestone D — Pin the public API (the 1.0 promise)

1.0 is a stability commitment. Freeze the contract consumers build on.

- [ ] Document and pin the public Python API (`Collection`, the operation
      modules, `model.BibFile`/`BibEntry`, `metadata`) as stable in `docs/`,
      alongside the already-stable CLI/JSON contract.
- [ ] Mark private surface explicitly (leading `_`; document the `_`-rule).
- [ ] Optional consistency pass: rename `JabRefMetadataBlock`/
      `JabRefMetadataUpdate`/`DuplicateJabRefMetadataError` → `Metadata*`
      (they now cover pynakes-meta too) **before** the API freezes, or
      consciously keep the names. Decide now; renames after 1.0 are breaking.
- [ ] State the semver policy: post-1.0, breaking the pinned API or the JSON
      envelope requires a major bump.

**Done when**: `docs/` has an authoritative "public API & stability" page and
the names are settled.

### Milestone E — 1.0.0 release & launch

- [ ] Bump to **1.0.0**; sync `capabilities.VERSION`; tag `v1.0.0`.
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

## Beyond 1.0 (toward BiMaS)

Out of 1.0, in roughly this order. The `Library`/`Catalogue` is the bridge from
the single-file engine to the lifelong corpus, and therefore to BiMaS.

- **Interoperability** — CSL-JSON import/export (Zotero/pandoc/citeproc lingua
  franca), RIS import/export, and first-class stable identifiers (DOI / arXiv /
  OpenAlex / ORCID) shared by dedup, import, and verify.
- **`Library` (corpus)** — `Library.open(dir)`; `collections()`,
  `collection(path)`; cross-file `search`/`find_key`/dedup (reusing the existing
  stable-identity machinery).
- **`Catalogue` (index)** — a derived, rebuildable search index (e.g. SQLite
  FTS) over the Library; strictly derived, never a competing source of truth.
- **Projections** — formalize subset export (today's `used --out`) as a
  first-class "view of the Library".
- **BiMaS** — a separate downstream project, built on the pinned engine + the
  Library/Catalogue. Begins only after the above.

## Out of scope (permanently, for pynakes)

A database of record, a cloud service, a PDF library, arbitrary shell
execution, a GUI, capture (web/DOI/PDF), and reading/annotation. These are
BiMaS or never.

**MCP server — downstream.** An MCP fits an agent interrogating a **personal
corpus** ("what do I already have on X") — i.e. queries over the
`Library`/`Catalogue`, which is BiMaS territory. Manuscript-time edits use the
pynakes **CLI** directly. So the MCP belongs downstream (BiMaS or a thin
`pynakes-mcp` companion on the pinned API), not in the lean, deterministic core.

## Risks & mitigations

- **`saveActions` format drift** (Milestone B) → JabRef is itself reworking the
  format toward embedded JSON; parse tolerantly (regex over `field[formatter]`),
  pin the JabRef version audited against, and keep formatters individually
  testable.
- **API pin too early/late** (Milestone D) → settle names (incl. the optional
  `JabRefMetadata*` rename) and the `_`-private rule *before* tagging 1.0;
  breaking changes after are major-version only.
- **Scope creep** → Library/Catalogue and interop stay Beyond 1.0 unless
  consciously pulled forward; no application concerns enter pynakes.

## Definition of done — 1.0

- [ ] JabRef feature parity complete (Milestone B); recognized-key set audited
      against a pinned JabRef version.
- [ ] Stored preferences honored by both `normalize` and `lint` (Milestone C).
- [ ] Public Python API + CLI/JSON contract documented, pinned, and named for
      stability; semver policy stated (Milestone D).
- [ ] Published to PyPI as 1.0.0 with a demo (Milestones A, E).
- [ ] All guiding principles intact; coverage ≥90%; `ruff` clean.

When this is met, pynakes 1.0 is stable and complete as a standalone single-file
engine, and Beyond-1.0 / BiMaS work may build on the pinned API.
