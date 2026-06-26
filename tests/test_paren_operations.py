"""Exercise every modifying operation and the serializer fallback on ``(...)`` entries.

BibTeX 0.99d permits both ``@type{key,...}`` and ``@type(key,...)`` as entry
delimiters. This file verifies that pynakes surgical-edit operations preserve
the ``(...)`` delimiter form and that the serializer fallback (entries with no
``raw_content``) produces valid output.

Invariant verified throughout: round-trip fidelity for unmodified entries
(Principle #1), surgical-minimal edits for modified ones (Principle #2).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.editing import remove_entry_field, rename_entry_field, set_entry_field
from pynakes.fields import clear_field, rename_field
from pynakes.keys import regenerate_key, rename_key
from pynakes.lint import lint
from pynakes.model import BibEntry
from pynakes.normalize import normalize_dois, normalize_month_macros

# ---------------------------------------------------------------------------
# Shared fixture strings
# ---------------------------------------------------------------------------

_PAREN_BIB = """\
@article(ParenA,
  author = {Smith, Alice},
  title = {On Sorting Algorithms},
  journal = {ACM Surveys},
  year = {2022},
  month = jan,
  doi = {10.1145/example.2022}
)

@book(ParenB,
  author = {Brown, Bob},
  title = {Data Structures},
  publisher = {MIT Press},
  year = {2019}
)
"""

_PAREN_NO_DOI = """\
@article(NoDoi,
  author = {Doe, Jane},
  title = {A Survey},
  journal = {J. Algorithms},
  year = {2023},
  month = march
)
"""


# ---------------------------------------------------------------------------
# 1. Surgical field edits preserve the (...) delimiter
# ---------------------------------------------------------------------------


def test_set_entry_field_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    entry = lib.entries["ParenA"]
    changed = set_entry_field(entry, "year", "2023")
    assert changed is True
    assert "year = {2023}" in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


def test_remove_entry_field_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    entry = lib.entries["ParenA"]
    changed = remove_entry_field(entry, "doi")
    assert changed is True
    assert "doi" not in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


def test_rename_entry_field_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    entry = lib.entries["ParenA"]
    changed = rename_entry_field(entry, "doi", "url")
    assert changed is True
    assert "url = {" in entry.raw_content
    assert "doi" not in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


# ---------------------------------------------------------------------------
# 2. High-level field operations preserve the (...) delimiter
# ---------------------------------------------------------------------------


def test_clear_field_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    renamed = clear_field(lib, "doi")
    assert renamed >= 1
    entry = lib.entries["ParenA"]
    assert "doi" not in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


def test_rename_field_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    count = rename_field(lib, "year", "date")
    assert count >= 1
    entry = lib.entries["ParenA"]
    assert "date = {2022}" in entry.raw_content
    assert "year" not in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


# ---------------------------------------------------------------------------
# 3. Key operations preserve the (...) delimiter
# ---------------------------------------------------------------------------


def test_rename_key_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    renamed = rename_key(lib, "ParenA", "Smith2022Sorting")
    assert renamed == 1
    assert "Smith2022Sorting" in lib.entries
    entry = lib.entries["Smith2022Sorting"]
    assert "@article(Smith2022Sorting," in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


def test_regenerate_key_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_BIB)
    result = regenerate_key(lib, "ParenA")
    assert result is not None
    old, new = result
    entry = lib.entries[new]
    assert f"@article({new}," in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


# ---------------------------------------------------------------------------
# 4. Normalize operations on (...) entries
# ---------------------------------------------------------------------------


def test_normalize_month_preserves_paren_delimiter() -> None:
    lib = parse_bib(_PAREN_NO_DOI)
    changed = normalize_month_macros(lib)
    assert changed == 1
    entry = lib.entries["NoDoi"]
    # march → mar (canonical BibTeX macro)
    assert "month = mar" in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")


def test_normalize_doi_preserves_paren_delimiter() -> None:
    # DOI in a paren entry must get normalized via a surgical edit.
    src = "@article(DiParen,\n  doi = {10.1145/example.2022}\n)"
    lib = parse_bib(src)
    count, warnings = normalize_dois(lib)
    entry = lib.entries["DiParen"]
    # Whether count is 0 (already canonical) or 1, the delimiter must survive.
    assert entry.raw_content.rstrip().endswith(")")
    assert not warnings


# ---------------------------------------------------------------------------
# 5. Lint on (...) entries produces no false errors
# ---------------------------------------------------------------------------


def test_lint_on_paren_entry_no_false_errors() -> None:
    lib = parse_bib(_PAREN_BIB)
    issues = lint(lib)
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, f"Unexpected errors on paren entries: {errors}"


# ---------------------------------------------------------------------------
# 6. Serializer fallback: entries without raw_content write valid BibTeX
# ---------------------------------------------------------------------------


def test_serializer_fallback_writes_braced_entry() -> None:
    # Programmatically created entries have no raw_content. The writer must
    # reconstruct them using {...} delimiters, producing valid BibTeX.
    entry = BibEntry(
        key="NewEntry",
        type="article",
        fields={
            "author": "Fallback, Test",
            "title": "Testing the Serializer Fallback",
            "journal": "Journal of Tests",
            "year": "2024",
        },
        raw_content=None,
    )
    lib = parse_bib("")
    lib.entries["NewEntry"] = entry

    output = write_bib(lib)
    assert "@article{NewEntry," in output
    assert "author = {Fallback, Test}" in output
    assert "year = {2024}" in output

    # Must round-trip: re-parse yields the same fields.
    lib2 = parse_bib(output)
    assert lib2.entries["NewEntry"].fields == entry.fields


def test_new_field_on_paren_entry_stays_surgical() -> None:
    # Adding a field that does NOT exist in raw_content is still handled via
    # a surgical insert (set_raw_field appends before the closing delimiter).
    # The (…) delimiter and unmodified=False are both preserved.
    lib = parse_bib(_PAREN_BIB)
    entry = lib.entries["ParenB"]
    changed = set_entry_field(entry, "address", "Cambridge, MA")
    assert changed is True
    assert entry.modified is False
    assert "address = {Cambridge, MA}" in entry.raw_content
    assert entry.raw_content.rstrip().endswith(")")

    # Output is still valid and semantically correct.
    output = write_bib(lib)
    assert "@book(ParenB," in output
    lib2 = parse_bib(output)
    assert lib2.entries["ParenB"].fields["address"] == "Cambridge, MA"
    assert lib2.entries["ParenB"].fields["title"] == "Data Structures"


def test_serializer_fallback_entry_without_raw_content_uses_braces() -> None:
    # The ``modified`` flag is set only when there is no ``raw_content`` at all.
    # Such entries (programmatically built, not parsed) are reconstructed with
    # ``{...}`` braces — the only form the reconstructor emits.
    entry = BibEntry(
        key="Rebuilt",
        type="book",
        fields={"author": "Rebuilt, Author", "title": "No Raw Content", "year": "2024"},
        raw_content=None,
    )
    set_entry_field(entry, "publisher", "Test Press")
    assert entry.modified is True

    lib = parse_bib("")
    lib.entries["Rebuilt"] = entry
    output = write_bib(lib)
    assert "@book{Rebuilt," in output
    assert "publisher = {Test Press}" in output

    lib2 = parse_bib(output)
    assert lib2.entries["Rebuilt"].fields["publisher"] == "Test Press"


# ---------------------------------------------------------------------------
# 7. Differential: bibtex oracle accepts pynakes output for paren entries
# ---------------------------------------------------------------------------


def _run_bibtex(bib_path: Path, tmp: Path) -> subprocess.CompletedProcess[str]:
    stem = bib_path.stem
    aux = tmp / f"{stem}.aux"
    aux.write_text(
        f"\\relax\n\\citation{{*}}\n\\bibstyle{{plain}}\n\\bibdata{{{stem}}}\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bibtex", stem],
        cwd=tmp,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("bibtex") is None, reason="bibtex oracle not installed")
def test_pynakes_output_of_paren_entries_accepted_by_bibtex(tmp_path: Path) -> None:
    """pynakes write output for paren-form entries must be accepted by bibtex."""
    lib = parse_bib(_PAREN_BIB)
    out_bib = tmp_path / "paren.bib"
    out_bib.write_text(write_bib(lib), encoding="utf-8")

    result = _run_bibtex(out_bib, tmp_path)
    errors = [ln for ln in result.stdout.splitlines() if ln.startswith("I couldn't")]
    assert not errors, f"bibtex rejected pynakes paren output:\n{result.stdout}"


@pytest.mark.skipif(shutil.which("bibtex") is None, reason="bibtex oracle not installed")
def test_modified_paren_entry_output_accepted_by_bibtex(tmp_path: Path) -> None:
    """After a surgical edit on a paren entry the written output is still valid bibtex."""
    lib = parse_bib(_PAREN_BIB)
    set_entry_field(lib.entries["ParenA"], "year", "2023")
    out_bib = tmp_path / "modified_paren.bib"
    out_bib.write_text(write_bib(lib), encoding="utf-8")

    result = _run_bibtex(out_bib, tmp_path)
    errors = [ln for ln in result.stdout.splitlines() if ln.startswith("I couldn't")]
    assert not errors, f"bibtex rejected modified paren output:\n{result.stdout}"
