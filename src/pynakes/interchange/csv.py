"""CSV export for bibliography review, spreadsheets, and audits.

CSV is export-only: repeated authors, braced capitalization, string macros,
linked files, comments, and BibTeX metadata do not round-trip cleanly, so
``pynakes convert refs.bib --to csv`` exports to CSV but ``--from csv`` is
not supported.
"""

import csv
import io

from pynakes.model import BibFile

# Stable default column order for CSV export.
_DEFAULT_COLUMNS = [
    "key",
    "type",
    "author",
    "title",
    "year",
    "date",
    "journal",
    "journaltitle",
    "booktitle",
    "doi",
    "url",
    "eprint",
    "archiveprefix",
    "volume",
    "number",
    "pages",
    "publisher",
    "keywords",
]


def export_csv(lib: BibFile, columns: list[str] | None = None) -> str:
    """Serialize *lib* to CSV text.

    Parameters
    ----------
    lib:
        The bibliography to export.
    columns:
        Column names (fields) to include. Defaults to :data:`_DEFAULT_COLUMNS`.

    Returns
    -------
    str
        CSV-encoded text with a header row and one row per entry.

    Notes
    -----
    Field values are written as stored/resolved strings. Authors are not split
    into separate columns; keywords are written as stored (typically
    semicolon- or comma-separated). Missing fields produce empty cells.
    """
    if columns is None:
        columns = _DEFAULT_COLUMNS

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()

    for entry in lib.entries.values():
        if not entry.key.strip():
            continue
        row = {"key": entry.key, "type": entry.type}
        row.update(entry.fields)
        writer.writerow(row)

    return buf.getvalue()
