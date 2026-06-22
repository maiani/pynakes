"""Tests for linting / validation checks."""

from pathlib import Path

from pynakes.bibtex_parser import parse_bib
from pynakes.lint import lint

FIXTURES = Path(__file__).parent / "fixtures"


def _types(issues) -> set[str]:
    return {i.type for i in issues}


def test_detects_duplicate_keys() -> None:
    lib = parse_bib("@article{A,year={1}}\n@article{A,year={2}}\n")
    issues = lint(lib)
    dupes = [i for i in issues if i.type == "duplicate_key"]
    assert len(dupes) == 1
    assert dupes[0].severity == "error"
    assert dupes[0].key == "A"


def test_flags_empty_citation_key() -> None:
    # An entry with no key must surface as an error, not be silently dropped.
    lib = parse_bib("@article{,\n  author = {Bob White},\n  title = {No Key}\n}\n")
    assert len(lib.entries) == 1
    issues = [i for i in lint(lib) if i.type == "empty_key"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    # ... and it is not double-reported as a duplicate-key set.
    assert not [i for i in lint(lib) if i.type == "duplicate_key"]


def test_warns_when_no_entries_found() -> None:
    # Non-BibTeX / wrong-file content must not return a clean "0 issues".
    lib = parse_bib("this is not bibtex at all }{@@@\n")
    issues = lint(lib)
    assert [i.type for i in issues] == ["no_entries"]
    assert issues[0].severity == "warning"


def test_missing_required_field() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    # article needs author and journal too.
    assert "author" in fields
    assert "journal" in fields


def test_biblatex_variants_satisfy_requirements() -> None:
    # journaltitle satisfies journal; date satisfies year.
    lib = parse_bib(
        "@article{A,\n  author = {X},\n  title = {T},\n  journaltitle = {J},\n  date = {2020}\n}\n"
    )
    assert not [i for i in lint(lib) if i.type == "missing_required_field"]


def test_malformed_doi() -> None:
    lib = parse_bib(
        "@article{A,\n  author={X},\n  title={T},\n  journal={J},\n  year={2020},\n"
        "  doi = {not-a-doi}\n}\n"
    )
    assert "malformed_doi" in _types(lint(lib))


def test_valid_doi_with_url_prefix_ok() -> None:
    lib = parse_bib(
        "@article{A,\n  author={X},\n  title={T},\n  journal={J},\n  year={2020},\n"
        "  doi = {https://doi.org/10.1234/abc.def}\n}\n"
    )
    assert "malformed_doi" not in _types(lint(lib))


def test_missing_doi_warns_for_article() -> None:
    lib = parse_bib("@article{A,\n  author={X},\n  title={T},\n  journal={J},\n  year={2020}\n}\n")
    missing = [i for i in lint(lib) if i.type == "missing_doi"]
    assert len(missing) == 1
    assert missing[0].severity == "warning"


def test_malformed_groups() -> None:
    lib = parse_bib(
        "@article{A,\n  author={X},\n  title={T},\n  journal={J},\n  year={2020},\n"
        "  doi={10.1/x},\n  groups = {AI;; ML}\n}\n"
    )
    assert "malformed_groups" in _types(lint(lib))


def test_no_false_positives_on_clean_entry() -> None:
    lib = parse_bib(
        "@article{A,\n  author = {Jane Doe},\n  title = {A Study},\n"
        "  journal = {Nature},\n  year = {2020},\n  doi = {10.1234/abc}\n}\n"
    )
    assert lint(lib) == []


def test_reports_noncanonical_identifier_case_without_inspecting_values() -> None:
    lib = parse_bib(
        "@Article{A,\n  TITLE = {A field-like phrase: FIELD = value},\n  DOI = {10.1234/abc}\n}\n"
    )

    issues = lint(lib)
    assert [(issue.type, issue.field) for issue in issues] == [
        ("noncanonical_entry_type_case", None),
        ("noncanonical_field_name_case", "title"),
        ("noncanonical_field_name_case", "doi"),
        ("missing_required_field", "author"),
        ("missing_required_field", "journal"),
        ("missing_required_field", "year"),
    ]


def test_fixtures_lint_without_errors() -> None:
    # simple.bib should produce no error-severity issues (only DOI warnings).
    lib = parse_bib((FIXTURES / "simple.bib").read_text())
    errors = [i for i in lint(lib) if i.severity == "error"]
    assert errors == []
