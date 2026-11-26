# Import references from PDFs

`ref from-pdf` creates bibliographic records from local PDFs. With Pinax
configured, it adopts unchanged bytes and writes relative `file` links; adoption
**moves the source by default**, after storage and bibliography commit. Use
`--mode copy` to preserve originals. Without Pinax it links the originals and
leaves them in place. It works without a Library manifest. Directories mean their immediate PDFs, sorted by name;
subdirectories and other file types are not imported.

Install the optional backend:

```sh
pip install 'pynakes[pdf]'
```

The backend is **PyMuPDF**. It is available under **AGPL-3.0 or a commercial
license**, with terms separate from pynakes' MIT license. Making it optional
does not waive those terms; consult [PyMuPDF licensing](https://pymupdf.io/licensing)
when distributing or deploying an application using this extra.

## Inspect, preview, and import

Initialize a destination bibliography, then preview a file or directory:

```sh
pynakes init references.bib
pynakes ref from-pdf references.bib papers/ --dry-run --diff --json
```

Offline import uses complete embedded BibTeX or XMP bibliographic records
(title, author/editor, and publication year/date). It does not treat a PDF's
creation timestamp as its publication date. Embedded private notes, file paths,
groups and bibliography settings are excluded. BibTeX attachments must have a
title corroborated by the document, because an attachment may be its reference
list. A scan or sparse metadata may produce no usable record.

For PDFs containing identifiers, request provider resolution explicitly:

```sh
pynakes ref from-pdf references.bib papers/ --online --dry-run --diff --json
```

Only identifiers go to existing DOI/arXiv/ISBN metadata providers; PDFs and their
extracted text are not uploaded. An automatically resolved title must agree
with document metadata or occur in its opening text before the abstract.
Multiple supported candidates, failed competing lookups, and probable existing
matches remain unresolved or ambiguous. A preprint and its published DOI are
not automatically collapsed into a single publication choice.

After reviewing evidence, select an identifier for a single PDF if necessary:

```sh
pynakes ref from-pdf references.bib paper.pdf --identifier 10.5555/example --online --dry-run --diff
```

`--identifier` is an explicit assertion that this is the document's identifier;
it bypasses title corroboration and can identify an otherwise unreadable scan.
Remove `--dry-run` to apply accepted imports. `--key` names a single entry;
`--key-source generated|provider` overrides the existing `import-key-source`
metadata setting in either direction. Library key patterns, dialect, declared
normalization, formatting and insertion order apply to new records.

## Outcomes and preservation

Every file has a result: `imported`, `linked` (another PDF for an existing work),
`existing` (the same bytes are already linked), `ambiguous`, `needs_online`,
`unresolved`, or `failed`. JSON includes a summary, `complete`, candidate
evidence, source SHA-256, extractor version and provider-resolution attempts.
Candidate identifiers include their metadata source or one-based PDF page.
Keep the JSON report if you need an import log; it contains private paths and
metadata and should not be published unreviewed.

Partial batches commit accepted records in one bibliography write and report
the rest, with `complete: false`. Exit 0 therefore does not mean that all PDFs
were identified. A batch with no accepted or already-present records exits 2
when ambiguous, otherwise 1. Re-running a completed batch does not add copies
of already-linked bytes. Different PDF bytes for one identified work remain
separate attachments; existing metadata is not overwritten.

PDF bytes and embedded annotations are preserved. Pinax stores variants under
`.pinax/objects/<sha256>.<extension>` and retains the original path/name as
private provenance. Multiple variants of the same role coexist. The default
role is `unclassified`; classification is explicit via `--role`. Existing fixed
Pinax paths remain supported. Citation-key renames move the manifest ownership
without renaming immutable objects.

`pinax-adopt-mode` (`move` or `copy`) and `pinax-adopt-role` configure the defaults;
`--mode` and `--role` override them. These settings are editable with `metadata
set`. `asset adopt FILE KEY SOURCE` stages the same storage/link transaction for
any local attachment; `asset recover FILE` finishes an interrupted adoption.
Moves refuse sources linked by other entries or already owned by Pinax; use
copy mode for these. Source hashes are checked before committing. Existing
external links remain absolute unless explicitly adopted.

`--expect-sha256` guards the destination bibliography against changes since a
reviewed preview; it does not pin the PDF across invocations. For a Library-wide
plan covering sources, decisions, rules and members, use the workflow below.

## Scope and limits

The worker reads metadata, up to 16 embedded filenames, and text from the first
twelve pages. It has a 30-second wall timeout per PDF, a 128 MiB input limit, a
1-million-character limit per metadata item and a 40,000-character text limit
per page (also shared across at most 128 reported blocks).
It does not enforce a hard peak-memory limit. Password-protected PDFs are
reported as failures; unprotected copies can be inspected. There is no OCR,
filename-based metadata inference, full-text indexing or automatic extraction
of reference lists. ISBNs are checksum-validated and resolved with the existing
Open Library provider. Multiple editions/identifiers require review. Online
comparison of complete embedded records exposes conflicting provider fields.
Text matching is conservative and can require explicit selection for equations,
complex typography and unusual title layouts.

## Python API

```python
from pynakes import Bibliography
from pynakes.pdf_import import inspect_pdf

evidence = inspect_pdf("paper.pdf")  # offline, no writes
library = Bibliography.open("references.bib")
report = library.import_pdfs(["paper.pdf"], online=False)
print(report.to_dict())
print(library.diff())
library.commit()  # apply the accepted staged changes
```

`inspect_pdf`, `import_pdfs`, `PDFInspection`, and `PDFImportReport` are exposed
by `pynakes.pdf_import`. Public results contain ordinary Python values rather
than PyMuPDF objects. The optional backend is loaded only for PDF operations.

## Managed Library ingestion and review

Create a [Library manifest](library-routing.md) with member bibliographies and
routing rules, then preview a selected cohort:

```sh
pynakes library ingest research.library.toml sample/ --mode copy --dry-run --diff --json
pynakes library ingest research.library.toml sample/ --mode copy --expect-plan SHA256 --json
pynakes library review research.library.toml --json
```

Replace `SHA256` with `plan_sha256` from the preview. Use identical options for
preview and apply, including `--online` when requested. Previews create no
Library files; an explicit provider cache may be populated by online lookups.
The operation provisions separate member-owned Pinax stores when needed. All
members and stores must lie inside the manifest directory. Existing work is
checked across members before routing; ambiguous ownership remains pending.
Only accepted metadata is inserted. Unsupported immediate directory entries,
missing, unreadable and unidentified files remain accounted for without fake
bibliography entries. Sources and PDFs are never executed or rewritten.

Unlike the single-bibliography importer, automatic managed acceptance requires
corroborating document text locations, not just PDF metadata properties. The
report retains page/block locations, excluded reference/recommendation evidence,
provider comparisons and field provenance. Text extraction is heuristic; inspect
uncertain results and leave them pending until reviewed.

Apply writes a version-1 private ledger at
`.pynakes-ingest/<manifest-stem>/ledger.json`. It records source occurrences and
hashes, candidates, decisions, routing, plan fingerprints, output hashes and
previous outcomes. `pending` and `complete` describe unresolved work; exit 0 only
means the operation completed. `accepted_records` counts unique accepted works,
including already-present records; `modified_entries` counts bibliography edits.
The manifest filename/stem identifies its ledger; keep it when restoring.

Supply reviewed decisions with `--decisions private-decisions.json`. Its JSON
object maps absolute source paths to decisions, each requiring the current
`sha256`. Supported choices are `identifier`, a `record` containing `entry_type`
and string-valued `fields`, `exclude` with a reason, `destination`, `mode`, and
`role`. Invalid or stale decisions remain pending. A `query` explicitly requests
text lookup and requires `--online`: this sends the supplied text to the existing
lookup provider. Candidate search alone never accepts a record. Identifier-only
operation has no automatic text-search fallback. PDFs and extracted page text
are never uploaded. Keep decision files and ledgers private.

Writes stage and verify payloads before publishing a version-1 recovery journal.
Materials precede manifests, bibliographies and receipts; moving originals is
last. Interruptions retain the journal and payloads. Recover with:

```sh
pynakes library recover research.library.toml --json
```

Recovery needs no provider calls. It accepts only original or planned output
bytes; external changes stop recovery for review. This is recoverable sequential
publication, not a globally atomic multi-file filesystem transaction. Do not
remove a live journal or its payloads. Reopen the Library after applying a plan.
Completed receipts recognize already-present materials on retry.

Back up the manifest, member bibliographies, entire Pinax stores (including
hidden `.pinax` directories), and private ledger together. Relative links work
at a different root without the original archive. Ordinary Git can store these
bytes; LFS or an external material backup is optional. Metadata-only clones
correctly report missing variants. The engine never stages files, commits,
configures Git/LFS, or pushes. Scrubbing a bibliography does not scrub adjacent
private ledgers or Pinax provenance.

```python
from pynakes import Library

plan = Library.open("research.library.toml").prepare_ingestion(
    ["sample/"], mode="copy", online=False,
)
preview = plan.to_dict()
result = plan.commit(expect_sha256=preview["plan_sha256"])
```
