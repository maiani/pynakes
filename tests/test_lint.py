"""Tests for linting / validation checks."""

import ast
from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.identity import identity_class
from pynakes.lint import (
    CATEGORY_FIXERS,
    ISSUE_CATEGORIES,
    SEVERITIES,
    LintIssue,
    LintProfile,
    _lint_entry,
    _lint_profile_entry,
    issue_category,
    lint,
)
from pynakes.model import BibEntry

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


def test_key_pattern_expectation_uses_the_generation_collision_suffix() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: key-pattern: [auth]_[year];}\n"
        "@article{First, author = {Jane Doe}, year = {2024}, title = {One}}\n"
        "@article{Second, author = {Jane Doe}, year = {2024}, title = {Two}}\n"
    )

    issues = [issue for issue in lint(lib) if issue.type == "citation_key_pattern_mismatch"]

    assert [issue.message for issue in issues] == [
        "Entry 'First' does not match configured citation-key pattern '[auth]_[year]'; "
        "expected 'doe_2024'",
        "Entry 'Second' does not match configured citation-key pattern '[auth]_[year]'; "
        "expected 'doe_2024a'",
    ]


def test_key_pattern_check_exempts_entries_with_no_author_or_title() -> None:
    # A Supplemental Material placeholder has nothing to build a key from;
    # flagging its real key as a "mismatch" against a recomputed "Anon__"
    # would just be the same noise `keys generate` was fixed to not produce.
    lib = parse_bib(
        "@comment{pynakes-meta: key-pattern: [auth]_[year]_[veryshorttitle];}\n"
        "@misc{SM, note = {See Supplemental Material at [URL] for details.}}\n"
    )

    issues = [issue for issue in lint(lib) if issue.type == "citation_key_pattern_mismatch"]

    assert issues == []


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


def test_metadata_lint_reports_typoed_fetch_policy_tokens() -> None:
    lib = parse_bib("@comment{pynakes-meta: pinax-fetch-policy: bestpdf,unfamiliar;}\n")

    issues = [issue for issue in lint(lib) if issue.type == "invalid_metadata_value"]

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].category == "correctness"
    assert issues[0].key == "pinax-fetch-policy"
    assert issues[0].field == "pinax-fetch-policy"
    assert "unfamiliar" in issues[0].message


def test_metadata_lint_rejects_typoed_journal_style() -> None:
    lib = parse_bib("@comment{pynakes-meta: normalize-journal-style:abbreviate;}\n")

    issue_types = _types(lint(lib))

    assert "invalid_metadata_value" in issue_types
    assert "invalid_profile_setting" not in issue_types


def test_metadata_lint_rejects_typoed_journal_source() -> None:
    lib = parse_bib("@comment{pynakes-meta: normalize-journal-source:jabbref;}\n")

    issue_types = _types(lint(lib))

    assert "invalid_metadata_value" in issue_types


def test_metadata_lint_scopes_unknown_keys_to_pynakes_meta() -> None:
    # pynakes owns pynakes-meta and claims to understand every key there, so an
    # unknown key is drift. jabref-meta is JabRef's namespace and pynakes only
    # catalogues a subset of its vocabulary, so an uncatalogued JabRef key is
    # tolerated rather than reported.
    lib = parse_bib(
        "@comment{pynakes-meta: mystery-test-key: value;}\n"
        "@comment{jabref-meta: someFutureJabrefKey: value;}\n"
    )

    unknown = [issue for issue in lint(lib) if issue.type == "unknown_metadata_key"]

    assert [issue.key for issue in unknown] == ["mystery-test-key"]


def test_metadata_lint_flags_duplicate_blocks_within_and_across_comments() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta:\n"
        "pinax-fetch-policy: preprint\n"
        "pinax-fetch-policy: published\n"
        "}\n"
        "@comment{pynakes-meta: pinax-fetch-policy: source;}\n"
    )

    duplicates = [issue for issue in lint(lib) if issue.type == "duplicate_metadata_block"]

    assert len(duplicates) == 1
    assert duplicates[0].severity == "warning"
    assert duplicates[0].key == "pinax-fetch-policy"
    assert "3 blocks" in duplicates[0].message


def test_metadata_lint_tolerates_jabref_flat_groups_format() -> None:
    # The flat ``groups:`` format repeats the ``groups`` key once per group
    # line by design; it must not read as a duplicate metadata block.
    lib = parse_bib(
        "@comment{jabref-meta: groups:0 All Papers:;}\n"
        "@comment{jabref-meta: groups:1 Machine Learning:;}\n"
        "@comment{jabref-meta: groups:1 Blockchain:;}\n"
    )

    assert not [issue for issue in lint(lib) if issue.type == "duplicate_metadata_block"]


def test_metadata_lint_silent_on_valid_metadata() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:none;}\n"
        "@comment{pynakes-meta: pinax-fetch-policy:bestpdf;}\n"
        "@comment{jabref-meta: databaseType:bibtex;}\n"
    )

    drift = [
        issue
        for issue in lint(lib)
        if issue.type
        in {"unknown_metadata_key", "invalid_metadata_value", "duplicate_metadata_block"}
    ]
    assert drift == []


def test_lint_flags_missing_tex_source(tmp_path: Path) -> None:
    lib = parse_bib("@comment{pynakes-meta: tex-sources: paper.tex;}\n")

    issues = [issue for issue in lint(lib, base_dir=tmp_path) if issue.type == "missing_tex_source"]

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].category == "correctness"
    assert issues[0].field == "tex-sources"
    assert "paper.tex" in issues[0].message


def test_lint_silent_on_existing_tex_source(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(r"\cite{Smith2020}" "\n")
    lib = parse_bib("@comment{pynakes-meta: tex-sources: paper.tex;}\n")

    assert not [
        issue for issue in lint(lib, base_dir=tmp_path) if issue.type == "missing_tex_source"
    ]


def test_lint_skips_tex_source_check_without_base_dir() -> None:
    # No base_dir means relative tex-sources paths cannot be resolved, so the
    # check is skipped rather than reported against the wrong directory.
    lib = parse_bib("@comment{pynakes-meta: tex-sources: paper.tex;}\n")

    assert not [issue for issue in lint(lib) if issue.type == "missing_tex_source"]


def test_missing_required_field() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    # article needs author and journal too.
    assert "author" in fields
    assert "journal" in fields


def test_lint_entry_respects_explicit_empty_field_view() -> None:
    entry = BibEntry(
        "A",
        "article",
        {"author": "A. Author", "title": "T", "journal": "J", "year": "2024"},
    )

    issues = _lint_entry(entry, {}, dialect="bibtex")

    assert {issue.field for issue in issues if issue.type == "missing_required_field"} == {
        "author",
        "title",
        "journal",
        "year",
    }


def test_lint_profile_respects_explicit_empty_field_view() -> None:
    lib = parse_bib("@comment{pynakes-meta: lint-required-fields-article:url;}\n")
    entry = BibEntry("A", "article", {"url": "https://example.test"})

    issues = _lint_profile_entry(entry, lib, LintProfile(), None, {})

    assert [(issue.type, issue.field) for issue in issues] == [
        ("missing_profile_required_field", "url")
    ]


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


def test_lint_uses_inherited_fields_for_profile_and_doi_checks() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: lint-required-fields-article:url;}\n"
        "@xdata{shared,\n"
        "  journal = {Nature},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example},\n"
        "  url = {https://example.test}\n"
        "}\n"
        "@article{Paper,\n"
        "  author = {A. Author},\n"
        "  title = {Paper},\n"
        "  xdata = {shared}\n"
        "}\n"
    )

    issue_types = _types(lint(lib))

    assert "missing_required_field" not in issue_types
    assert "missing_profile_required_field" not in issue_types
    assert "missing_doi" not in issue_types


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


def test_missing_doi_is_reported_as_advisory_for_article() -> None:
    lib = parse_bib("@article{A,\n  author={X},\n  title={T},\n  journal={J},\n  year={2020}\n}\n")
    missing = [i for i in lint(lib) if i.type == "missing_doi"]
    assert len(missing) == 1
    # A missing DOI is an observation, not a defect: it must not bury an error.
    assert missing[0].severity == "info"
    assert missing[0].category == "consistency"
    assert missing[0].fixer is None


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
    assert all(i.severity == "info" for i in issues)
    assert all(i.category == "consistency" for i in issues)
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


def test_reports_repeated_fields_case_insensitively() -> None:
    lib = parse_bib("@misc{A, Title={First}, title={Second}}\n")
    issues = [issue for issue in lint(lib) if issue.type == "duplicate_field"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].key == "A"
    assert issues[0].field == "title"


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
        "@comment{pynakes-meta: normalize-protected-terms:OpenAI;}\n\n"
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


def test_lint_accepts_already_abbreviated_known_journal() -> None:
    # Regression: a field already holding the builtin abbreviation used to be
    # reported as unknown_journal because exact lookup only matched full
    # titles, not the abbreviated form itself.
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n"
        "@article{A,\n"
        "  author = {Jane Smith},\n"
        "  title = {A Study},\n"
        "  journal = {Phys. Rev. Lett.},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example}\n"
        "}\n"
    )

    issues = lint(lib)
    assert "unknown_journal" not in _types(issues)
    assert "journal_style_mismatch" not in _types(issues)


def test_lint_journal_source_none_disables_bundled_table() -> None:
    # normalize-journal-source: none opts out of the bundled JabRef table, so
    # an already-abbreviated value that only that table would recognize goes
    # back to being reported unknown.
    lib = parse_bib(
        "@comment{pynakes-meta: normalize-journal-style:abbreviated;}\n"
        "@comment{pynakes-meta: normalize-journal-source:none;}\n"
        "@article{A,\n"
        "  author = {Jane Smith},\n"
        "  title = {A Study},\n"
        "  journal = {Phys. Rev. Lett.},\n"
        "  year = {2024},\n"
        "  doi = {10.1234/example}\n"
        "}\n"
    )

    issues = lint(lib)
    assert "unknown_journal" in _types(issues)


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


def test_xdata_entry_produces_no_false_required_field_errors() -> None:
    # @xdata entries are structural data containers; they legitimately omit
    # author, title, year and must not be flagged for missing required fields.
    lib = parse_bib(
        "@xdata{pub, publisher = {Example Press}, location = {City}}\n"
        "@book{Book, xdata = {pub}, title = {T}, author = {Doe, J.}, year = {2020}}\n"
    )
    required_issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    xdata_issues = [i for i in required_issues if i.key == "pub"]
    assert not xdata_issues, f"false required-field errors on @xdata entry: {xdata_issues}"


def test_set_entry_produces_no_false_required_field_errors() -> None:
    # @set entries hold entryset membership metadata; they do not carry the
    # author/title/year/publisher fields of their member entries.
    lib = parse_bib(
        "@set{DatasetSet, entryset = {art1, art2}, entrysubtype = {research}}\n"
        "@article{art1, author = {A, B}, title = {T1}, journaltitle = {J}, date = {2024}}\n"
        "@article{art2, author = {C, D}, title = {T2}, journaltitle = {J}, date = {2024}}\n"
    )
    required_issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    set_issues = [i for i in required_issues if i.key == "DatasetSet"]
    assert not set_issues, f"false required-field errors on @set entry: {set_issues}"


def test_required_fields_for_techreport() -> None:
    lib = parse_bib("@techreport{T,\n  author = {X},\n  title = {T},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    assert "institution" in fields, (
        "techreport should require institution (or school) in the built-in rules"
    )


def test_required_fields_for_unpublished() -> None:
    lib = parse_bib("@unpublished{U,\n  title = {T},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    assert "author" in fields, "unpublished should require author in the built-in rules"


def test_required_fields_for_incollection() -> None:
    lib = parse_bib("@incollection{C,\n  author = {X},\n  title = {T},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    assert "booktitle" in fields, "incollection should require booktitle in the built-in rules"


def test_required_fields_for_manual() -> None:
    lib = parse_bib("@manual{M,\n  author = {X},\n  year = {2020}\n}\n")
    issues = [i for i in lint(lib) if i.type == "missing_required_field"]
    fields = {i.field for i in issues}
    assert "title" in fields, "manual should require title in the built-in rules"


@pytest.mark.parametrize(
    ("entry_type", "fields"),
    [
        # BibLaTeX required fields and aliases are taken from the official
        # BibLaTeX manual on CTAN, section 2.1 "Entry Types":
        # https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
        ("article", {"author", "title", "journaltitle", "year"}),
        ("book", {"author", "title", "year"}),
        ("mvbook", {"author", "title", "year"}),
        ("inbook", {"author", "title", "booktitle", "year"}),
        ("bookinbook", {"author", "title", "booktitle", "year"}),
        ("suppbook", {"author", "title", "booktitle", "year"}),
        ("booklet", {"author", "title", "year"}),
        ("collection", {"editor", "title", "year"}),
        ("mvcollection", {"editor", "title", "year"}),
        ("incollection", {"author", "title", "editor", "booktitle", "year"}),
        ("suppcollection", {"author", "title", "editor", "booktitle", "year"}),
        ("dataset", {"author", "title", "year"}),
        ("manual", {"author", "title", "year"}),
        ("misc", {"author", "title", "year"}),
        ("online", {"author", "title", "year", "doi"}),
        ("patent", {"author", "title", "number", "year"}),
        ("periodical", {"editor", "title", "year"}),
        ("suppperiodical", {"author", "title", "journaltitle", "year"}),
        ("proceedings", {"title", "year"}),
        ("mvproceedings", {"title", "year"}),
        ("inproceedings", {"author", "title", "booktitle", "year"}),
        ("reference", {"editor", "title", "year"}),
        ("mvreference", {"editor", "title", "year"}),
        ("inreference", {"author", "title", "editor", "booktitle", "year"}),
        ("report", {"author", "title", "type", "institution", "year"}),
        ("thesis", {"author", "title", "type", "institution", "year"}),
        ("unpublished", {"author", "title", "year"}),
        ("review", {"author", "title", "journaltitle", "year"}),
        ("software", {"author", "title", "year"}),
        ("conference", {"author", "title", "booktitle", "year"}),
        ("electronic", {"author", "title", "year", "doi"}),
        ("www", {"author", "title", "year", "doi"}),
        ("mastersthesis", {"author", "title", "institution", "year"}),
        ("phdthesis", {"author", "title", "institution", "year"}),
        ("techreport", {"author", "title", "institution", "year"}),
    ],
)
def test_biblatex_required_fields_cover_default_data_model(
    entry_type: str, fields: set[str]
) -> None:
    lib = parse_bib(f"@comment{{jabref-meta: databaseType:biblatex;}}\n@{entry_type}{{Key,\n}}\n")

    issues = [i for i in lint(lib) if i.type == "missing_required_field"]

    assert {issue.field for issue in issues} == fields


def test_biblatex_required_fields_differ_from_bibtex_book_publisher() -> None:
    entry = "@book{B,\n  author = {A. Author},\n  title = {T},\n  date = {2020}\n}\n"
    biblatex = parse_bib("@comment{jabref-meta: databaseType:biblatex;}\n" + entry)
    bibtex = parse_bib("@comment{jabref-meta: databaseType:bibtex;}\n" + entry)

    assert "publisher" not in {
        i.field for i in lint(biblatex) if i.type == "missing_required_field"
    }
    assert "publisher" in {i.field for i in lint(bibtex) if i.type == "missing_required_field"}


def test_custom_biblatex_entry_type_and_field_names_produce_no_errors() -> None:
    # Custom entry types (e.g. @online, @dataset) and fields with non-standard
    # characters (e.g. colons as used by BibLaTeX data-model extensions) must
    # parse and lint without false errors or tracebacks.
    lib = parse_bib(
        "@online{Dataset,\n"
        "  author = {Ångström, Anders},\n"
        "  title = {Données, 数据, and data},\n"
        "  date = {2025},\n"
        "  url = {https://example.test/dataset},\n"
        "  custom:field = {A project-defined value}\n"
        "}\n"
    )
    issues = lint(lib)
    error_issues = [i for i in issues if i.severity == "error"]
    assert not error_issues, f"unexpected errors on custom entry: {error_issues}"
    # The custom field must survive a round-trip through lint.
    assert lib.entries["Dataset"].fields["custom:field"] == "A project-defined value"


# --- severity and category axes --------------------------------------------


def test_every_emitted_issue_type_has_a_category() -> None:
    # Parses lint.py so a newly added check cannot silently inherit the
    # correctness fallback: every LintIssue type must be mapped explicitly.
    source = Path(__file__).resolve().parents[1] / "src" / "pynakes" / "lint.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    emitted = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "LintIssue"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert emitted, "no LintIssue constructions found; the parser needs updating"
    assert emitted <= set(ISSUE_CATEGORIES), (
        f"unmapped lint issue types: {sorted(emitted - set(ISSUE_CATEGORIES))}"
    )
    assert set(ISSUE_CATEGORIES) <= emitted, (
        f"stale lint issue types in ISSUE_CATEGORIES: {sorted(set(ISSUE_CATEGORIES) - emitted)}"
    )


def test_every_emitted_severity_is_declared() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "pynakes" / "lint.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    severities = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "LintIssue"
        and len(node.args) > 1
        and isinstance(node.args[1], ast.Constant)
    }
    assert severities <= set(SEVERITIES)


def test_every_category_declares_whether_a_command_fixes_it() -> None:
    assert set(CATEGORY_FIXERS) == set(ISSUE_CATEGORIES.values())
    # Only normalize and format may be named as fixers; lint never rewrites.
    assert {fixer for fixer in CATEGORY_FIXERS.values() if fixer} == {"normalize", "format"}


@pytest.mark.parametrize(
    "issue_type,category,fixer",
    [
        ("duplicate_key", "correctness", None),
        ("missing_required_field", "correctness", None),
        ("journal_style_mismatch", "content", "normalize"),
        ("malformed_doi", "content", "normalize"),
        ("noncanonical_entry_type_case", "layout", "format"),
        ("noncanonical_field_name_case", "layout", "format"),
        ("inconsistent_field", "consistency", None),
        ("missing_doi", "consistency", None),
        ("invalid_profile_setting", "profile", None),
    ],
)
def test_issue_category_and_fixer(issue_type: str, category: str, fixer: str | None) -> None:
    issue = LintIssue(issue_type, "warning", "message")

    assert issue.category == category
    assert issue.fixer == fixer
    assert issue.to_dict()["category"] == category
    assert issue.to_dict()["fixer"] == fixer


def test_unmapped_issue_type_falls_back_to_correctness() -> None:
    assert issue_category("a_check_added_later") == "correctness"


def test_layout_findings_are_advisory_and_point_at_format() -> None:
    lib = parse_bib(
        "@Article{A,\n  Author = {Jane Doe},\n  title = {A Study},\n"
        "  journal = {Nature},\n  YEAR = {2020},\n  doi = {10.1234/abc}\n}\n"
    )

    layout = [i for i in lint(lib) if i.category == "layout"]

    assert {i.type for i in layout} == {
        "noncanonical_entry_type_case",
        "noncanonical_field_name_case",
    }
    assert all(i.severity == "info" for i in layout)
    assert all(i.fixer == "format" for i in layout)


def test_advisory_findings_never_outrank_a_structural_error() -> None:
    # An entry missing a required field must remain the highest severity even
    # when it also has layout and consistency findings.
    lib = parse_bib("@Article{A,\n  Title = {A Study},\n  journal = {J},\n  YEAR = {2020}\n}\n")

    issues = lint(lib)

    assert any(i.severity == "error" and i.category == "correctness" for i in issues)
    assert {i.severity for i in issues if i.category in {"layout", "consistency"}} == {"info"}


# --- consistency scoping ---------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("@article{A, author={A}, title={T}, journal={J}, year={2020}, volume={1}}", "published"),
        ("@article{A, author={A}, title={T}, journal={J}, year={2020}, pages={1--9}}", "published"),
        # A venue alone publishes a conference paper; it has no volume or pages.
        ("@inproceedings{A, author={A}, title={T}, booktitle={Proc}, year={2020}}", "published"),
        # Publication evidence outranks eprint evidence.
        (
            "@article{A, author={A}, title={T}, journal={J}, year={2020}, volume={1},"
            " eprint={2301.00001}, archiveprefix={arXiv}}",
            "published",
        ),
        (
            "@article{A, author={A}, title={T}, year={2020}, eprint={2301.00001},"
            " archiveprefix={arXiv}}",
            "preprint",
        ),
        ("@misc{A, author={A}, title={T}, year={2020}, arxiv={2301.00001}}", "preprint"),
        ("@article{A, author={A}, title={T}, year={2020}, ssrn={123456}}", "preprint"),
        ("@book{A, author={A}, title={T}, publisher={P}, year={2020}}", "book"),
        ("@incollection{A, author={A}, title={T}, booktitle={B}, year={2020}}", "book"),
        ("@software{A, author={A}, title={T}, year={2020}}", "code"),
        ("@dataset{A, author={A}, title={T}, year={2020}}", "code"),
        ("@phdthesis{A, author={A}, title={T}, school={S}, year={2020}}", "unknown"),
    ],
)
def test_identity_class_of_an_entry(source: str, expected: str) -> None:
    entry = next(iter(parse_bib(source + "\n").entries.values()))

    assert identity_class(entry) == expected


def test_consistency_does_not_judge_preprints_against_published_peers() -> None:
    # Same entry type, different identity class: grouping by type alone would
    # flag both preprints for the volume their published peers carry.
    lib = parse_bib(
        "@article{P1, author={A}, title={T1}, journal={J}, year={2020}, volume={1}}\n"
        "@article{P2, author={B}, title={T2}, journal={J}, year={2021}, volume={2}}\n"
        "@article{P3, author={C}, title={T3}, journal={J}, year={2022}, volume={3}}\n"
        "@article{P4, author={D}, title={T4}, journal={J}, year={2023}, volume={4}}\n"
        "@article{E1, author={E}, title={T5}, year={2024}, eprint={2401.00001},"
        " archiveprefix={arXiv}}\n"
        "@article{E2, author={F}, title={T6}, year={2024}, eprint={2401.00002},"
        " archiveprefix={arXiv}}\n"
    )

    assert _consistency(lint(lib)) == []


def test_consistency_still_flags_a_gap_within_one_identity_class() -> None:
    # Scoping must not silence the check: comparable peers are still compared.
    lib = parse_bib(
        "@article{P1, author={A}, title={T1}, journal={J}, year={2020}, volume={1}}\n"
        "@article{P2, author={B}, title={T2}, journal={J}, year={2021}, volume={2}}\n"
        "@article{P3, author={C}, title={T3}, journal={J}, year={2022}, volume={3}}\n"
        "@article{P4, author={D}, title={T4}, journal={J}, year={2023}, pages={1--9}}\n"
    )

    assert _consistency(lint(lib)) == [("P4", "volume")]


@pytest.mark.parametrize("decoration", ["issn", "publisher", "month", "url", "abstract"])
def test_consistency_ignores_publisher_decoration(decoration: str) -> None:
    # A record from a metadata-sparse source legitimately lacks these; their
    # absence reports provenance, not a bibliographic gap.
    entries = "".join(
        f"@article{{P{index}, author={{A}}, title={{T{index}}}, journal={{J}},"
        f" year={{202{index}}}, volume={{{index}}}, {decoration}={{value}}}}\n"
        for index in range(1, 4)
    )
    sparse = "@article{Sparse, author={Z}, title={TZ}, journal={J}, year={2024}, volume={9}}\n"
    lib = parse_bib(entries + sparse)

    assert _consistency(lint(lib)) == []


# ---------------------------------------------------------------------------
# Source-line locations
# ---------------------------------------------------------------------------


def test_parser_records_entry_and_metadata_block_lines() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: dialect: biblatex;}\n"
        "\n"
        "@Article{Newton1687,\n"
        "  author = {Isaac Newton},\n"
        "  title = {Principia},\n"
        "}\n"
        "\n"
        "@book{Euler1748, title={Introductio}}\n"
    )

    entry_lines = {entry.key: entry.start_line for entry in lib.entries.values()}
    assert entry_lines == {"Newton1687": 3, "Euler1748": 8}
    assert all(block.start_line == 1 for block in lib.pynakes_metadata_blocks)


def test_entries_built_in_memory_have_no_line() -> None:
    assert BibEntry(key="A", type="article", fields={}).start_line is None


def test_lint_reports_the_declaring_entry_line() -> None:
    lib = parse_bib(
        "@article{First,\n"
        "  author = {A. Author},\n"
        "  title = {One},\n"
        "  journal = {J},\n"
        "  year = {2020}\n"
        "}\n"
        "\n"
        "@article{Second,\n"
        "  title = {Two}\n"
        "}\n"
    )

    issues = [
        issue
        for issue in lint(lib)
        if issue.type == "missing_required_field" and issue.key == "Second"
    ]

    assert issues
    assert all(issue.line == 8 for issue in issues)


def test_duplicate_key_finding_points_at_the_first_occurrence() -> None:
    lib = parse_bib("@article{A, title={One}}\n\n\n@article{A, title={Two}}\n")

    (dupe,) = [issue for issue in lint(lib) if issue.type == "duplicate_key"]

    assert dupe.line == 1


def test_metadata_finding_keeps_its_comment_line_over_a_colliding_citation_key() -> None:
    # An entry is deliberately keyed exactly like the unknown metadata key: the
    # block's own line must win, never the entry-line lookup.
    lib = parse_bib(
        "@article{unfamiliar-key,\n  author = {A},\n  title = {T},\n  journal = {J},\n"
        "  year = {2020}\n}\n"
        "\n"
        "@comment{pynakes-meta: unfamiliar-key: whatever;}\n"
    )

    (issue,) = [i for i in lint(lib) if i.type == "unknown_metadata_key"]

    assert issue.key == "unfamiliar-key"
    assert issue.line == 8


def test_line_numbers_survive_crlf_files() -> None:
    lib = parse_bib(
        "@article{First,\r\n  author = {A},\r\n  title = {T},\r\n  journal = {J},\r\n"
        "  year = {2020}\r\n}\r\n\r\n@book{Second, title={T}}\r\n"
    )

    entry_lines = {entry.key: entry.start_line for entry in lib.entries.values()}
    assert entry_lines == {"First": 1, "Second": 8}
    missing = [i for i in lint(lib) if i.type == "missing_required_field" and i.key == "Second"]
    assert missing
    assert all(i.line == 8 for i in missing)


def test_issue_to_dict_includes_line() -> None:
    issue = LintIssue("missing_required_field", "error", "m", key="A", field="author", line=12)

    assert issue.to_dict()["line"] == 12


def test_file_level_findings_have_no_line() -> None:
    lib = parse_bib("")

    (empty,) = [issue for issue in lint(lib) if issue.type == "no_entries"]

    assert empty.line is None
