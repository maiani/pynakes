"""Tests for JabRef group management."""

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.groups import (
    add_to_group,
    list_entries_in_group,
    list_groups,
    remove_from_group,
)

_GROUPED = (
    "@article{A,\n  title = {One},\n  groups = {Machine Learning; AI}\n}\n\n"
    "@article{B,\n  title = {Two},\n  groups = {AI}\n}\n\n"
    "@article{C,\n  title = {Three}\n}\n"
)


def test_list_groups_distinct_first_seen_order() -> None:
    lib = parse_bib(_GROUPED)
    assert list_groups(lib) == ["Machine Learning", "AI"]


def test_list_entries_in_group() -> None:
    lib = parse_bib(_GROUPED)
    assert list_entries_in_group(lib, "AI") == ["A", "B"]
    assert list_entries_in_group(lib, "Machine Learning") == ["A"]


def test_add_to_group_creates_field() -> None:
    lib = parse_bib(_GROUPED)
    count = add_to_group(lib, "C", "AI")
    assert count == 1
    assert lib.entries["C"].fields["groups"] == "AI"
    assert "C" in list_entries_in_group(lib, "AI")


def test_add_to_group_appends_semicolon_delimited() -> None:
    lib = parse_bib(_GROUPED)
    add_to_group(lib, "B", "Robotics")
    assert lib.entries["B"].fields["groups"] == "AI; Robotics"


def test_add_to_group_is_idempotent() -> None:
    lib = parse_bib(_GROUPED)
    assert add_to_group(lib, "A", "AI") == 0


def test_add_to_group_unknown_key_changes_nothing() -> None:
    lib = parse_bib(_GROUPED)
    assert add_to_group(lib, "ZZZ", "AI") == 0


def test_remove_from_group() -> None:
    lib = parse_bib(_GROUPED)
    count = remove_from_group(lib, "A", "AI")
    assert count == 1
    assert lib.entries["A"].fields["groups"] == "Machine Learning"


def test_remove_last_group_drops_field() -> None:
    lib = parse_bib(_GROUPED)
    remove_from_group(lib, "B", "AI")
    assert "groups" not in lib.entries["B"].fields
    # And it round-trips without a stray empty groups line.
    assert "groups" not in write_bib(lib).split("@article{B,")[1].split("}")[0]


def test_round_trip_preserves_other_fields() -> None:
    original = "@article{A,\n  title = {The {DNA} Helix},\n  year = {2020}\n}\n"
    lib = parse_bib(original)
    add_to_group(lib, "A", "Bio")
    out = write_bib(lib)
    assert "The {DNA} Helix" in out
    assert "groups = {Bio}" in out


def test_add_to_all_duplicates_of_a_key() -> None:
    lib = parse_bib(
        "@article{Dup,\n  year = {2020}\n}\n\n@article{Dup,\n  year = {2021}\n}\n"
    )
    count = add_to_group(lib, "Dup", "X")
    assert count == 2
    assert all(e.fields.get("groups") == "X" for e in lib.entries.get_all("Dup"))
