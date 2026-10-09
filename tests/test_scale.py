"""The linear-time paths that replaced quadratic ones: line numbering and key lookup.

Timings live in ``scripts/bench_scale.py``; these tests pin the behavior the
faster paths must keep.
"""

import pytest

from pynakes._text_utils import LineCounter
from pynakes.bibtex_parser import parse_bib
from pynakes.editing import rename_entry_key
from pynakes.model import BibEntry, EntryStore

TEXTS = [
    "",
    "one line",
    "a\nb\nc",
    "a\r\nb\r\nc\r\n",
    "a\rb\rc",
    "mixed\r\nendings\nand\rlone\r\r\n\n",
    "\r\n\r\n",
    "ellipsis\x85 and separators\fare not breaks\n",
]


def _reference(text: str, position: int) -> int:
    """The line at ``position``, counted naively from the start."""
    prefix = text[:position]
    return 1 + prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")


@pytest.mark.parametrize("text", TEXTS)
def test_counting_forward_matches_counting_from_the_start(text: str) -> None:
    counter = LineCounter(text)
    for position in range(len(text) + 1):
        assert counter.at(position) == _reference(text, position), position


@pytest.mark.parametrize("text", TEXTS)
def test_any_order_of_queries_gives_the_same_lines(text: str) -> None:
    counter = LineCounter(text)
    positions = list(range(len(text) + 1))
    for position in positions[::3] + positions[::-1] + positions[1::2]:
        assert counter.at(position) == _reference(text, position), position


def test_only_editor_line_breaks_count() -> None:
    lib = parse_bib("% note\x85 ellipsis \n@misc{A,\n  title = {T},\n}\n")
    assert lib.entries["A"].start_line == 2


def _entry(key: str) -> BibEntry:
    return BibEntry(key=key, type="misc", fields={})


def test_lookups_follow_a_key_renamed_in_place() -> None:
    store = EntryStore([_entry("Newton1687"), _entry("Euler1748")])
    assert "Newton1687" in store

    store["Newton1687"].key = "Newton1704"

    assert "Newton1687" not in store
    assert store["Newton1704"].key == "Newton1704"


def test_lookups_follow_a_rename_through_the_editing_helpers() -> None:
    lib = parse_bib("@misc{Newton1687,\n  title = {Principia},\n}\n")
    assert "Newton1687" in lib.entries

    rename_entry_key(lib.entries["Newton1687"], "Newton1713")

    assert lib.entries.get("Newton1687") is None
    assert lib.entries.get_all("Newton1713")[0].fields["title"] == "Principia"


def test_duplicate_keys_keep_store_order_through_adds_and_reorders() -> None:
    first, second, other = _entry("Gauss1801"), _entry("Gauss1801"), _entry("Abel1826")
    store = EntryStore([first])
    assert store.get_all("Gauss1801") == [first]

    store.add(other)
    store.add(second)
    assert store.get_all("Gauss1801") == [first, second]
    assert store["Gauss1801"] is first

    store.reorder(lambda entry: entry is first)
    assert store.get_all("Gauss1801") == [second, first]

    store.remove(second)
    assert store.get_all("Gauss1801") == [first]


def test_replacing_an_entry_by_key_updates_lookups() -> None:
    store = EntryStore([_entry("Riemann1854")])
    replacement = BibEntry(key="Riemann1854", type="article", fields={"year": "1854"})

    store["Riemann1854"] = replacement

    assert store["Riemann1854"] is replacement
    assert len(store) == 1
