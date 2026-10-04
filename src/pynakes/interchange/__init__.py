"""Bibliography interchange formats: CSL-JSON, RIS, MODS, EndNote, and CSV.

Translates between pynakes' BibTeX/BibLaTeX entry model and common interchange
formats: CSL-JSON (the Zotero/pandoc/citeproc lingua franca), RIS, MODS XML,
EndNote tagged text, and CSV. This is bibliographic-*data* conversion, distinct
from the in-place BibTeX↔BibLaTeX dialect conversion in :mod:`pynakes.convert`:
*export* turns a library into foreign-format text and *import* parses foreign
text into a new :class:`~pynakes.model.BibFile`.

CSV is export-only — it is lossy for BibTeX structures (repeated authors,
braced capitalization, string macros, linked files, comments, and metadata do
not round-trip cleanly).

Mappings cover the common entry types and fields. Unmapped fields are dropped
on export (with the rest of the conversion's best effort) rather than guessed.
Conversion is deterministic and offline.
"""

from pynakes.model import BibFile

EXPORT_FORMATS = ("csl-json", "ris", "mods", "endnote", "csv")
IMPORT_FORMATS = ("csl-json", "ris", "mods", "endnote")


def export_library(lib: BibFile, fmt: str) -> str:
    """Serialize *lib* to the named interchange format."""
    if fmt == "csl-json":
        from pynakes.interchange.csl import export_csl_json

        return export_csl_json(lib)
    if fmt == "ris":
        from pynakes.interchange.ris import export_ris

        return export_ris(lib)
    if fmt == "mods":
        from pynakes.interchange.mods import export_mods

        return export_mods(lib)
    if fmt == "endnote":
        from pynakes.interchange.endnote import export_endnote

        return export_endnote(lib)
    if fmt == "csv":
        from pynakes.interchange.csv import export_csv

        return export_csv(lib)
    raise ValueError(
        f"Unsupported export format {fmt!r}; choose one of {', '.join(EXPORT_FORMATS)}"
    )


def import_library(text: str, fmt: str) -> BibFile:
    """Parse interchange-format *text* into a new :class:`BibFile`."""
    if fmt == "csl-json":
        from pynakes.interchange.csl import import_csl_json

        return import_csl_json(text)
    if fmt == "ris":
        from pynakes.interchange.ris import import_ris

        return import_ris(text)
    if fmt == "mods":
        from pynakes.interchange.mods import import_mods

        return import_mods(text)
    if fmt == "endnote":
        from pynakes.interchange.endnote import import_endnote

        return import_endnote(text)
    raise ValueError(
        f"Unsupported import format {fmt!r}; choose one of {', '.join(IMPORT_FORMATS)}"
    )
