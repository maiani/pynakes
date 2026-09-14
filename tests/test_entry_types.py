"""Tests for entry-type-dependent field naming."""

import pytest

from pynakes.entry_types import (
    container_field,
    eprint_fields,
    has_container,
    preprint_entry_type,
)


@pytest.mark.parametrize(
    "entry_type,expected",
    [
        ("article", "journal"),
        ("periodical", "journal"),
        ("suppperiodical", "journal"),
        ("inproceedings", "booktitle"),
        ("incollection", "booktitle"),
        ("inbook", "booktitle"),
        ("conference", "booktitle"),
        ("inreference", "booktitle"),
        # A monograph's own title *is* the container, so a provider's container
        # title has nowhere legitimate to go.
        ("book", None),
        ("proceedings", None),
        ("misc", None),
        ("phdthesis", None),
    ],
)
def test_container_field_by_entry_type(entry_type: str, expected: str | None) -> None:
    assert container_field(entry_type) == expected


def test_container_field_uses_biblatex_spelling() -> None:
    assert container_field("article", dialect="biblatex") == "journaltitle"
    assert container_field("incollection", dialect="biblatex") == "booktitle"


def test_container_field_ignores_case_and_surrounding_space() -> None:
    assert container_field("  InCollection ") == "booktitle"


def test_has_container_detects_any_spelling() -> None:
    assert has_container({"booktitle": "Games of No Chance"})
    assert has_container({"journaltitle": "Acta Eruditorum"})
    assert not has_container({"journal": "   "})
    assert not has_container({"title": "Only a title"})


def test_eprint_fields_match_the_casing_arxiv_publishes() -> None:
    names = eprint_fields("bibtex")
    assert (names.eprint, names.archive, names.eprint_class) == (
        "eprint",
        "archivePrefix",
        "primaryClass",
    )
    assert names.archive_value == "arXiv"


def test_eprint_fields_use_biblatex_names_and_lowercase_archive() -> None:
    names = eprint_fields("biblatex")
    assert (names.eprint, names.archive, names.eprint_class) == (
        "eprint",
        "eprinttype",
        "eprintclass",
    )
    assert names.archive_value == "arxiv"


def test_eprint_fields_carry_a_non_arxiv_archive_name() -> None:
    assert eprint_fields("bibtex", archive="biorxiv").archive_value == "biorxiv"


def test_preprint_entry_type_per_dialect() -> None:
    assert preprint_entry_type("bibtex") == "misc"
    assert preprint_entry_type("biblatex") == "online"
