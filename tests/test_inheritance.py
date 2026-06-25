"""BibLaTeX inheritance contract (crossref, xdata, xref, sets).

Unit tests pin the documented contract; the differential test validates it
against ``biber --tool --output-resolve`` as an oracle when biber is installed.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib

# --- the contract, pinned directly ----------------------------------------


def _resolve(src: str, key: str) -> dict[str, str]:
    return parse_bib(src).resolved_fields(key)


def test_xdata_injects_fields_verbatim() -> None:
    src = (
        "@xdata{info, publisher = {Press}, location = {City}}\n"
        "@book{b, xdata = {info}, title = {T}}\n"
    )
    fields = _resolve(src, "b")
    assert fields["publisher"] == "Press"
    assert fields["location"] == "City"
    assert fields["title"] == "T"


def test_xdata_supports_multiple_and_chained_references() -> None:
    src = (
        "@xdata{base, series = {S}}\n"
        "@xdata{a, publisher = {P}, xdata = {base}}\n"
        "@xdata{b, location = {L}}\n"
        "@book{book, xdata = {a, b}, title = {T}}\n"
    )
    fields = _resolve(src, "book")
    assert fields["publisher"] == "P"  # from a
    assert fields["location"] == "L"  # from b
    assert fields["series"] == "S"  # from a -> base (chained)


def test_crossref_remaps_title_to_booktitle_for_proceedings() -> None:
    src = (
        "@proceedings{p, title = {Proc}, subtitle = {Sub}, titleaddon = {Add}, editor = {E, E}}\n"
        "@inproceedings{c, crossref = {p}, title = {Paper}}\n"
    )
    fields = _resolve(src, "c")
    assert fields["booktitle"] == "Proc"
    assert fields["booksubtitle"] == "Sub"
    assert fields["booktitleaddon"] == "Add"
    assert fields["editor"] == "E, E"  # same-name inheritance
    assert fields["title"] == "Paper"  # own title is not overwritten
    assert "subtitle" not in fields  # source title fields are not inherited as-is


def test_crossref_remaps_title_to_maintitle_for_multivolume_parent() -> None:
    src = "@mvbook{p, title = {Main}, subtitle = {Sub}}\n@inbook{c, crossref = {p}, title = {Ch}}\n"
    fields = _resolve(src, "c")
    assert fields["maintitle"] == "Main"
    assert fields["mainsubtitle"] == "Sub"
    assert fields["title"] == "Ch"


def test_crossref_remaps_title_to_journaltitle_for_periodical() -> None:
    src = "@periodical{p, title = {Jrnl}, subtitle = {JS}}\n@article{c, crossref = {p}, title = {A}}\n"
    fields = _resolve(src, "c")
    assert fields["journaltitle"] == "Jrnl"
    assert fields["journalsubtitle"] == "JS"


def test_own_field_wins_over_inherited() -> None:
    src = (
        "@collection{p, publisher = {ParentPress}, note = {N}}\n"
        "@incollection{c, crossref = {p}, publisher = {OwnPress}}\n"
    )
    fields = _resolve(src, "c")
    assert fields["publisher"] == "OwnPress"
    assert fields["note"] == "N"


def test_xref_inherits_nothing() -> None:
    src = "@proceedings{p, title = {Proc}, editor = {E, E}}\n@inproceedings{c, xref = {p}}\n"
    fields = _resolve(src, "c")
    assert fields == {"xref": "p"}


def test_set_members_do_not_inherit_from_set() -> None:
    src = "@set{s, entryset = {a, b}}\n@book{a, title = {A}}\n@book{b, title = {B}}\n"
    assert _resolve(src, "a") == {"title": "A"}
    assert _resolve(src, "s") == {"entryset": "a, b"}


def test_missing_parent_and_cycles_are_tolerated() -> None:
    assert _resolve("@inbook{c, crossref = {ghost}, title = {T}}\n", "c") == {
        "crossref": "ghost",
        "title": "T",
    }
    cyclic = "@book{a, crossref = {b}, title = {A}}\n@book{b, crossref = {a}, title = {B}}\n"
    # No exception, and each entry keeps its own title.
    assert _resolve(cyclic, "a")["title"] == "A"
    assert _resolve(cyclic, "b")["title"] == "B"


def test_reference_field_is_not_propagated_to_child() -> None:
    src = "@proceedings{p, title = {Proc}, options = {x}}\n@inproceedings{c, crossref = {p}}\n"
    fields = _resolve(src, "c")
    assert "options" not in fields  # control fields never inherit
    assert fields["booktitle"] == "Proc"


# --- differential test against the biber oracle ----------------------------

# Fields whose inherited values we compare against biber. Restricted to the
# inheritance-relevant set so biber's own normalizations (e.g. year -> date,
# name re-splitting) do not make the comparison brittle.
_ORACLE_FIELDS = (
    "booktitle",
    "booksubtitle",
    "booktitleaddon",
    "maintitle",
    "mainsubtitle",
    "maintitleaddon",
    "journaltitle",
    "journalsubtitle",
    "publisher",
    "location",
)

_ORACLE_SOURCE = """\
@xdata{pub, publisher = {Example Press}, location = {Anytown}}
@proceedings{proc, title = {Proceedings of Examples}, subtitle = {Sub}, titleaddon = {Add}}
@mvbook{mvb, title = {Main Title}, subtitle = {Main Sub}}
@periodical{per, title = {The Journal}, subtitle = {JS}}

@inproceedings{paper, crossref = {proc}, xdata = {pub}, title = {A Paper}, author = {W, W}}
@inbook{chap, crossref = {mvb}, title = {Chapter}}
@article{art, crossref = {per}, title = {An Article}}
"""


def _biber_resolved(source: str, tmp_path: Path) -> dict[str, dict[str, str]]:
    in_bib = tmp_path / "in.bib"
    out_bib = tmp_path / "out.bib"
    in_bib.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            "biber",
            "--tool",
            "--output-resolve",
            "--output-format=bibtex",
            "--quiet",
            "--nolog",
            f"--output-file={out_bib}",
            str(in_bib),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    resolved: dict[str, dict[str, str]] = {}
    for block in re.finditer(r"@(\w+)\{([^,]+),(.*?)\n\}", out_bib.read_text(), re.S):
        key = block.group(2).strip()
        fields = {
            name.lower(): value
            for name, value in re.findall(r"(\w+)\s*=\s*\{([^}]*)\}", block.group(3))
        }
        resolved[key] = fields
    return resolved


@pytest.mark.skipif(shutil.which("biber") is None, reason="biber oracle not installed")
def test_inheritance_matches_biber_oracle(tmp_path: Path) -> None:
    oracle = _biber_resolved(_ORACLE_SOURCE, tmp_path)
    lib = parse_bib(_ORACLE_SOURCE)

    for key in ("paper", "chap", "art"):
        ours = lib.resolved_fields(key)
        theirs = oracle[key]
        for field in _ORACLE_FIELDS:
            assert ours.get(field) == theirs.get(field), (
                f"{key}.{field}: pynakes={ours.get(field)!r} biber={theirs.get(field)!r}"
            )
