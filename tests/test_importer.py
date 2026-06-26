"""Reference import tests (DOI and arXiv)."""

from urllib.error import HTTPError, URLError

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.importer import (
    ARXIV,
    DOI,
    ArxivImportError,
    CitationKeyConflictError,
    DOIImportError,
    DuplicateArxivError,
    DuplicateDOIError,
    UnsupportedIdentifierError,
    canonical_doi,
    entry_from_bibtex,
    existing_keys_for_arxiv,
    existing_keys_for_doi,
    extract_doi_from_journal_url,
    fetch_bibtex_for_doi,
    normalize_arxiv,
    normalize_doi,
    prepare_imported_arxiv,
    prepare_imported_entry,
    prepare_imported_reference,
    render_entry,
    resolve_identifier,
)

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v2</id>
    <published>2023-01-02T10:00:00Z</published>
    <title>A Deep Test of arXiv Import</title>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:primary_category term="cs.LG"/>
    <arxiv:doi>10.5555/published</arxiv:doi>
    <arxiv:journal_ref>J. Tests 1, 2 (2024)</arxiv:journal_ref>
  </entry>
</feed>
"""

PROVIDER_BIBTEX = """@article{provider-key,
  author = {Jane Smith and John Doe},
  title = {A Practical Test of DOI Import},
  journal = {Journal of Tests},
  year = {2024},
  doi = {10.5555/provider}
}
"""


def test_normalize_doi_accepts_urls() -> None:
    assert normalize_doi("https://doi.org/10.5555/ABC.DEF") == "10.5555/ABC.DEF"
    assert normalize_doi("DOI: 10.5555/abc") == "10.5555/abc"


def test_normalize_doi_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_doi("not-a-doi")


def test_entry_from_bibtex_returns_first_entry() -> None:
    entry = entry_from_bibtex(PROVIDER_BIBTEX)
    assert entry.type == "article"
    assert entry.fields["title"] == "A Practical Test of DOI Import"
    assert entry.modified is True
    assert entry.raw_content is None


def test_prepare_imported_entry_generates_unique_key() -> None:
    lib = parse_bib(
        """@article{Smith2024Practical,
  author = {Jane Smith},
  title = {A Different Practical Paper},
  year = {2024}
}
"""
    )

    entry = prepare_imported_entry(
        lib,
        "10.5555/provider",
        fetcher=lambda doi: PROVIDER_BIBTEX,
    )

    assert entry.key == "Smith2024Practicala"
    assert entry.fields["doi"] == "10.5555/provider"


def test_prepare_imported_entry_uses_jabref_key_pattern_metadata() -> None:
    lib = parse_bib(
        """@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}

@article{Existing,
  author = {Someone Else},
  title = {Existing},
  year = {2020}
}
"""
    )

    entry = prepare_imported_entry(
        lib,
        "10.5555/provider",
        fetcher=lambda doi: PROVIDER_BIBTEX,
    )

    assert entry.key == "Smith24Practical"


def test_prepare_imported_entry_can_use_provider_key() -> None:
    lib = parse_bib("")

    entry = prepare_imported_entry(
        lib,
        "10.5555/provider",
        key_source="provider",
        fetcher=lambda doi: PROVIDER_BIBTEX,
    )

    assert entry.key == "provider-key"


def test_prepare_imported_entry_explicit_key_wins() -> None:
    lib = parse_bib("")

    entry = prepare_imported_entry(
        lib,
        "10.5555/provider",
        key="Manual2024",
        key_source="provider",
        fetcher=lambda doi: PROVIDER_BIBTEX,
    )

    assert entry.key == "Manual2024"


def test_prepare_imported_entry_detects_duplicate_doi() -> None:
    lib = parse_bib(
        """@article{Existing,
  title = {Existing},
  doi = {https://doi.org/10.5555/provider}
}
"""
    )

    with pytest.raises(DuplicateDOIError) as exc:
        prepare_imported_entry(
            lib,
            "10.5555/provider",
            fetcher=lambda doi: PROVIDER_BIBTEX,
        )

    assert exc.value.keys == ["Existing"]


def test_prepare_imported_entry_explicit_key_conflict() -> None:
    lib = parse_bib("@article{Taken2020, title = {X}}\n")
    with pytest.raises(CitationKeyConflictError) as exc:
        prepare_imported_entry(
            lib,
            "10.5555/provider",
            key="Taken2020",
            fetcher=lambda doi: PROVIDER_BIBTEX,
        )
    assert exc.value.key == "Taken2020"


def test_prepare_imported_entry_rejects_invalid_key_source() -> None:
    lib = parse_bib("")
    with pytest.raises(ValueError, match="key source"):
        prepare_imported_entry(
            lib, "10.5555/provider", key_source="nonsense", fetcher=lambda doi: PROVIDER_BIBTEX
        )


def test_prepare_imported_entry_allows_duplicate_when_requested() -> None:
    lib = parse_bib("@article{Existing, title = {X}, doi = {10.5555/provider}}\n")
    entry = prepare_imported_entry(
        lib,
        "10.5555/provider",
        allow_duplicate_doi=True,
        fetcher=lambda doi: PROVIDER_BIBTEX,
    )
    assert entry.fields["doi"] == "10.5555/provider"


def test_entry_from_bibtex_rejects_empty_and_invalid() -> None:
    with pytest.raises(DOIImportError, match="no BibTeX entries"):
        entry_from_bibtex("% just a comment\n")
    with pytest.raises(DOIImportError, match="invalid BibTeX"):
        entry_from_bibtex("@article{broken, title = {unbalanced }\n")


def test_existing_keys_for_doi_skips_malformed_existing_doi() -> None:
    lib = parse_bib("@article{Good, doi = {10.5555/x}}\n@article{Bad, doi = {not-a-doi}}\n")
    assert existing_keys_for_doi(lib, "10.5555/x") == ["Good"]


def test_canonical_doi_is_lowercased() -> None:
    assert canonical_doi("https://doi.org/10.5555/ABC") == "10.5555/abc"


def test_render_entry_roundtrips() -> None:
    entry = entry_from_bibtex(PROVIDER_BIBTEX)
    rendered = render_entry(entry)
    assert rendered.startswith("@article{provider-key")
    assert not rendered.endswith("\n")
    assert "doi = {10.5555/provider}" in rendered


def test_fetch_bibtex_for_doi_wraps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise HTTPError("https://doi.org/x", 404, "Not Found", {}, None)

    monkeypatch.setattr("pynakes.importer.urlopen", _raise)
    with pytest.raises(DOIImportError, match="HTTP 404"):
        fetch_bibtex_for_doi("10.5555/missing")


def test_fetch_bibtex_for_doi_wraps_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr("pynakes.importer.urlopen", _raise)
    with pytest.raises(DOIImportError, match="Could not resolve"):
        fetch_bibtex_for_doi("10.5555/missing")


# --- identifier resolution -------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("10.5555/abc", (DOI, "10.5555/abc")),
        ("https://doi.org/10.5555/ABC", (DOI, "10.5555/ABC")),
        ("doi:10.5555/abc", (DOI, "10.5555/abc")),
        ("2301.00001", (ARXIV, "2301.00001")),
        ("2301.00001v3", (ARXIV, "2301.00001")),
        ("arXiv:2301.00001", (ARXIV, "2301.00001")),
        ("https://arxiv.org/abs/2301.00001v2", (ARXIV, "2301.00001")),
        ("https://arxiv.org/pdf/2301.00001.pdf", (ARXIV, "2301.00001")),
        ("hep-th/9901001", (ARXIV, "hep-th/9901001")),
    ],
)
def test_resolve_identifier(value: str, expected: tuple[str, str]) -> None:
    assert resolve_identifier(value) == expected


@pytest.mark.parametrize("value", ["", "not-an-identifier", "10.x/bad", "random text"])
def test_resolve_identifier_rejects_unknown(value: str) -> None:
    with pytest.raises(UnsupportedIdentifierError):
        resolve_identifier(value)


# --- journal URL extraction ------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_doi",
    [
        # nature.com: slug IS the DOI suffix under 10.1038
        (
            "https://www.nature.com/articles/s41535-025-00801-3",
            "10.1038/s41535-025-00801-3",
        ),
        (
            "https://nature.com/articles/s41586-024-07487-w",
            "10.1038/s41586-024-07487-w",
        ),
        # APS: DOI embedded literally in the abstract URL
        (
            "https://journals.aps.org/rmp/abstract/10.1103/k13g-z9s8",
            "10.1103/k13g-z9s8",
        ),
        # APS PDF variant
        (
            "https://journals.aps.org/rmp/pdf/10.1103/k13g-z9s8",
            "10.1103/k13g-z9s8",
        ),
        # APS Physical Review Letters
        (
            "https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.132.010601",
            "10.1103/PhysRevLett.132.010601",
        ),
    ],
)
def test_extract_doi_from_journal_url(url: str, expected_doi: str) -> None:
    assert extract_doi_from_journal_url(url) == expected_doi


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/articles/something",
        "https://arxiv.org/abs/2301.00001",
        "https://doi.org/10.5555/abc",
        "not a url at all",
    ],
)
def test_extract_doi_from_journal_url_returns_none_for_unknown(url: str) -> None:
    assert extract_doi_from_journal_url(url) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://www.nature.com/articles/s41535-025-00801-3",
            (DOI, "10.1038/s41535-025-00801-3"),
        ),
        (
            "https://journals.aps.org/rmp/abstract/10.1103/k13g-z9s8",
            (DOI, "10.1103/k13g-z9s8"),
        ),
        (
            "https://journals.aps.org/rmp/pdf/10.1103/k13g-z9s8",
            (DOI, "10.1103/k13g-z9s8"),
        ),
    ],
)
def test_resolve_identifier_accepts_journal_urls(url: str, expected: tuple[str, str]) -> None:
    assert resolve_identifier(url) == expected


def test_normalize_arxiv_strips_version_and_scheme() -> None:
    assert normalize_arxiv("arXiv:2301.00001v5") == "2301.00001"
    assert normalize_arxiv("https://arxiv.org/abs/2301.00001") == "2301.00001"
    assert normalize_arxiv("garbage that is not an id") == "garbage that is not an id"


# --- arXiv import ----------------------------------------------------------


def test_prepare_imported_arxiv_builds_misc_entry_for_bibtex() -> None:
    lib = parse_bib("")
    entry = prepare_imported_arxiv(
        lib, "2301.00001", dialect="bibtex", fetcher=lambda identifier: ARXIV_ATOM
    )
    assert entry.type == "misc"
    assert entry.fields["author"] == "Ada Lovelace and Alan Turing"
    assert entry.fields["title"] == "A Deep Test of arXiv Import"
    assert entry.fields["eprint"] == "2301.00001"
    assert entry.fields["archivePrefix"] == "arXiv"
    assert entry.fields["primaryClass"] == "cs.LG"
    assert entry.fields["year"] == "2023"
    assert entry.fields["url"] == "https://arxiv.org/abs/2301.00001"
    assert entry.fields["doi"] == "10.5555/published"
    assert entry.key == "Lovelace2023Deep"


def test_prepare_imported_arxiv_builds_online_entry_for_biblatex() -> None:
    lib = parse_bib("")
    entry = prepare_imported_arxiv(
        lib, "2301.00001", dialect="biblatex", fetcher=lambda identifier: ARXIV_ATOM
    )
    assert entry.type == "online"
    assert entry.fields["eprinttype"] == "arxiv"
    assert entry.fields["eprintclass"] == "cs.LG"
    assert entry.fields["date"] == "2023-01-02"
    assert "year" not in entry.fields


def test_prepare_imported_arxiv_detects_duplicate() -> None:
    lib = parse_bib(
        "@misc{Existing, eprint = {2301.00001}, archivePrefix = {arXiv}, title = {X}}\n"
    )
    with pytest.raises(DuplicateArxivError) as exc:
        prepare_imported_arxiv(lib, "2301.00001v2", fetcher=lambda identifier: ARXIV_ATOM)
    assert exc.value.keys == ["Existing"]


def test_prepare_imported_arxiv_allows_duplicate_when_requested() -> None:
    lib = parse_bib(
        "@misc{Existing, eprint = {2301.00001}, archivePrefix = {arXiv}, title = {X}}\n"
    )
    entry = prepare_imported_arxiv(
        lib, "2301.00001", allow_duplicate=True, fetcher=lambda identifier: ARXIV_ATOM
    )
    assert entry.fields["eprint"] == "2301.00001"


def test_existing_keys_for_arxiv_matches_eprint_and_url() -> None:
    lib = parse_bib(
        "@misc{A, eprint = {2301.00001v1}, eprinttype = {arxiv}}\n"
        "@article{B, url = {https://arxiv.org/abs/2301.00001}}\n"
        "@article{C, doi = {10.1/x}}\n"
    )
    assert existing_keys_for_arxiv(lib, "2301.00001") == ["A", "B"]


def test_fetch_arxiv_record_wraps_invalid_xml() -> None:
    with pytest.raises(ArxivImportError, match="invalid XML"):
        prepare_imported_arxiv(parse_bib(""), "2301.00001", fetcher=lambda identifier: "<not-xml")


def test_prepare_imported_reference_dispatches_by_type() -> None:
    lib = parse_bib("")
    kind, entry = prepare_imported_reference(
        lib, "10.5555/provider", doi_fetcher=lambda doi: PROVIDER_BIBTEX
    )
    assert kind == DOI
    assert entry.fields["doi"] == "10.5555/provider"

    kind, entry = prepare_imported_reference(
        lib, "arXiv:2301.00001", arxiv_fetcher=lambda identifier: ARXIV_ATOM
    )
    assert kind == ARXIV
    assert entry.type == "misc"
