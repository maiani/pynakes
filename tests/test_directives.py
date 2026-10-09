"""Per-entry directives: parsing, lint waivers, engine staging, and ``ref directive``."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.canonical import CanonicalLayout, write_bib_canonical
from pynakes.cli import app
from pynakes.directives import (
    EntryDirective,
    directive_problem,
    entry_directives,
    format_directive,
    parse_directive,
)
from pynakes.engine import Bibliography
from pynakes.lint import entry_ignore_rules, is_waived, lint

runner = CliRunner()

NEWTON = (
    "@article{Newton1687,\n"
    "  author = {Newton, Isaac},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  journal = {Royal Society},\n"
    "  year = {1687}\n"
    "}\n"
)
DARWIN = (
    "@article{Darwin1858,\n"
    "  author = {Darwin, Charles},\n"
    "  title = {On the Tendency of Species to Form Varieties},\n"
    "  journal = {Journal of the Proceedings of the Linnean Society},\n"
    "  year = {1858}\n"
    "}\n"
)


def _types(issues) -> list[str]:
    return [issue.type for issue in issues]


# --- grammar ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("% pynakes: ignore missing_doi\n", EntryDirective("ignore", ("missing_doi",))),
        (
            "% pynakes: ignore missing_doi, layout -- no DOI -- ever",
            EntryDirective("ignore", ("missing_doi", "layout"), "no DOI -- ever"),
        ),
        ("%%  Pynakes:  IGNORE a b,c --", EntryDirective("ignore", ("a", "b", "c"))),
        ("@comment{pynakes: ignore layout}", EntryDirective("ignore", ("layout",))),
        ("@Comment(pynakes: keep-key)", EntryDirective("keep-key")),
        ("% a note about the work", None),
        ("@comment{pynakes-meta: lint-ignore: layout}", None),
    ],
)
def test_parse_directive(comment: str, expected: EntryDirective | None) -> None:
    assert parse_directive(comment) == expected


def test_format_directive_round_trips_through_the_parser() -> None:
    line = format_directive("ignore", ("missing_doi", "layout"), "no DOI assigned")

    assert line == "% pynakes: ignore missing_doi, layout -- no DOI assigned"
    assert parse_directive(line) == EntryDirective(
        "ignore", ("missing_doi", "layout"), "no DOI assigned"
    )


@pytest.mark.parametrize(
    ("directive", "problem"),
    [
        (EntryDirective("ignore", ("missing_doi", "consistency")), None),
        (EntryDirective("ignore", ("missing_profile_required_field:volume",)), None),
        (EntryDirective("keep-key"), "unknown directive"),
        (EntryDirective("ignore"), "needs at least one argument"),
        (EntryDirective("ignore", ("missing_dio",)), "missing_dio"),
        (EntryDirective("ignore", ("missing_doi:",)), "needs a field"),
    ],
)
def test_directive_problem(directive: EntryDirective, problem: str | None) -> None:
    found = directive_problem(directive)
    assert found is None if problem is None else problem in (found or "")


def test_only_a_comment_attached_to_the_entry_is_its_directive() -> None:
    # A blank line makes the comment a free, file-level comment.
    lib = parse_bib(
        "% pynakes: ignore layout\n\n"
        + NEWTON
        + "\n% pynakes: ignore missing_doi\n@comment{pynakes: ignore consistency}\n"
        + DARWIN
    )

    by_key = {
        entry.key: [d.text() for d in entry_directives(lib).get(id(entry), [])]
        for entry in lib.entries.values()
    }

    assert by_key == {
        "Newton1687": [],
        "Darwin1858": ["pynakes: ignore missing_doi", "pynakes: ignore consistency"],
    }


# --- lint ------------------------------------------------------------------


def test_ignore_directive_waives_only_its_own_entry() -> None:
    lib = parse_bib("% pynakes: ignore missing_doi\n" + NEWTON + "\n" + DARWIN)

    issues = lint(lib)
    rules = entry_ignore_rules(lib)
    waived = [(issue.key, issue.type) for issue in issues if is_waived(issue, rules)]

    # lint() itself still reports every finding; the command applies waivers.
    assert _types(issues).count("missing_doi") == 2
    assert waived == [("Newton1687", "missing_doi")]


def test_ignore_with_a_field_waives_only_that_field() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: lint-required-fields: volume, number;}\n\n"
        "% pynakes: ignore missing_profile_required_field:volume -- no volumes\n" + NEWTON
    )

    rules = entry_ignore_rules(lib)
    left = [
        issue.field
        for issue in lint(lib)
        if issue.type == "missing_profile_required_field" and not is_waived(issue, rules)
    ]

    assert left == ["number"]


def test_invalid_and_unused_directives_are_findings() -> None:
    lib = parse_bib(
        "% pynakes: ignore missing_dio\n% pynakes: keep-key\n% pynakes: ignore layout\n" + NEWTON
    )

    issues = [issue for issue in lint(lib) if issue.key == "Newton1687"]
    messages = {issue.type: [] for issue in issues}
    for issue in issues:
        messages[issue.type].append(issue.message)

    assert len(messages["invalid_entry_directive"]) == 2
    # `layout` matches nothing: the entry is already lowercase.
    assert messages["unused_entry_directive"] == [
        "Entry 'Newton1687' ignores 'layout', but lint reports no such finding for it; "
        "remove the directive"
    ]
    rules = entry_ignore_rules(lib)
    assert not any(is_waived(issue, rules) for issue in issues)


def test_format_keeps_a_directive_with_its_entry_when_sorting() -> None:
    lib = parse_bib(NEWTON + "\n% pynakes: ignore missing_doi\n" + DARWIN)

    output = write_bib_canonical(lib, CanonicalLayout(entry_order="key"))

    assert "% pynakes: ignore missing_doi\n@article{Darwin1858," in output
    assert output.index("Darwin1858") < output.index("Newton1687")


# --- engine ----------------------------------------------------------------


def _open(tmp_path: Path, text: str) -> Bibliography:
    path = tmp_path / "refs.bib"
    path.write_bytes(text.encode())
    return Bibliography.open(path)


def test_adding_a_directive_inserts_one_line_and_nothing_else(tmp_path: Path) -> None:
    source = NEWTON + "\n" + DARWIN
    coll = _open(tmp_path, source)

    assert coll.add_entry_directive("Darwin1858", "ignore", ("missing_doi",), "no DOI")

    expected = source.replace(
        "@article{Darwin1858", "% pynakes: ignore missing_doi -- no DOI\n@article{Darwin1858"
    )
    assert coll.preview() == expected
    coll.commit()
    reopened = Bibliography.open(tmp_path / "refs.bib")
    assert [d.args for d in reopened.entry_directives("Darwin1858")] == [("missing_doi",)]


def test_adding_keeps_crlf_and_works_on_the_first_entry(tmp_path: Path) -> None:
    source = NEWTON.replace("\n", "\r\n")
    coll = _open(tmp_path, source)

    coll.add_entry_directive("Newton1687", "ignore", ("missing_doi",))

    assert coll.preview() == "% pynakes: ignore missing_doi\r\n" + source


def test_adding_present_arguments_changes_only_a_new_reason(tmp_path: Path) -> None:
    source = "% pynakes: ignore missing_doi, layout -- old\n" + NEWTON
    coll = _open(tmp_path, source)

    assert not coll.add_entry_directive("Newton1687", "ignore", ("missing_doi",))
    assert coll.preview() == source
    assert coll.add_entry_directive("Newton1687", "ignore", ("missing_doi",), "new")
    assert coll.preview() == source.replace("-- old", "-- new")


def test_removing_arguments_rewrites_or_drops_the_line(tmp_path: Path) -> None:
    source = (
        NEWTON + "\n% pynakes: ignore missing_doi, layout -- why\n"
        "@comment{pynakes: ignore consistency}\n" + DARWIN
    )
    coll = _open(tmp_path, source)

    assert coll.remove_entry_directive("Darwin1858", "ignore", ("layout", "consistency")) == 2

    assert coll.preview() == NEWTON + "\n% pynakes: ignore missing_doi -- why\n" + DARWIN
    assert coll.remove_entry_directive("Darwin1858", "ignore") == 1
    assert coll.preview() == NEWTON + "\n" + DARWIN


def test_directive_staging_refuses_unknown_duplicate_or_invalid(tmp_path: Path) -> None:
    coll = _open(tmp_path, NEWTON + "\n" + NEWTON)

    with pytest.raises(KeyError):
        coll.add_entry_directive("Euclid300", "ignore", ("missing_doi",))
    with pytest.raises(ValueError, match="duplicated"):
        coll.add_entry_directive("Newton1687", "ignore", ("missing_doi",))
    with pytest.raises(ValueError, match="unknown directive"):
        coll.add_entry_directive("Newton1687", "keep-key")


# --- CLI -------------------------------------------------------------------


def test_ref_directive_adds_and_lint_honors_it(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(NEWTON)

    result = runner.invoke(
        app,
        ["ref", "directive", str(bib), "Newton1687", "ignore", "missing_doi", "--reason", "none"],
    )
    assert result.exit_code == 0, result.output
    assert bib.read_text() == "% pynakes: ignore missing_doi -- none\n" + NEWTON

    linted = json.loads(runner.invoke(app, ["lint", str(bib), "--json"]).output)
    assert all(issue["type"] != "missing_doi" for issue in linted["issues"])
    assert linted["summary"]["suppressed"] == 1


def test_ref_directive_envelope_and_remove(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("% pynakes: ignore missing_doi, layout\n" + NEWTON)

    result = runner.invoke(
        app,
        ["ref", "directive", str(bib), "Newton1687", "ignore", "layout", "--remove", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "ref_directive"
    assert payload["modified"] is True
    assert payload["modified_entries"] == 1
    assert payload["directive"] == {"verb": "ignore", "args": ["layout"], "reason": None}
    assert payload["removed"] is True
    assert bib.read_text() == "% pynakes: ignore missing_doi\n" + NEWTON

    again = runner.invoke(
        app,
        ["ref", "directive", str(bib), "Newton1687", "ignore", "layout", "--remove", "--json"],
    )
    payload = json.loads(again.output)
    assert payload["modified"] is False
    assert payload["warnings"][0]["type"] == "directive_not_found"


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (["Newton1687", "ignore", "missing_dio"], "InvalidInput"),
        (["Newton1687", "keep-key"], "InvalidInput"),
        (["Newton1687", "ignore", "layout", "--remove", "--reason", "x"], "InvalidInput"),
        (["Euclid300", "ignore", "missing_doi"], "KeyNotFound"),
    ],
)
def test_ref_directive_refusals(tmp_path: Path, argv: list[str], error: str) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(NEWTON)

    result = runner.invoke(app, ["ref", "directive", str(bib), *argv, "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == error
    assert bib.read_text() == NEWTON


def test_directives_survive_a_jabref_rewrite() -> None:
    # Recorded from JabKit 6.0-beta.1 `convert` (BibTeX to BibTeX) with a field
    # formatter forcing every entry to be rewritten: JabRef realigns and
    # reorders fields but keeps each comment directly above its entry.
    jabref_output = (
        "% pynakes: ignore missing_doi -- venue assigns no DOIs\n"
        "@Article{Newton1687,\n"
        "  author              = {Newton, Isaac},\n"
        "  title               = {PHILOSOPHIAE NATURALIS PRINCIPIA MATHEMATICA},\n"
        "  journal             = {Royal Society},\n"
        "  year                = {1687},\n"
        "}\n"
        "\n"
        "@comment{pynakes: ignore layout}\n"
        "@Book{Darwin1859,\n"
        "  author              = {Darwin, Charles},\n"
        "  title               = {ON THE ORIGIN OF SPECIES},\n"
        "  publisher           = {John Murray},\n"
        "  year                = {1859},\n"
        "}\n"
    )
    lib = parse_bib(jabref_output)

    rules = entry_ignore_rules(lib)
    unwaived = [issue.type for issue in lint(lib) if not is_waived(issue, rules)]

    assert set(rules) == {"Newton1687", "Darwin1859"}
    assert "missing_doi" not in unwaived
    assert unwaived == ["noncanonical_entry_type_case"]  # Newton's @Article stays
