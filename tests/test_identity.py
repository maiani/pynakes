"""Tests for conservative work-matching evidence."""

from pynakes.bibtex_parser import parse_bib
from pynakes.identity import (
    WorkEvidence,
    WorkIdentifiers,
    compare_work_evidence,
    evidence_from_entry,
    find_exact_matches,
    normalize_work_identifier,
)


def test_identifier_normalization_excludes_author_identity() -> None:
    assert normalize_work_identifier("doi", "https://doi.org/10.5555/ABC").value == ("10.5555/abc")
    assert normalize_work_identifier("arxiv", "arXiv:2301.00001v2").value == "2301.00001"
    assert normalize_work_identifier("ORCID", "0000-0000-0000-0000") is None
    assert normalize_work_identifier("doi", "not a DOI") is None


def test_repository_preprint_identifier_also_contributes_doi_evidence() -> None:
    identifiers = WorkIdentifiers.from_mapping({"biorxiv": "10.1101/2020.01.01.123456"})

    assert identifiers.by_kind() == {
        "biorxiv": frozenset({"10.1101/2020.01.01.123456"}),
        "doi": frozenset({"10.1101/2020.01.01.123456"}),
    }


def test_matching_identifier_is_exact_and_explained() -> None:
    left = WorkEvidence(WorkIdentifiers.from_mapping({"doi": "10.5555/example"}))
    right = WorkEvidence(
        WorkIdentifiers.from_mapping({"doi": "https://doi.org/10.5555/EXAMPLE", "pmid": "123"})
    )

    match = compare_work_evidence(left, right)

    assert match.status == "exact"
    assert match.score == 1.0
    assert match.reasons == ("matching doi: 10.5555/example",)
    assert match.is_match


def test_conflicting_same_kind_identifier_overrides_other_matching_evidence() -> None:
    left = WorkEvidence(WorkIdentifiers.from_mapping({"doi": "10.5555/example", "pmid": "123"}))
    right = WorkEvidence(WorkIdentifiers.from_mapping({"doi": "10.5555/example", "pmid": "456"}))

    match = compare_work_evidence(left, right)

    assert match.status == "conflict"
    assert match.reasons == ("conflicting pmid: 123 != 456",)
    assert not match.is_match


def test_metadata_similarity_is_probable_not_exact() -> None:
    left = evidence_from_entry(
        parse_bib(
            "@article{A, author={Ada Lovelace and Charles Babbage}, "
            "title={A Practical Engine for Symbolic Computation}, year={1843}}\n"
        ).entries["A"]
    )
    right = evidence_from_entry(
        parse_bib(
            "@article{B, author={Ada Lovelace}, "
            "title={A practical engine for symbolic computation}, year={1843}}\n"
        ).entries["B"]
    )

    match = compare_work_evidence(left, right)

    assert match.status == "probable"
    assert match.score == 1.0
    assert "shared author: lovelace" in match.reasons


def test_metadata_without_sufficient_evidence_is_unknown() -> None:
    left = WorkEvidence(title_fingerprint="short", authors=("lovelace",), year="1843")
    right = WorkEvidence(title_fingerprint="short", authors=("lovelace",), year="1843")

    match = compare_work_evidence(left, right)

    assert match.status == "unknown"
    assert match.reasons == ("insufficient title evidence",)


def test_find_exact_matches_uses_provider_and_cross_provider_identifiers() -> None:
    library = parse_bib(
        "@article{Published, doi={10.1101/2020.01.01.123456}}\n"
        "@techreport{Nber, number={w12345}}\n"
        "@article{IssueNumber, number={12345}}\n"
    )

    assert find_exact_matches(library, {"biorxiv": "10.1101/2020.01.01.123456"}) == ["Published"]
    assert find_exact_matches(library, {"nber": "w12345"}) == ["Nber"]


def test_find_exact_matches_blocks_overlap_even_when_other_evidence_conflicts() -> None:
    library = parse_bib("@article{Existing, doi={10.5555/example}, pmid={123}}\n")

    assert find_exact_matches(
        library,
        {"doi": "10.5555/example", "pmid": "456"},
    ) == ["Existing"]
