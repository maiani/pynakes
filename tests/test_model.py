"""Tests for the data model."""

import json
from dataclasses import asdict

from pynakes.model import BibEntry, BibFile, EntryStore


class TestBibEntry:
    """Tests for BibEntry dataclass."""

    def test_minimal_entry(self) -> None:
        """Test creating an entry with minimal fields."""
        entry = BibEntry(key="Smith2020", type="article", fields={})
        assert entry.key == "Smith2020"
        assert entry.type == "article"
        assert entry.fields == {}
        assert entry.raw_content is None
        assert entry.raw_comments == []
        assert entry.jabref_metadata == {}
        assert entry.modified is False

    def test_entry_with_fields(self) -> None:
        """Test creating an entry with fields."""
        fields = {
            "author": "John Smith",
            "title": "A Great Paper",
            "journal": "Nature",
            "year": "2020",
        }
        entry = BibEntry(key="Smith2020", type="article", fields=fields)
        assert entry.fields == fields
        assert entry.fields["author"] == "John Smith"
        assert entry.fields["title"] == "A Great Paper"

    def test_entry_with_optional_fields(self) -> None:
        """Test creating an entry with optional fields."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"author": "John Smith"},
            raw_content="@article{Smith2020, author={John Smith}}",
            raw_comments=["% This is a comment"],
            jabref_metadata={"keywords": "AI, ML"},
            modified=True,
        )
        assert entry.raw_content == "@article{Smith2020, author={John Smith}}"
        assert entry.raw_comments == ["% This is a comment"]
        assert entry.jabref_metadata == {"keywords": "AI, ML"}
        assert entry.modified is True

    def test_entry_modification(self) -> None:
        """Test modifying entry fields."""
        entry = BibEntry(key="Smith2020", type="article", fields={})
        entry.fields["author"] = "John Smith"
        entry.modified = True
        assert entry.fields["author"] == "John Smith"
        assert entry.modified is True

    def test_entry_repr(self) -> None:
        """Test __repr__ for debugging."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"author": "John Smith", "title": "Paper Title", "journal": "Nature"},
        )
        repr_str = repr(entry)
        assert "Smith2020" in repr_str
        assert "article" in repr_str
        assert "modified=False" in repr_str

    def test_entry_repr_long_values(self) -> None:
        """Test __repr__ truncates long field values."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"abstract": "A" * 100},
        )
        repr_str = repr(entry)
        assert "..." in repr_str

    def test_entry_to_dict(self) -> None:
        """Test converting entry to dictionary."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"author": "John Smith"},
        )
        entry_dict = asdict(entry)
        assert entry_dict["key"] == "Smith2020"
        assert entry_dict["type"] == "article"
        assert entry_dict["fields"] == {"author": "John Smith"}
        assert entry_dict["modified"] is False

    def test_entry_to_json(self) -> None:
        """Test round-trip entry to JSON."""
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"author": "John Smith", "title": "A Paper"},
        )
        entry_dict = asdict(entry)
        json_str = json.dumps(entry_dict)
        loaded = json.loads(json_str)
        assert loaded["key"] == "Smith2020"
        assert loaded["type"] == "article"
        assert loaded["fields"]["author"] == "John Smith"


class TestBibLibrary:
    """Tests for BibFile dataclass."""

    def test_empty_library(self) -> None:
        """Test creating an empty library."""
        lib = BibFile(entries={})
        assert len(lib.entries) == 0
        assert lib.strings == {}
        assert lib.preamble == []
        assert lib.raw_comments == []
        assert lib.encoding == "utf-8"
        assert lib.line_ending == "\n"

    def test_library_with_entries(self) -> None:
        """Test creating a library with entries."""
        entry1 = BibEntry(key="Smith2020", type="article", fields={})
        entry2 = BibEntry(key="Jones2021", type="book", fields={})
        lib = BibFile(entries={"Smith2020": entry1, "Jones2021": entry2})
        assert len(lib.entries) == 2
        assert lib.entries["Smith2020"].key == "Smith2020"
        assert lib.entries["Jones2021"].key == "Jones2021"

    def test_library_with_strings(self) -> None:
        """Test library with string definitions."""
        lib = BibFile(
            entries={},
            strings={"IEEE": "IEEE Transactions", "ACM": "ACM Computing Surveys"},
        )
        assert lib.strings["IEEE"] == "IEEE Transactions"
        assert lib.strings["ACM"] == "ACM Computing Surveys"

    def test_library_with_preamble(self) -> None:
        """Test library with preamble."""
        lib = BibFile(
            entries={},
            preamble=["@preamble{Acknowledgments}"],
        )
        assert lib.preamble == ["@preamble{Acknowledgments}"]

    def test_library_with_comments(self) -> None:
        """Test library with comments."""
        lib = BibFile(
            entries={},
            raw_comments=["% BibTeX file", "% Created by pynakes"],
        )
        assert len(lib.raw_comments) == 2

    def test_library_encoding_variants(self) -> None:
        """Test library with different encodings."""
        lib_utf8 = BibFile(entries={}, encoding="utf-8")
        lib_latin1 = BibFile(entries={}, encoding="latin-1")
        assert lib_utf8.encoding == "utf-8"
        assert lib_latin1.encoding == "latin-1"

    def test_library_line_ending_variants(self) -> None:
        """Test library with different line endings."""
        lib_unix = BibFile(entries={}, line_ending="\n")
        lib_windows = BibFile(entries={}, line_ending="\r\n")
        assert lib_unix.line_ending == "\n"
        lib_windows.line_ending == "\r\n"

    def test_library_modification(self) -> None:
        """Test modifying library contents."""
        lib = BibFile(entries={})
        entry = BibEntry(key="Smith2020", type="article", fields={})
        lib.entries["Smith2020"] = entry
        assert len(lib.entries) == 1
        assert lib.entries["Smith2020"].key == "Smith2020"

    def test_library_repr(self) -> None:
        """Test __repr__ for debugging."""
        entry = BibEntry(key="Smith2020", type="article", fields={})
        lib = BibFile(entries={"Smith2020": entry})
        repr_str = repr(lib)
        assert "entries=1" in repr_str
        assert "encoding='utf-8'" in repr_str

    def test_library_to_dict(self) -> None:
        """Test converting library to dictionary."""
        entry = BibEntry(key="Smith2020", type="article", fields={"author": "John"})
        lib = BibFile(
            entries={"Smith2020": entry},
            strings={"IEEE": "IEEE Transactions"},
            encoding="utf-8",
        )
        lib_dict = lib.to_dict()
        assert len(lib_dict["entries"]) == 1
        assert lib_dict["strings"]["IEEE"] == "IEEE Transactions"
        assert lib_dict["encoding"] == "utf-8"

    def test_library_to_json(self) -> None:
        """Test round-trip library to JSON."""
        entry = BibEntry(key="Smith2020", type="article", fields={"author": "John"})
        lib = BibFile(
            entries={"Smith2020": entry},
            strings={"IEEE": "IEEE Transactions"},
        )
        lib_dict = lib.to_dict()
        json_str = json.dumps(lib_dict)
        loaded = json.loads(json_str)
        assert len(loaded["entries"]) == 1
        assert loaded["entries"]["Smith2020"]["key"] == "Smith2020"
        assert loaded["strings"]["IEEE"] == "IEEE Transactions"

    def test_library_complex_scenario(self) -> None:
        """Test a library with multiple entries, strings, and metadata."""
        entries = {
            "Smith2020": BibEntry(
                key="Smith2020",
                type="article",
                fields={"author": "John Smith", "title": "Paper 1"},
            ),
            "Jones2021": BibEntry(
                key="Jones2021",
                type="book",
                fields={"author": "Jane Jones", "title": "Book 1"},
            ),
        }
        lib = BibFile(
            entries=entries,
            strings={"IEEE": "IEEE Transactions"},
            preamble=["@preamble{Acknowledgments}"],
            raw_comments=["% Created by pynakes"],
            encoding="utf-8",
            line_ending="\n",
        )
        assert len(lib.entries) == 2
        assert len(lib.strings) == 1
        assert len(lib.preamble) == 1
        assert len(lib.raw_comments) == 1
        assert lib.encoding == "utf-8"


class TestEntryCollection:
    """Tests for the duplicate-tolerant entry container."""

    def _entry(self, key: str, author: str) -> BibEntry:
        return BibEntry(key=key, type="article", fields={"author": author})

    def test_dict_like_access_first_match(self) -> None:
        coll = EntryStore()
        coll.add(self._entry("k", "first"))
        coll.add(self._entry("k", "second"))

        assert "k" in coll
        assert coll["k"].fields["author"] == "first"  # first match wins
        assert coll.get("missing") is None

    def test_preserves_duplicates(self) -> None:
        coll = EntryStore()
        coll.add(self._entry("k", "first"))
        coll.add(self._entry("k", "second"))

        assert len(coll) == 2
        assert [e.fields["author"] for e in coll.get_all("k")] == ["first", "second"]
        assert coll.duplicate_keys() == {"k": 2}

    def test_no_duplicates_reports_empty(self) -> None:
        coll = EntryStore([self._entry("a", "x"), self._entry("b", "y")])
        assert coll.duplicate_keys() == {}
        assert coll.keys() == ["a", "b"]

    def test_setitem_replaces_first(self) -> None:
        coll = EntryStore([self._entry("k", "old")])
        coll["k"] = self._entry("k", "new")
        assert coll["k"].fields["author"] == "new"
        assert len(coll) == 1

    def test_construct_from_dict(self) -> None:
        coll = EntryStore({"k": self._entry("k", "x")})
        assert coll["k"].fields["author"] == "x"
