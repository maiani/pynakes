"""Project selections preserve provenance, source independence and local edits."""

from dataclasses import replace

import pytest

from pynakes import Bibliography, Library
from pynakes.editing import rename_entry_key, set_entry_field
from pynakes.engine import ExternalModificationError
from pynakes.library_backend import (
    BibTeXLibraryBackend,
    ItemRef,
    ReferenceView,
    Revision,
    SourceChanged,
    SourceMissing,
)
from pynakes.project_selection import SelectionConflict, prepare_selection


class Source:
    def __init__(self):
        self.record = ReferenceView(
            ItemRef("source", "record"),
            Revision("source", "1"),
            "book",
            "book",
            (("title", "Principia"), ("year", "1687")),
        )

    def get(self, ref, *, expected_revision=None, native=False):
        assert ref == self.record.ref
        if expected_revision is not None and expected_revision != self.record.revision:
            raise SourceChanged("Stale source")
        return self.record

    def update(self, **fields):
        self.record = replace(
            self.record,
            fields=tuple(fields.items()),
            revision=Revision("source", self.record.revision.token + "1"),
        )


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "project.bib"
    path.write_text('% Exact header\n\n@book{Other, title = "Unchanged"}\n', encoding="utf-8")
    return path, Source()


def select(path, source, key=None):
    bib = Bibliography.open(path)
    prepare_selection(source, source.record.ref, bib, key=key)
    bib.commit()
    return bib


def test_select_rename_repeat_and_merge(project):
    path, source = project
    original = path.read_bytes()
    bib = select(path, source, "Local")
    assert path.read_bytes().startswith(original)
    entry = bib.entries["Local"]
    rename_entry_key(entry, "Independent")
    set_entry_field(entry, "note", "Project note")
    bib.commit()
    before = path.read_bytes()
    select(path, source)
    assert path.read_bytes() == before
    source.update(title="Corrected Principia", year="1687")
    bib = select(path, source)
    assert bib.entries["Independent"].fields == {
        "title": "Corrected Principia",
        "year": "1687",
        "note": "Project note",
    }
    assert len(bib.entry_comments("Independent")) == 1
    assert path.read_bytes().startswith(original)


def test_local_only_edits_do_not_advance_baseline(project):
    path, source = project
    bib = select(path, source, "Local")
    set_entry_field(bib.entries["Local"], "title", "Locally edited")
    bib.commit()
    select(path, source)  # Must not make the local edit an accepted source baseline.
    before = path.read_bytes()
    source.update(title="Upstream edit", year="1687")
    with pytest.raises(SelectionConflict, match="title"):
        select(path, source)
    assert path.read_bytes() == before


def test_source_deletions_and_same_edit(project):
    path, source = project
    bib = select(path, source, "Local")
    set_entry_field(bib.entries["Local"], "title", "Same edit")
    bib.commit()
    source.update(title="Same edit")
    bib = select(path, source)
    assert bib.entries["Local"].fields == {"title": "Same edit"}
    source.record = replace(source.record, entry_type="misc")
    assert select(path, source).entries["Local"].type == "misc"


def test_source_and_project_changes_block_commit(project):
    path, source = project
    bib = Bibliography.open(path)
    prepare_selection(source, source.record.ref, bib, key="Local")
    before = path.read_bytes()
    source.update(title="New", year="1687")
    with pytest.raises(SourceChanged):
        bib.commit()
    assert path.read_bytes() == before
    bib = Bibliography.open(path)
    prepare_selection(source, source.record.ref, bib, key="Local")
    path.write_bytes(before + b"% Another edit\n")
    with pytest.raises(ExternalModificationError):
        bib.commit()
    assert path.read_bytes() == before + b"% Another edit\n"


def test_existing_records_and_bad_bindings_require_review(project):
    path, source = project
    with pytest.raises(SelectionConflict):
        select(path, source, "Other")
    select(path, source, "Local")
    with pytest.raises(SelectionConflict):
        select(path, source, "Different")
    content = path.read_text(encoding="utf-8")
    content = content.replace("pynakes-source-v1: ", "pynakes-source-v1: invalid:")
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SelectionConflict, match="Invalid source binding"):
        select(path, source)


def test_staged_or_unbound_file_target_refused(project):
    path, source = project
    bib = Bibliography.open(path)
    bib.add_entry("book", "Added", {"title": "Added"})
    with pytest.raises(SelectionConflict, match="pristine"):
        prepare_selection(source, source.record.ref, bib)
    with pytest.raises(SelectionConflict, match="Bibliography.open"):
        prepare_selection(source, source.record.ref, Bibliography.from_text("", path))


def test_file_backend_duplicates_privacy_and_stale_occurrences(tmp_path):
    path = tmp_path / "source.bib"
    text = "@book{Same,title={Principia},year={1687},note={Private}}\n@book{Same,title={Opticks}}\n"
    path.write_text(text, encoding="utf-8")
    b = BibTeXLibraryBackend(Library.from_files([path]))
    first = b.scan(limit=1)
    second = b.scan(limit=1, cursor=first.next_cursor)
    assert first.items[0].citation_key == second.items[0].citation_key
    assert first.items[0].ref != second.items[0].ref
    assert "note" not in dict(first.items[0].fields)
    assert first.items[0].issues
    assert b.get(first.items[0].ref, native=True).native_json
    assert b.describe()["backend"] == "bibtex"
    with pytest.raises(SourceMissing):
        b.get(ItemRef(b.source, "missing"))
    with pytest.raises(SourceChanged):
        b.get(ItemRef("other", first.items[0].ref.key))
    project = tmp_path / "project.bib"
    project.write_text("", encoding="utf-8")
    bib = Bibliography.open(project)
    prepare_selection(b, first.items[0].ref, bib, key="Selected")
    bib.commit()
    assert path.read_text(encoding="utf-8") == text
    path.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(SourceChanged):
        b.scan()
    reopened = BibTeXLibraryBackend(Library.from_files([path]))
    with pytest.raises(SourceMissing):
        reopened.get(first.items[0].ref)


def test_partial_native_library_reports_coverage(tmp_path):
    missing = tmp_path / "missing.bib"
    b = BibTeXLibraryBackend(Library.from_files([missing]))
    assert not b.scan().complete
    assert b.scan().issues


def test_project_type_conflict_and_invalid_source_are_atomic(project):
    from pynakes.editing import set_entry_type

    path, source = project
    bib = select(path, source, "Local")
    set_entry_type(bib.entries["Local"], "misc")
    bib.commit()
    before = path.read_bytes()
    source.record = replace(source.record, entry_type="article")
    with pytest.raises(SelectionConflict, match="type"):
        select(path, source)
    assert path.read_bytes() == before
    source.record = replace(source.record, entry_type="book")
    source.update(title="Corrected", year="{1687")
    bib = Bibliography.open(path)
    with pytest.raises(ValueError):
        prepare_selection(source, source.record.ref, bib)
    assert not bib.is_modified


def test_project_dialect_and_unsupported_projection(project):
    from pynakes.library_backend import SourceUnsupported

    path, source = project
    path.write_text("@comment{jabref-meta: databaseType:biblatex;}\n", encoding="utf-8")
    source.record = replace(
        source.record,
        entry_type="article",
        fields=(("title", "Example"), ("journal", "Example Journal"), ("year", "1900")),
    )
    bib = select(path, source, "Local")
    assert bib.entries["Local"].fields["journaltitle"] == "Example Journal"
    assert bib.entries["Local"].fields["date"] == "1900"
    source.record = replace(source.record, entry_type=None)
    with pytest.raises(SourceUnsupported):
        select(path, source)
    source.record = replace(source.record, entry_type="book", fields=())
    with pytest.raises(SourceUnsupported, match="title"):
        select(path, source)
