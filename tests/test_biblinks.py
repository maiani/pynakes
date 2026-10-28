"""Bibliography links: declaration, coordinated edits and validation."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import biblinks as links
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.lint import lint

runner = CliRunner()

MASTER = """@book{Newton1687,
  author = {Isaac Newton},
  title = {Philosophiae Naturalis Principia Mathematica},
  year = {1687},
}

@inproceedings{Euler1748,
  author = {Leonhard Euler},
  title = {Introductio},
  crossref = {Acta1748},
}

@proceedings{Acta1748,
  booktitle = {Acta Eruditorum},
  year = {1748},
}
"""

CHAPTER = """@book{Newton1687,
  author = {Isaac   Newton},
  title = "Philosophiae Naturalis Principia Mathematica",
  year = 1687,
  groups = {Thesis},
}

@inproceedings{Euler1748,
  author = {Leonhard Euler},
  title = {Introductio},
  booktitle = {Acta Eruditorum},
  year = {1748},
}
"""


def _pair(tmp_path: Path, chapter: str = CHAPTER) -> tuple[Path, Path]:
    (tmp_path / "chapters").mkdir()
    master = tmp_path / "master.bib"
    child = tmp_path / "chapters" / "ch1.bib"
    master.write_text(MASTER, encoding="utf-8")
    child.write_text(chapter, encoding="utf-8")
    return child, master


def _run(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.output)


def _link(child: Path, master: Path, *extra: str) -> dict:
    code, data = _run("biblink", "add", str(child), str(master), *extra)
    assert code == 0, data
    return data


def _findings(child: Path) -> list[tuple[str, str | None, str | None]]:
    code, data = _run("biblink", "check", str(child))
    assert code == 0, data
    return [(f["type"], f.get("key"), f.get("field")) for f in data["links"][0]["findings"]]


def test_a_declaration_parses_with_defaults_and_rejects_bad_options() -> None:
    parsed = links.parse_declaration("../master.bib", "parent")
    assert (parsed.path, parsed.constraint, parsed.flow) == (
        "../master.bib",
        "field-subset",
        "down",
    )
    spaced = links.parse_declaration("My Thesis.bib flow=up constraint=key-subset", "child")
    assert (spaced.path, spaced.constraint, spaced.flow) == ("My Thesis.bib", "key-subset", "up")
    with pytest.raises(ValueError, match="constraint"):
        links.parse_declaration("a.bib constraint=superset", "parent")
    with pytest.raises(ValueError, match="names no file"):
        links.parse_declaration("constraint=key-subset", "parent")


def test_link_add_declares_the_link_at_both_ends_relative_to_each(tmp_path: Path) -> None:
    child, master = _pair(tmp_path)
    data = _link(child, master)
    assert data["modified"] is True and data["other"]["modified"] is True
    assert "biblink-parents: ../master.bib constraint=field-subset flow=down" in child.read_text()
    assert (
        "biblink-children: chapters/ch1.bib constraint=field-subset flow=down" in master.read_text()
    )
    # Running it again changes nothing; a new constraint replaces the old one in place.
    assert _link(child, master)["modified"] is False
    _link(child, master, "--constraint", "key-subset")
    assert child.read_text().count("biblink-parents:") == 1
    assert "constraint=key-subset" in master.read_text()


def test_a_faithful_copy_holds_despite_delimiters_whitespace_inheritance_and_local_fields(
    tmp_path: Path,
) -> None:
    child, master = _pair(tmp_path)
    _link(child, master)
    code, data = _run("biblink", "check", str(child), "--strict")
    assert code == 0, data
    report = data["links"][0]
    assert report["ok"] and report["complete"] and report["reciprocal"]
    assert report["checked_entries"] == 2
    assert data["source_sha256"]


def test_field_subset_reports_drift_type_mismatch_and_missing_keys(tmp_path: Path) -> None:
    drifted = (
        CHAPTER.replace("Principia Mathematica", "{Principia} Mathematica")
        .replace("@inproceedings{Euler1748", "@incollection{Euler1748")
        .replace("  year = {1748},\n", "  year = {1748},\n  note = {Chapter two},\n")
        + "\n@book{Leibniz1684, title = {Nova Methodus}}\n"
    )
    child, master = _pair(tmp_path, drifted)
    _link(child, master)
    assert sorted(_findings(child), key=str) == sorted(
        [
            ("field_drift", "Newton1687", "title"),
            ("type_mismatch", "Euler1748", None),
            ("field_drift", "Euler1748", "note"),
            ("missing_key", "Leibniz1684", None),
        ],
        key=str,
    )
    code, data = _run("biblink", "check", str(child), "--strict")
    assert code == 1 and data["ok"] is False


def test_key_subset_ignores_field_drift(tmp_path: Path) -> None:
    child, master = _pair(tmp_path, CHAPTER.replace("Introductio", "Introductio in analysin"))
    _link(child, master, "--constraint", "key-subset")
    assert _findings(child) == []


def test_duplicate_keys_are_ambiguous_not_guessed(tmp_path: Path) -> None:
    child, master = _pair(tmp_path, CHAPTER + "\n@book{Newton1687, title = {Opticks}}\n")
    _link(child, master)
    assert ("ambiguous_key", "Newton1687", None) in _findings(child)


def test_one_sided_disagreeing_and_unreadable_links_are_reported(tmp_path: Path) -> None:
    child, master = _pair(tmp_path)
    child.write_text(
        "@comment{pynakes-meta:\nbiblink-parents: ../master.bib\n}\n\n" + CHAPTER, encoding="utf-8"
    )
    assert [f[0] for f in _findings(child)] == ["not_reciprocal"]

    _link(child, master)
    master.write_text(master.read_text().replace("flow=down", "flow=none"), encoding="utf-8")
    assert [f[0] for f in _findings(child)] == ["declaration_mismatch"]

    master.unlink()
    code, data = _run("biblink", "check", str(child))
    report = data["links"][0]
    assert code == 0 and report["complete"] is False and not report["ok"]
    assert [f["type"] for f in report["findings"]] == ["unreadable_file"]


def test_link_remove_clears_both_ends_or_reports_no_link(tmp_path: Path) -> None:
    child, master = _pair(tmp_path)
    _link(child, master)
    code, data = _run("biblink", "remove", str(master), str(child))
    assert code == 0, data
    assert "link-" not in child.read_text() and "link-" not in master.read_text()
    assert [d["role"] for d in data["removed"]] == ["child", "parent"]

    code, data = _run("biblink", "remove", str(master), str(child))
    assert code == 1 and data["error"] == "KeyNotFound"


def test_a_stale_digest_for_either_file_writes_nothing(tmp_path: Path) -> None:
    child, master = _pair(tmp_path)
    before = (child.read_bytes(), master.read_bytes())
    code, data = _run("biblink", "add", str(child), str(master), "--expect-other-sha256", "0" * 64)
    assert code == 2 and data["error"] == "ExternalModification"
    assert (child.read_bytes(), master.read_bytes()) == before


def test_a_failed_second_write_restores_the_first(tmp_path: Path, monkeypatch) -> None:
    child, master = _pair(tmp_path)
    before = child.read_bytes()
    first, second = Bibliography.open(child), Bibliography.open(master)
    links.stage_link(first, second, "field-subset", "down")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(second, "commit", fail)
    with pytest.raises(OSError, match="disk full"):
        links.commit_together([first, second])
    assert child.read_bytes() == before
    assert "biblink-children" not in master.read_text()


def test_link_list_and_lint_read_the_declarations(tmp_path: Path) -> None:
    child, master = _pair(tmp_path)
    _link(child, master)
    code, data = _run("biblink", "list", str(master))
    assert code == 0
    assert [(row["role"], row["path"], row["exists"]) for row in data["links"]] == [
        ("child", "chapters/ch1.bib", True)
    ]
    bad = parse_bib("@comment{pynakes-meta:\nbiblink-parents: a.bib flow=sideways\n}\n")
    assert "invalid_metadata_value" in [issue.type for issue in lint(bad)]


def _sync(file: Path, *args: str) -> dict:
    code, data = _run("biblink", "sync", str(file), *args)
    assert code == 0, data
    return data


def test_sync_down_repairs_the_child_and_never_deletes(tmp_path: Path) -> None:
    drifted = CHAPTER.replace("Introductio", "Introductio in analysin").replace(
        "  year = {1748},\n", "  year = {1748},\n  note = {Chapter two},\n"
    )
    child, master = _pair(tmp_path, drifted.replace("@inproceedings{Euler", "@book{Euler"))
    _link(child, master)
    before = master.read_bytes()
    data = _sync(child)
    changes = data["files"][0]["changes"]
    assert {(c["key"], c["field"], c["new"]) for c in changes} == {
        ("Euler1748", "title", "Introductio"),
        ("Euler1748", None, "inproceedings"),
    }
    assert [s["field"] for s in data["skipped"] if s.get("field")] == ["note"]
    assert master.read_bytes() == before
    assert "note = {Chapter two}" in child.read_text()
    assert _findings(child) == [("field_drift", "Euler1748", "note")]


def test_sync_up_needs_the_flow_and_leaves_inherited_fields(tmp_path: Path) -> None:
    drifted = CHAPTER.replace("Introductio", "Introductio in analysin").replace(
        "{Acta Eruditorum}", "{Acta Eruditorum Lipsiae}"
    )
    child, master = _pair(tmp_path, drifted)
    _link(child, master)
    refused = _sync(child, "--direction", "up")
    assert refused["modified"] is False
    assert "flow=down does not allow a sync up" in refused["skipped"][0]["reason"]

    _link(child, master, "--flow", "both")
    data = _sync(child, "--direction", "up")
    assert [(c["key"], c["field"]) for c in data["files"][1]["changes"]] == [("Euler1748", "title")]
    assert "title = {Introductio in analysin}" in master.read_text()
    inherited = [s for s in data["skipped"] if s.get("field") == "booktitle"]
    assert inherited and "inherits" in inherited[0]["reason"]


def test_two_parents_disagreeing_is_a_conflict_left_unwritten(tmp_path: Path) -> None:
    child, master = _pair(tmp_path, CHAPTER.replace("Introductio", "Introductio in analysin"))
    other = tmp_path / "other.bib"
    other.write_text(
        MASTER.replace("{Introductio}", "{Introductio, editio altera}"), encoding="utf-8"
    )
    _link(child, master)
    _link(child, other)
    data = _sync(child)
    assert [(c["key"], c["field"]) for c in data["conflicts"]] == [("Euler1748", "title")]
    assert "Introductio in analysin" in child.read_text()


def test_sync_skips_key_subset_and_one_sided_links(tmp_path: Path) -> None:
    child, master = _pair(tmp_path, CHAPTER.replace("Introductio", "Introductio in analysin"))
    _link(child, master, "--constraint", "key-subset")
    assert "key-subset" in _sync(child)["skipped"][0]["reason"]
    _link(child, master)
    master.write_text(MASTER, encoding="utf-8")
    assert "does not declare the link alike" in _sync(child)["skipped"][0]["reason"]


def test_sync_refuses_a_stale_digest_for_a_linked_file(tmp_path: Path) -> None:
    child, master = _pair(tmp_path, CHAPTER.replace("Introductio", "Introductio in analysin"))
    _link(child, master, "--flow", "both")
    before = master.read_bytes()
    code, data = _run(
        "biblink",
        "sync",
        str(child),
        "--direction",
        "up",
        "--expect-linked-sha256",
        f"{master}={'0' * 64}",
    )
    assert code == 2 and data["error"] == "ExternalModification"
    assert master.read_bytes() == before
