"""Tests for ``scrub``: removing private content before a public release.

Covers the operation module (what counts as private and who decides), the
engine staging that keeps the released copy byte-identical apart from the
removals, and the CLI's creation envelope and ``--check`` gate.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.metadata import metadata_value, set_metadata
from pynakes.scrub import DEFAULT_PRIVATE_FIELDS, ScrubOptions, scrub_library

runner = CliRunner()

PRIVATE = """@comment{jabref-meta: databaseType:bibtex;}

@comment{jabref-meta: grouping:
0 AllEntriesGroup:;
1 StaticGroup:To check\\;0\\;1\\;\\;\\;\\;;
}

@comment{pynakes-meta: pinax-files-dir:library.files;}

@comment{Reminder: ask the librarian about the 1713 second edition.}

@article{newton1687,
  author    = {Newton, Isaac},
  title     = {Philosophiae Naturalis Principia Mathematica},
  journal   = {Royal Society},
  year      = {1687},
  abstract  = {Axioms and laws of motion.},
  keywords  = {mechanics},
  groups    = {To check},
  owner     = {a.reader},
  timestamp = {2020-01-02},
  priority  = {prio1},
  file      = {:/home/a.reader/papers/newton.pdf:PDF},
}

@book{euclid300bc,
  author = {Euclid},
  title  = {Elements},
  year   = {-300},
}
"""

CLEAN = """@article{darwin1859,
  author = {Darwin, Charles},
  title  = {On the Origin of Species},
  year   = {1859},
}
"""


def _bib(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")  # exact bytes on Windows too
    return path


# --- what counts as private ------------------------------------------------


def test_default_set_removes_private_fields_and_keeps_bibliographic_ones() -> None:
    lib = parse_bib(PRIVATE)
    report = scrub_library(lib)

    entry = lib.entries["newton1687"]
    assert set(entry.fields) == {"author", "title", "journal", "year", "abstract", "keywords"}
    assert report.fields == {"file": 1, "groups": 1, "owner": 1, "priority": 1, "timestamp": 1}
    assert report.entries == 1
    assert report.field_removals == 5


def test_abstract_and_keywords_are_not_private_by_default() -> None:
    # Bibliographic content a reader may want is never dropped unasked.
    assert "abstract" not in DEFAULT_PRIVATE_FIELDS
    assert "keywords" not in DEFAULT_PRIVATE_FIELDS
    assert "note" not in DEFAULT_PRIVATE_FIELDS


def test_extra_fields_and_globs() -> None:
    lib = parse_bib(
        "@article{hooke1665,\n"
        "  title = {Micrographia},\n"
        "  abstract = {Observations by magnifying glasses.},\n"
        "  bdsk-file-1 = {cHJpdmF0ZQ==},\n"
        "  bdsk-file-2 = {bW9yZQ==},\n"
        "}\n"
    )
    report = scrub_library(lib, ScrubOptions(extra_fields=("abstract",)))

    assert set(lib.entries["hooke1665"].fields) == {"title"}
    assert report.fields == {"bdsk-file-1": 1, "bdsk-file-2": 1, "abstract": 1}


def test_field_names_match_case_insensitively() -> None:
    lib = parse_bib("@book{euclid300bc,\n  title = {Elements},\n  Owner = {a.reader},\n}\n")
    scrub_library(lib)
    assert set(lib.entries["euclid300bc"].fields) == {"title"}


def test_keep_field_overrides_the_default_set() -> None:
    lib = parse_bib(PRIVATE)
    report = scrub_library(lib, ScrubOptions(keep_fields=("file", "groups")))

    entry = lib.entries["newton1687"]
    assert "file" in entry.fields
    assert "groups" in entry.fields
    assert "owner" not in entry.fields
    assert set(report.fields) == {"owner", "timestamp", "priority"}


def test_comma_separated_names_are_split() -> None:
    lib = parse_bib(PRIVATE)
    report = scrub_library(lib, ScrubOptions(extra_fields=("abstract,keywords",)))
    assert "abstract" in report.fields
    assert "keywords" in report.fields


def test_metadata_and_free_comments_are_separate_counts() -> None:
    lib = parse_bib(PRIVATE)
    report = scrub_library(lib)

    assert report.metadata_blocks == 3
    assert report.metadata_keys == ["databaseType", "grouping", "pinax-files-dir"]
    assert report.comments == 1
    assert lib.jabref_metadata_blocks == []
    assert lib.pynakes_metadata_blocks == []
    assert metadata_value(lib, "grouping") is None


def test_repeated_metadata_key_is_named_once_but_counted_per_block() -> None:
    # JabRef writes one `groups:` comment per node.
    lib = parse_bib(
        "@comment{jabref-meta: groups:0 All Papers:;}\n"
        "@comment{jabref-meta: groups:1 Optics:;}\n\n"
        "@book{euclid300bc,\n  title = {Elements},\n}\n"
    )
    report = scrub_library(lib)

    assert report.metadata_blocks == 2
    assert report.metadata_keys == ["groups"]


def test_percent_comment_lines_count_as_free_comments() -> None:
    lib = parse_bib("% working note\n@book{euclid300bc,\n  title = {Elements},\n}\n")
    report = scrub_library(lib)
    assert report.comments == 1


def test_keep_switches_leave_each_kind_alone() -> None:
    lib = parse_bib(PRIVATE)
    report = scrub_library(lib, ScrubOptions(fields=False, comments=False, metadata=False))

    assert report.clean
    assert report.patterns == []
    assert "owner" in lib.entries["newton1687"].fields
    assert len(lib.metadata_blocks) == 3


def test_clean_library_reports_nothing_to_remove() -> None:
    report = scrub_library(parse_bib(CLEAN))
    assert report.clean
    assert report.to_dict()["clean"] is True


# --- the library's own policy ----------------------------------------------


def test_library_metadata_extends_and_narrows_the_field_set() -> None:
    lib = parse_bib(PRIVATE)
    set_metadata(lib, "scrub-fields", "abstract")
    set_metadata(lib, "scrub-keep-fields", "groups")
    scrub_library(lib)

    entry = lib.entries["newton1687"]
    assert "abstract" not in entry.fields
    assert "groups" in entry.fields


def test_library_metadata_can_turn_block_removal_off() -> None:
    lib = parse_bib(PRIVATE)
    set_metadata(lib, "scrub-comments", "false")
    set_metadata(lib, "scrub-metadata", "false")
    report = scrub_library(lib)

    assert report.comments == 0
    assert report.metadata_blocks == 0
    assert report.fields  # fields are still scrubbed


def test_keep_all_fields_via_metadata_glob() -> None:
    lib = parse_bib(PRIVATE)
    set_metadata(lib, "scrub-keep-fields", "*")
    report = scrub_library(lib)

    assert report.fields == {}
    assert "owner" in lib.entries["newton1687"].fields


def test_explicit_option_overrides_library_metadata() -> None:
    lib = parse_bib(PRIVATE)
    set_metadata(lib, "scrub-comments", "false")
    report = scrub_library(lib, ScrubOptions(comments=True))
    assert report.comments == 1


# --- engine staging and round-trip fidelity --------------------------------


def test_scrubbed_output_changes_only_what_was_removed(tmp_path: Path) -> None:
    coll = Bibliography.open(_bib(tmp_path, "library.bib", PRIVATE))
    coll.scrub()
    output = coll.preview()

    # The untouched entry survives byte-for-byte, and the scrubbed one keeps
    # the alignment of every field it still has.
    untouched = PRIVATE[PRIVATE.index("@book{euclid300bc,") :].rstrip("\n")
    assert untouched in output
    assert "  author    = {Newton, Isaac}," in output
    assert "  abstract  = {Axioms and laws of motion.}," in output
    assert "owner" not in output
    assert "jabref-meta" not in output
    assert "librarian" not in output


def test_removed_blocks_leave_no_blank_gap(tmp_path: Path) -> None:
    coll = Bibliography.open(_bib(tmp_path, "library.bib", PRIVATE))
    coll.scrub()
    output = coll.preview()

    assert output.startswith("@article{newton1687,")
    assert "\n\n\n" not in output


def test_scrubbed_output_reparses_to_the_same_library(tmp_path: Path) -> None:
    coll = Bibliography.open(_bib(tmp_path, "library.bib", PRIVATE))
    coll.scrub()
    reparsed = parse_bib(coll.preview())

    assert reparsed.entries.keys() == ["newton1687", "euclid300bc"]
    assert reparsed.metadata_blocks == []
    assert reparsed.raw_comments == []


def test_scrub_commits_in_place(tmp_path: Path) -> None:
    path = _bib(tmp_path, "library.bib", PRIVATE)
    coll = Bibliography.open(path)
    coll.scrub()
    result = coll.commit()

    assert result.modified
    assert "owner" not in path.read_text()


def test_scrubbing_a_clean_library_writes_nothing(tmp_path: Path) -> None:
    coll = Bibliography.open(_bib(tmp_path, "library.bib", CLEAN))
    report = coll.scrub()

    assert report.clean
    assert coll.preview() == CLEAN
    assert coll.diff() == ""


def test_scrubbing_twice_is_a_no_op(tmp_path: Path) -> None:
    # The second pass sees blanked comment slots left by the first.
    coll = Bibliography.open(_bib(tmp_path, "library.bib", PRIVATE))
    coll.scrub()
    scrubbed = coll.preview()
    second = coll.scrub()

    assert second.clean
    assert coll.preview() == scrubbed


# --- CLI -------------------------------------------------------------------


def test_cli_writes_a_scrubbed_copy_and_leaves_the_source_alone(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(source), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert source.read_text() == PRIVATE
    assert "owner" not in out.read_text()
    assert "@book{euclid300bc," in out.read_text()


def test_cli_copies_an_already_clean_library_unchanged(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", CLEAN)
    out = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(source), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "nothing private found" in result.output
    assert out.read_text() == CLEAN


def test_cli_json_envelope(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(source), "--out", str(out), "--json"])

    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["action"] == "scrub"
    assert data["file"] == str(out)
    assert data["written"] is True
    assert data["dry_run"] is False
    assert data["warnings"] == []
    assert data["source"] == str(source)
    assert data["removed"]["entries"] == 1
    assert data["removed"]["metadata_blocks"] == 3
    assert data["removed"]["comments"] == 1
    assert {item["field"] for item in data["removed"]["fields"]} == {
        "file",
        "groups",
        "owner",
        "priority",
        "timestamp",
    }


def test_cli_requires_an_output_path(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    result = runner.invoke(app, ["scrub", str(source), "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["error"] == "InvalidInput"
    assert "--out" in data["message"]


def test_cli_check_excludes_out(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    result = runner.invoke(
        app, ["scrub", str(source), "--check", "--out", str(tmp_path / "x.bib"), "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "InvalidInput"


def test_cli_check_gates_on_private_content(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    result = runner.invoke(app, ["scrub", str(source), "--check", "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["action"] == "scrub-check"
    assert data["clean"] is False
    assert data["written"] is False
    assert source.read_text() == PRIVATE


def test_cli_check_passes_on_a_clean_library(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", CLEAN)
    result = runner.invoke(app, ["scrub", str(source), "--check", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["clean"] is True


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(source), "--out", str(out), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["written"] is False
    assert not out.exists()


def test_cli_diff_reports_removals_against_the_source(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(source), "--out", str(out), "--diff"])

    assert f"--- {source} (original)" in result.output
    assert "-  owner     = {a.reader}," in result.output
    assert "-@comment{jabref-meta: databaseType:bibtex;}" in result.output


def test_cli_keep_flags(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(
        app,
        [
            "scrub",
            str(source),
            "--out",
            str(out),
            "--keep-metadata",
            "--keep-comments",
            "--keep-field",
            "file",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["removed"]["metadata_blocks"] == 0
    assert data["removed"]["comments"] == 0
    text = out.read_text()
    assert "jabref-meta" in text
    assert "librarian" in text
    assert "file      = {:/home/a.reader/papers/newton.pdf:PDF}," in text
    assert "owner" not in text


def test_cli_keep_fields_scrubs_blocks_only(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    out = tmp_path / "public.bib"
    result = runner.invoke(
        app, ["scrub", str(source), "--out", str(out), "--keep-fields", "--json"]
    )

    data = json.loads(result.output)
    assert data["removed"]["fields"] == []
    assert data["removed"]["metadata_blocks"] == 3
    assert "owner" in out.read_text()


def test_cli_scrubs_in_place_when_out_is_the_input(tmp_path: Path) -> None:
    source = _bib(tmp_path, "library.bib", PRIVATE)
    result = runner.invoke(app, ["scrub", str(source), "--out", str(source), "--backup"])

    assert result.exit_code == 0, result.output
    assert "owner" not in source.read_text()
    assert (tmp_path / "library.bib.bak").read_text() == PRIVATE


def test_cli_rejects_stdin(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scrub", "-", "--out", str(tmp_path / "x.bib"), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "InvalidInput"
