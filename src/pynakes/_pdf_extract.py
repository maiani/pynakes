"""Isolated, offline PDF reader used by :mod:`pynakes.pdf_import`.

Only this worker imports PyMuPDF. The parent applies a wall-clock timeout; no
PDF is rewritten and no embedded attachment or action is executed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_METADATA = 1_000_000
MAX_TEXT = 40_000


def extract(path: str | Path) -> dict:
    """Read document information, XMP, embedded BibTeX and bounded front matter."""
    import pymupdf

    result: dict = {"info": {}, "xmp": "", "bibtex": [], "pages": [], "warnings": []}
    with pymupdf.open(path) as reader:
        if not reader.is_pdf:
            raise ValueError("Not a PDF")
        if reader.needs_pass:
            raise ValueError("Encrypted PDF: supply an unencrypted copy for inspection")
        info_type, info_ref = reader.xref_get_key(-1, "Info")
        info_xref = int(info_ref.split()[0]) if info_type == "xref" else None
        for name in ("Title", "Author", "Subject", "DOI", "doi", "BibTeX", "bibtex"):
            value_type, text = reader.xref_get_key(info_xref, name) if info_xref else ("null", "")
            if value_type == "string":
                if len(text) > MAX_METADATA:
                    result["warnings"].append(f"Ignored oversized document metadata {name}")
                else:
                    result["info"][name] = text
        try:
            metadata = reader.get_xml_metadata()
        except Exception as exc:
            metadata = ""
            result["warnings"].append(f"Could not read XMP metadata: {exc}")
        if metadata:
            if len(metadata) <= MAX_METADATA:
                result["xmp"] = metadata
            else:
                result["warnings"].append("Ignored oversized XMP metadata")
        for name in reader.embfile_names()[:16]:
            if name.lower().endswith(".bib"):
                data = reader.embfile_get(name)
                if len(data) <= MAX_METADATA:
                    result["bibtex"].append(
                        {"source": f"attachment:{name}", "text": data.decode("utf-8-sig")}
                    )
                else:
                    result["warnings"].append(f"Ignored oversized BibTeX attachment: {name}")
        result["page_count"] = len(reader)
        for index in range(min(12, len(reader))):
            try:
                text = reader[index].get_text("text", sort=True) or ""
                blocks = reader[index].get_text("blocks", sort=True) or []
                bounded_blocks = []
                remaining = MAX_TEXT
                for block in blocks[:128]:
                    if isinstance(block[4], str) and remaining > 0:
                        value = block[4][:remaining]
                        bounded_blocks.append({"bbox": list(block[:4]), "text": value})
                        remaining -= len(value)
                result["pages"].append(
                    {
                        "page": index + 1,
                        "text": text[:MAX_TEXT],
                        "blocks": bounded_blocks,
                    }
                )
                if len(text) > MAX_TEXT:
                    result["warnings"].append(f"Truncated extracted text on page {index + 1}")
            except Exception as exc:
                result["warnings"].append(f"Could not extract page {index + 1}: {exc}")
    return result


def main() -> None:
    """Return a JSON result, including recoverable reader failures."""
    try:
        result = extract(sys.argv[1])
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
