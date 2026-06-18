"""DOI import tests."""

from urllib.error import HTTPError, URLError

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.doi import (
    CitationKeyConflictError,
    DOIImportError,
    DuplicateDOIError,
    canonical_doi,
    entry_from_bibtex,
    existing_keys_for_doi,
    fetch_bibtex_for_doi,
    normalize_doi,
    prepare_imported_entry,
    render_entry,
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

    monkeypatch.setattr("pynakes.doi.urlopen", _raise)
    with pytest.raises(DOIImportError, match="HTTP 404"):
        fetch_bibtex_for_doi("10.5555/missing")


def test_fetch_bibtex_for_doi_wraps_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr("pynakes.doi.urlopen", _raise)
    with pytest.raises(DOIImportError, match="Could not resolve"):
        fetch_bibtex_for_doi("10.5555/missing")
