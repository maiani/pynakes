# Import references from PDFs

`ref from-pdf` creates bibliographic records from local PDFs and links their
unchanged originals using the standard `file` field. It works without a Library
manifest or Pinax store. Directories mean their immediate PDFs, sorted by name;
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

Only identifiers go to existing DOI/arXiv metadata providers; PDFs and their
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

Original filenames, bytes and embedded annotations are preserved. This first
version records absolute links: it does not copy materials into Pinax, migrate
annotations, or create a portable project export. Keep the source files in
place. Their hashes are checked during inspection and again before committing
staged imports. `--expect-sha256` guards the destination bibliography against
changes since a reviewed preview; it does not pin the PDF across invocations.

## Scope and limits

The worker reads metadata, up to 16 embedded filenames, and text from the first
two pages. It has a 30-second wall timeout per PDF, a 128 MiB input limit, a
1-million-character metadata limit and a 40,000-character text limit per page.
It does not enforce a hard peak-memory limit. Password-protected PDFs are
reported as failures; unprotected copies can be inspected. There is no OCR,
filename-based metadata inference, title search, ISBN resolution, full-text
indexing or automatic extraction of reference lists in this first version.
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
