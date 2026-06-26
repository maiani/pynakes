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


def test_crossref_inherits_required_fields_without_mutating_child() -> None:
    lib = parse_bib(
        "@proceedings{Conference,\n"
        "  title = {Proceedings},\n"
        "  booktitle = {Conference Book},\n"
        "  year = {2024}\n"
        "}\n"
        "@inproceedings{Paper,\n"
        "  author = {A. Author},\n"
        "  title = {Paper},\n"
        "  crossref = {Conference}\n"
        "}\n"
    )

    assert lib.entries["Paper"].fields.get("booktitle") is None
    assert lib.resolved_fields("Paper")["booktitle"] == "Conference Book"
    assert not [issue for issue in lint(lib) if issue.type == "missing_required_field"]


def test_crossref_child_fields_override_inherited_values() -> None:
    lib = parse_bib(
        "@proceedings{Parent, booktitle = {Parent Book}, year = {2024}}\n"
        "@inproceedings{Child,\n"
        "  author = {A. Author},\n"
        "  title = {Paper},\n"
        "  booktitle = {Child Book},\n"
        "  crossref = {Parent}\n"
        "}\n"
    )

    assert lib.resolved_fields("Child")["booktitle"] == "Child Book"


def test_crossref_cycle_is_tolerated() -> None:
    lib = parse_bib(
        "@inproceedings{First, author = {A. Author}, title = {Paper}, crossref = {Second}}\n"
        "@proceedings{Second, title = {Proceedings}, crossref = {First}}\n"
    )

    fields = lib.resolved_fields("First")

    assert fields["author"] == "A. Author"  # inherited from the parent
    assert fields["title"] == "Paper"  # own title kept despite the cycle
    assert fields["booktitle"] == "Proceedings"  # parent's title remapped, no infinite loop


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


def _consistency(issues):
    return [(i.key, i.field) for i in issues if i.type == "inconsistent_field"]


def test_field_consistency_flags_majority_field_missing_from_one_entry() -> None:
    # doi is present on 3 of 4 articles; only the one lacking it is flagged.
    lib = parse_bib(
        "@article{a1, author={A}, title={T1}, journal={J}, year={2020}, doi={10.1/a}}\n"
        "@article{a2, author={B}, title={T2}, journal={J}, year={2021}, doi={10.1/b}}\n"
        "@article{a3, author={C}, title={T3}, journal={J}, year={2022}}\n"
        "@article{a4, author={D}, title={T4}, journal={J}, year={2023}, doi={10.1/d}}\n"
    )
    issues = [i for i in lint(lib) if i.type == "inconsistent_field"]
    assert _consistency(issues) == [("a3", "doi")]
    assert all(i.severity == "warning" for i in issues)
    assert "3 of 4" in issues[0].message


def test_field_consistency_ignores_non_majority_and_universal_fields() -> None:
    # 'note' on exactly half (not a majority); 'year' on all (universal).
    lib = parse_bib(
        "@article{a1, author={A}, title={T1}, journal={J}, year={2020}, note={n}}\n"
        "@article{a2, author={B}, title={T2}, journal={J}, year={2021}, note={n}}\n"
        "@article{a3, author={C}, title={T3}, journal={J}, year={2022}}\n"
        "@article{a4, author={D}, title={T4}, journal={J}, year={2023}}\n"
    )
    assert _consistency(lint(lib)) == []


def test_field_consistency_needs_at_least_three_entries_of_a_type() -> None:
    lib = parse_bib(
        "@article{a1, author={A}, title={T1}, journal={J}, year={2020}, doi={10.1/a}}\n"
        "@article{a2, author={B}, title={T2}, journal={J}, year={2021}}\n"
    )
    assert _consistency(lint(lib)) == []


def test_field_consistency_ignores_management_and_structural_fields() -> None:
    # groups/file/timestamp vary legitimately and must never be flagged.
    lib = parse_bib(
        "@article{a1, author={A}, title={T1}, journal={J}, year={2020}, groups={X}, file={a.pdf}}\n"
        "@article{a2, author={B}, title={T2}, journal={J}, year={2021}, groups={Y}, file={b.pdf}}\n"
        "@article{a3, author={C}, title={T3}, journal={J}, year={2022}}\n"
    )
    assert _consistency(lint(lib)) == []


def test_field_consistency_respects_crossref_inheritance() -> None:
    # booktitle is inherited by every child via crossref, so none is flagged;
    # only the genuinely-missing majority field (doi) is.
    lib = parse_bib(
        "@proceedings{p, title={Proc}}\n"
        "@inproceedings{c1, author={A}, title={X1}, crossref={p}, doi={1}}\n"
        "@inproceedings{c2, author={B}, title={X2}, crossref={p}, doi={2}}\n"
        "@inproceedings{c3, author={C}, title={X3}, crossref={p}}\n"
    )
    flagged = _consistency(lint(lib))
    assert ("c3", "doi") in flagged
    assert all(field != "booktitle" for _, field in flagged)


def test_reports_undefined_string_references_in_entries_and_definitions() -> None:
    lib = parse_bib(
        "@string{venue = publisher # { Press}}\n"
        "@article{A,\n"
        "  author = {Jane Doe},\n"
        "  title = {A Study},\n"
        "  journal = venue # { Letters},\n"
        "  year = {2024},\n"
        "  month = jun #\n"
        "    june,\n"
        "  doi = {10.1234/abc}\n"
        "}\n"
    )

    issues = [issue for issue in lint(lib) if issue.type == "undefined_string_reference"]

    assert [(issue.key, issue.field) for issue in issues] == [(None, "venue"), ("A", "month")]
    assert all(issue.severity == "error" for issue in issues)
    assert "publisher" in issues[0].message
    assert "june" in issues[1].message


def test_accepts_defined_and_standard_bibtex_string_references() -> None:
    lib = parse_bib(
        "@string{venue = {Journal}}\n"
        "@article{A,\n"
        "  author = {Jane Doe},\n"
        "  title = {A Study},\n"
        "  journal = venue # { Letters},\n"
        "  year = {2024},\n"
        "  month = jun,\n"
        "  doi = {10.1234/abc}\n"
        "}\n"
    )

    assert "undefined_string_reference" not in _types(lint(lib))


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


def test_lint_checks_the_stored_profile() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
        "@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n"
        "@comment{pynakes-meta: lint-required-fields-article:url;}\n"
        "@comment{pynakes-meta: protected-terms:OpenAI;}\n\n"
        "@article{WrongKey,\n"
        "  author = {Jane Smith},\n"
        "  title = {OpenAI and DNA},\n"
        "  journal = {Nature Machine Intelligence},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example}\n"
        "}\n"
    )

    issues = lint(lib)
    assert {
        "citation_key_pattern_mismatch",
        "journal_style_mismatch",
        "missing_profile_required_field",
        "title_capitalization_unprotected",
    } <= _types(issues)
    assert all(issue.severity == "warning" for issue in issues)


def test_lint_reports_unknown_journals_when_style_is_configured() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n"
        "@article{A,\n"
        "  author = {Jane Smith},\n"
        "  title = {Unmapped journal},\n"
        "  journal = {Some Obscure Local Gazette},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example}\n"
        "}\n"
    )

    issues = lint(lib)
    assert "unknown_journal" in _types(issues)
    unknown = next(issue for issue in issues if issue.type == "unknown_journal")
    assert unknown.field == "journal"


def test_profile_can_disable_title_protection() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-protect-titles:false;}\n"
        "@article{A,\n"
        "  author = {Jane Smith},\n"
        "  title = {DNA repair},\n"
        "  journal = {Nature},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example}\n"
        "}\n"
    )

    assert "title_capitalization_unprotected" not in _types(lint(lib))
