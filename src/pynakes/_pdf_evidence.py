"""PDF inspection and candidate evidence; never mutates a bibliography."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pynakes._identifiers import normalize_arxiv, normalize_doi, normalize_isbn
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.model import undefined_string_references

# Deliberately bibliographic: never import embedded local paths, private notes,
# groups, directives, or metadata settings from an untrusted document.
BIB_FIELDS = frozenset(
    "title author editor year date journal journaltitle booktitle publisher address location "
    "volume number pages edition doi isbn issn eprint eprinttype archiveprefix primaryclass "
    "url urldate institution school organization series language abstract".split()
)
MAX_PDF_BYTES = 128 * 1024 * 1024
EXTRACTION_TIMEOUT = 30
_DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"\[\]{}]+", re.IGNORECASE)
_ARXIV = re.compile(
    r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)"
    r"([a-z-]+(?:\.[a-z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


class PDFDependencyError(ValueError):
    """PDF inspection needs the optional ``pynakes[pdf]`` dependency."""


@dataclass
class PDFInspection:
    """Evidence from unchanged PDF bytes; candidates are not verified references."""

    path: str
    sha256: str
    extractor: str
    page_count: int = 0
    identifiers: list[dict] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    locations: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    title: str = ""
    warnings: list[str] = field(default_factory=list)
    opening_text: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        """Serialize evidence without copying page text into batch reports."""
        result = asdict(self)
        result.pop("opening_text")
        return result


def require_pdf_dependency() -> None:
    if importlib.util.find_spec("pymupdf") is None:
        raise PDFDependencyError(
            'PDF import requires PyMuPDF; install with: pip install "pynakes[pdf]"'
        )


def file_digest(path: Path) -> str:
    """Hash the complete original, including embedded annotations."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_pdf(path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("_pdf_extract.py")), str(path)],
        capture_output=True,
        timeout=EXTRACTION_TIMEOUT,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"PDF reader exited with status {result.returncode}")
    data = json.loads(result.stdout)
    if "error" in data:
        raise ValueError(data["error"])
    return data


def inspect_pdf(path: str | Path) -> PDFInspection:
    """Inspect one PDF offline in a worker with a 30-second wall timeout.

    Reads at most the first twelve pages for text evidence. Files over 128 MiB,
    encrypted PDFs and malformed PDFs are rejected. No OCR is performed.
    Hashes before and after extraction detect changed source bytes. The timeout
    limits duration, not peak memory of the optional PDF parser.
    """
    require_pdf_dependency()
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("Expected a regular PDF no larger than 128 MiB")
    with source.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise ValueError("Not a PDF: missing PDF header")
    digest = file_digest(source)
    data = _read_pdf(source)
    if file_digest(source) != digest:
        raise ValueError("PDF changed during inspection; retry with a stable source")
    from importlib.metadata import version

    result = PDFInspection(str(source), digest, f"PyMuPDF {version('PyMuPDF')}")
    result.page_count = data.get("page_count", 0)
    result.warnings.extend(data.get("warnings", []))
    info = data.get("info", {})
    result.title = info.get("Title", "").strip()
    for name in ("DOI", "doi"):
        _identifiers(result, info.get(name, ""), f"document-info:{name}")
    for name in ("BibTeX", "bibtex"):
        if info.get(name):
            _bibtex(result, info[name], f"document-info:{name}")
    for attachment in data.get("bibtex", []):
        _bibtex(result, attachment["text"], attachment["source"])
    if data.get("xmp"):
        _xmp(result, data["xmp"])
    references = False
    for page in data.get("pages", []):
        text = page["text"]
        parts = re.split(r"(?im)^\s*(?:references|bibliography)\s*$", text, maxsplit=1)
        accepted = "" if references else parts[0]
        recommendations = re.split(
            r"(?im)^\s*(?:recommended articles|you may also like|related articles|other books in this series)\s*:?\s*$",
            accepted,
            maxsplit=1,
        )
        if len(recommendations) > 1:
            other = PDFInspection(result.path, result.sha256, result.extractor)
            _identifiers(other, recommendations[1], "recommendations", page["page"])
            result.rejected.extend(
                {**item, "reason": "recommendation"} for item in other.identifiers
            )
            accepted = recommendations[0]
        rejected = text if references else (parts[1] if len(parts) > 1 else "")
        if rejected:
            other = PDFInspection(result.path, result.sha256, result.extractor)
            _identifiers(other, rejected, "reference-list", page["page"])
            result.rejected.extend(
                {**item, "reason": "reference_list"} for item in other.identifiers
            )
        _identifiers(result, accepted, "page-text", page["page"])
        for index, block in enumerate(page.get("blocks", [])):
            block_text = block["text"]
            excluded = references or block_text.strip() not in accepted
            result.locations.append(
                {
                    "page": page["page"],
                    "block": index,
                    "bbox": block["bbox"],
                    "text": block_text[:4000],
                    "included": not excluded,
                    "reason": "other_work_or_reference" if excluded else "front_matter",
                }
            )
        if page["page"] <= 2:
            result.opening_text += accepted + "\n"
        references = references or len(parts) > 1
    if not result.opening_text.strip():
        result.warnings.append("No usable opening-page text; OCR is not available")
    return result


def _identifiers(result: PDFInspection, text: str, source: str, page: int | None = None) -> None:
    isbn_pattern = re.compile(r"ISBN(?:-1[03])?\s*:?\s*([0-9][0-9Xx -]{8,24}[0-9Xx])", re.I)
    for match in isbn_pattern.finditer(text):
        try:
            value = normalize_isbn(match.group(1))
        except ValueError:
            result.rejected.append(
                {
                    "kind": "isbn",
                    "value": match.group(1),
                    "source": source,
                    "page": page,
                    "reason": "invalid_checksum",
                }
            )
        else:
            result.identifiers.append(
                {"kind": "isbn", "value": value, "source": source, "page": page}
            )
    for kind, pattern in (("doi", _DOI), ("arxiv", _ARXIV)):
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(".,;") if kind == "doi" else match.group(1)
            # Keep balanced parentheses in DOI suffixes; trim prose punctuation.
            while value.endswith(")") and value.count(")") > value.count("("):
                value = value[:-1]
            try:
                normalized = normalize_doi(value) if kind == "doi" else normalize_arxiv(value)
            except ValueError:
                continue
            if normalized:
                item = {"kind": kind, "value": normalized, "source": source, "page": page}
                if item not in result.identifiers:
                    result.identifiers.append(item)


def _bibtex(result: PDFInspection, text: str, source: str) -> None:
    try:
        lib = parse_bib(text)
        for entry in lib.entries.values():
            # Unresolved @string expressions must not become invented literals.
            if any(
                undefined_string_references(v, lib.strings)
                for v in entry.field_expressions.values()
            ):
                result.warnings.append(f"Skipped BibTeX expressions requiring resolution: {source}")
                continue
            record = {
                "entry_type": entry.type,
                "provider_key": entry.key,
                "fields": {k: v for k, v in entry.fields.items() if k in BIB_FIELDS},
                "source": source,
            }
            if record not in result.records:
                result.records.append(record)
    except (ParseError, ValueError) as exc:
        result.warnings.append(f"Invalid embedded BibTeX ({source}): {exc}")


def _xmp(result: PDFInspection, text: str) -> None:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        result.warnings.append("Ignored XMP containing a DTD or entity declaration")
        return
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        result.warnings.append(f"Invalid XMP: {exc}")
        return
    fields: dict[str, str] = {}
    entry_type, provider_key = "misc", None
    values: list[tuple[str, str]] = []
    for node in root.iter():
        values.extend(node.attrib.items())
        if isinstance(node.tag, str):
            name = node.tag.rsplit("}", 1)[-1].lower()
            leaves = [child.text or "" for child in node.iter() if child.tag.endswith("}li")]
            value = (
                " and ".join(leaves)
                if name == "creator"
                else (leaves[0] if leaves else node.text or "")
            )
            values.append((node.tag, value.strip()))
    for tag, value in values:
        if not value:
            continue
        namespace, _, name = tag.rpartition("}")
        namespace, name = namespace.lower(), name.lower()
        if "bibtex" in namespace:
            if name in {"bibtex", "entry"} and value.lstrip().startswith("@"):
                _bibtex(result, value, "xmp:bibtex")
            elif name in BIB_FIELDS:
                fields[name] = value
            elif name == "entrytype":
                entry_type = value.lower()
            elif name in {"citekey", "key"}:
                provider_key = value
        elif "purl.org/dc/" in namespace:
            mapped = {"title": "title", "creator": "author", "date": "date"}.get(name)
            if mapped:
                fields.setdefault(mapped, value)
        elif "prismstandard.org/namespaces/basic/" in namespace:
            mapped = {
                "doi": "doi",
                "publicationname": "journal",
                "publicationdate": "date",
                "volume": "volume",
                "number": "number",
            }.get(name)
            if mapped:
                fields.setdefault(mapped, value)
    if fields.get("title"):
        result.title = fields["title"]
    if fields.get("doi"):
        _identifiers(result, fields["doi"], "xmp:doi")
    if fields.get("eprint"):
        _identifiers(result, "arXiv:" + fields["eprint"], "xmp:eprint")
    if fields:
        result.records.append(
            {
                "entry_type": entry_type,
                "provider_key": provider_key,
                "fields": fields,
                "source": "xmp",
            }
        )


def normalized_title(value: str) -> str:
    """Compare Unicode/LaTeX title text without punctuation or layout whitespace."""
    from pynakes._text_utils import _normalize_text

    for name, glyph in {
        "alpha": "α",
        "beta": "β",
        "gamma": "γ",
        "delta": "δ",
        "epsilon": "ε",
        "theta": "θ",
        "lambda": "λ",
        "mu": "μ",
        "nu": "ν",
        "pi": "π",
        "rho": "ρ",
        "sigma": "σ",
        "tau": "τ",
        "phi": "φ",
        "chi": "χ",
        "psi": "ψ",
        "omega": "ω",
    }.items():
        value = re.sub(r"\\" + name + r"\b", glyph, value, flags=re.I)
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
    value = unicodedata.normalize("NFKD", _normalize_text(value))
    return "".join(char for char in value.casefold() if char.isalnum())


def document_title_locations(inspection: PDFInspection, title: str) -> list[dict]:
    """Locate an included title beginning a text line, without altering its value."""
    candidate = normalized_title(title)
    if len(candidate) < 12:
        return []
    support = []
    for location in inspection.locations:
        if not location["included"]:
            continue
        lines = location["text"].splitlines()
        if any(
            normalized_title(" ".join(lines[index:])).startswith(candidate)
            for index in range(len(lines))
        ):
            support.append({k: v for k, v in location.items() if k != "text"})
    return support


def title_supported(inspection: PDFInspection, title: str) -> bool:
    """Require a nontrivial title in metadata or the opening text before the abstract."""
    candidate = normalized_title(title)
    if len(candidate) < 12:
        return False
    if candidate == normalized_title(inspection.title):
        return True
    opening = re.split(r"(?i)\babstract\b", inspection.opening_text, maxsplit=1)[0][:4000]
    return candidate in normalized_title(opening) or bool(
        document_title_locations(inspection, title)
    )
