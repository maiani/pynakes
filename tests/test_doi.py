"""DOI import tests."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.doi import (
    DuplicateDOIError,
    entry_from_bibtex,
    normalize_doi,
    prepare_imported_entry,
)

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
