"""Finding Pinax PDFs stored as the published version that are really preprints.

Not public API. ``asset check`` reports what this module finds and
``asset repair --reclassify`` moves each finding to the preprint path. A file
is reported only on evidence, each piece named in the finding:

* ``source_host`` — the manifest records that it was downloaded from a
  preprint repository (arXiv).
* ``arxiv_doi`` — the entry's only DOI is arXiv's own (``10.48550/arXiv.*``),
  which names the preprint.
* ``pdf_arxiv_stamp`` — the PDF carries arXiv's margin stamp
  (``arXiv:<id>v<n> [<category>] <date>``), which arXiv adds to the PDFs it
  serves and a publisher's version of record does not carry.

A file with no such evidence is never reported: the absence of evidence is not
evidence of a preprint.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable

from pynakes._fetch_attempts import is_preprint_host
from pynakes._identifiers import is_arxiv_doi
from pynakes.filestore import FileStore
from pynakes.model import BibEntry

# arXiv's margin stamp: the identifier with its version, then the category in
# brackets. The version and the bracketed category tell it apart from a
# reference list that merely cites an arXiv id.
_ARXIV_STAMP = re.compile(
    rb"arXiv:\s*((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))v(\d+)\s*\[\s*[A-Za-z\-]+(?:\.[A-Za-z\-]+)?\s*\]"
)
_STREAM = re.compile(rb"stream\r?\n")
# Only the start of a file is read, and only its first few streams inflated:
# the stamp is on the first page.
_READ_BYTES = 4 * 1024 * 1024
_MAX_STREAMS = 24
_MAX_INFLATED = 2 * 1024 * 1024


def misclassified_published(store: FileStore, entries: Iterable[BibEntry]) -> list[dict]:
    """Return one finding per stored published PDF the evidence says is a preprint.

    Each finding names the ``key``, the stored ``path``, its ``evidence``, and
    the ``action`` a repair would take: ``move`` to the preprint path, or
    ``conflict`` when a preprint PDF is already there (nothing is overwritten).
    """
    rows = _manifest_rows(store)
    findings: list[dict] = []
    for entry in entries:
        key = entry.key
        if not key.strip():
            continue
        presence = store.presence_for(key)
        if not presence.published_pdf:
            continue
        path = store.paths_for(key).published_pdf
        evidence = _evidence(entry, rows.get(key, {}), path.read_bytes()[:_READ_BYTES])
        if not evidence:
            continue
        findings.append(
            {
                "key": key,
                "kind": "published_pdf",
                "path": str(path),
                "evidence": evidence,
                "action": "conflict" if presence.preprint_pdf else "move",
            }
        )
    return findings


def arxiv_stamp(data: bytes) -> str | None:
    """Return the ``arXiv:<id>v<n>`` stamp a PDF's first streams carry, or ``None``."""
    match = _ARXIV_STAMP.search(data)
    if match is not None:
        return _stamp(match)
    for count, found in enumerate(_STREAM.finditer(data)):
        if count >= _MAX_STREAMS:
            break
        start = found.end()
        end = data.find(b"endstream", start)
        if end < 0:
            break
        try:
            inflated = zlib.decompressobj().decompress(data[start:end], _MAX_INFLATED)
        except zlib.error:
            continue
        match = _ARXIV_STAMP.search(inflated)
        if match is not None:
            return _stamp(match)
    return None


def _stamp(match: re.Match[bytes]) -> str:
    return f"arXiv:{match.group(1).decode('ascii')}v{match.group(2).decode('ascii')}"


def _evidence(entry: BibEntry, row: dict, data: bytes) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    record = row.get("published_pdf")
    source = record.get("source") if isinstance(record, dict) else None
    if isinstance(source, str) and is_preprint_host(source):
        evidence.append({"type": "source_host", "detail": source})
    doi = entry.fields.get("doi", "").strip()
    if doi and is_arxiv_doi(doi):
        evidence.append({"type": "arxiv_doi", "detail": doi})
    stamp = arxiv_stamp(data)
    if stamp is not None:
        evidence.append({"type": "pdf_arxiv_stamp", "detail": stamp})
    return evidence


def _manifest_rows(store: FileStore) -> dict[str, dict]:
    if not store.manifest_path.is_file():
        return {}
    files = store.read_manifest().get("files", {})
    if not isinstance(files, dict):
        return {}
    return {key: row for key, row in files.items() if isinstance(row, dict)}
