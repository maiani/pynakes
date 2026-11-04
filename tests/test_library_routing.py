"""Routing policies and guarded, one-home additions across Library members."""

import json

import pytest
from typer.testing import CliRunner

from pynakes import BibEntry, Bibliography, ExternalModificationError, Library
from pynakes.cli import app
from pynakes.library import LibraryRoutingError

RULE = """
[routing]
fallback = "inbox.bib"
[[routing.rules]]
name = "Books"
where = "type in [book, mvbook, booklet]"
destination = "books.bib"
priority = 100
[[routing.rules]]
name = "Engines"
where = 'keywords contains "engines"'
destination = "engines.bib"
priority = 10
"""


@pytest.fixture
def manifest(tmp_path):
    for name in ("books", "engines", "inbox"):
        (tmp_path / f"{name}.bib").write_bytes(b"% Untouched header.\r\n")
    path = tmp_path / "test.library.toml"
    path.write_text(
        'pynakes-library = 1\nmembers = ["books.bib", "engines.bib", "inbox.bib"]\n' + RULE
    )
    return path


def entry(kind="book", key="Example1900", **fields):
    return BibEntry(
        key=key,
        type=kind,
        fields={"title": "Imaginary Engines", "author": "Example, Alice", "year": "1900", **fields},
    )


def test_transversal_book_rule_beats_subject_and_reports_all_matches(manifest, monkeypatch):
    monkeypatch.chdir(manifest.parent.parent)
    decision = Library.open(manifest).route(entry(keywords="engines"))
    assert decision.status == "routed"
    assert decision.destination == manifest.parent / "books.bib"
    assert [r.name for r in decision.matched_rules] == ["Books", "Engines"]
    assert decision.to_dict()["matched_rules"][0]["priority"] == 100


def test_subject_fallback_and_explicit_destination(manifest):
    lib = Library.open(manifest)
    assert lib.route(entry("article", keywords="engines")).destination.name == "engines.bib"
    assert lib.route(entry("article")).reason == "fallback"
    assert lib.route(entry("article")).destination.name == "inbox.bib"
    assert lib.route(entry(), destination="inbox.bib").reason == "explicit_destination"
    with pytest.raises(ValueError, match="not a Library member"):
        lib.route(entry(), destination="outside.bib")


def test_ties_are_not_resolved_by_order_or_fallback(manifest):
    manifest.write_text(manifest.read_text().replace("priority = 10\n", "priority = 100\n"))
    lib = Library.open(manifest)
    decision = lib.route(entry(keywords="engines"))
    assert decision.status == "ambiguous" and decision.destination is None
    with pytest.raises(LibraryRoutingError) as exc:
        lib.stage_entry(entry(keywords="engines"))
    assert exc.value.decision.reason == "equal_priority_destinations"
    assert lib.route(entry(keywords="engines"), destination="books.bib").status == "routed"
    # Multiple equally ranked rules selecting the same home agree.
    manifest.write_text(
        manifest.read_text().replace('destination = "engines.bib"', 'destination = "books.bib"')
    )
    assert Library.open(manifest).route(entry(keywords="engines")).status == "routed"


def test_no_fallback_and_unnamed_library_require_destination(manifest):
    manifest.write_text(manifest.read_text().replace('fallback = "inbox.bib"\n', ""))
    assert Library.open(manifest).route(entry("article")).status == "unmatched"
    lib = Library.from_files([manifest.parent / "books.bib"])
    assert lib.route(entry()).status == "unmatched"
    staged = lib.stage_entry(entry(), destination=manifest.parent / "books.bib")
    staged.bibliography.commit()
    assert len(Bibliography.open(manifest.parent / "books.bib").entries) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        ("[routing]", "[routing]\nunknown = true"),
        ("[routing]", 'routing = "bad"\n[other]'),
        ("priority = 100", "priority = true"),
        ('name = "Books"', 'name = ""'),
        ('name = "Engines"', 'name = "Books"'),
        ('where = "type in [book, mvbook, booklet]"', 'where = "type in ["'),
        ('where = "type in [book, mvbook, booklet]"', 'where = "used"'),
        ('destination = "books.bib"', 'destination = "missing.bib"'),
        ('destination = "books.bib"', 'destination = "/books.bib"'),
        ('destination = "books.bib"', 'destination = "books.pdf"'),
        ('destination = "books.bib"', 'destination = ""'),
        ("priority = 100", "unexpected = 100"),
        ("[routing]", '[routing]\nrules = "bad"'),
    ],
)
def test_invalid_policy_refused(manifest, replacement):
    manifest.write_text(manifest.read_text().replace(*replacement))
    with pytest.raises(ValueError):
        Library.open(manifest)


def test_excluded_destination_refused(manifest):
    manifest.write_text(
        manifest.read_text().replace("[routing]", 'exclude = ["books.bib"]\n[routing]')
    )
    with pytest.raises(ValueError, match="not a Library member"):
        Library.open(manifest)


def test_missing_member_blocks_add_even_with_explicit_destination(manifest):
    (manifest.parent / "engines.bib").unlink()
    lib = Library.open(manifest)
    assert lib.route(entry()).status == "incomplete"
    with pytest.raises(LibraryRoutingError):
        lib.stage_entry(entry(), destination="books.bib")


@pytest.mark.parametrize("kind", ["exact", "probable", "key", "version"])
def test_existing_work_across_members_precedes_routing(manifest, kind):
    coll = Bibliography.open(manifest.parent / "inbox.bib")
    data = entry(doi="10.5555/example")
    coll.add_entry(
        "article" if kind == "version" else "book",
        data.key,
        {**data.fields, **({"journal": "Examples"} if kind == "version" else {})},
    )
    coll.commit()
    candidate = entry(key="Different", doi="10.5555/example")
    if kind == "probable":
        candidate.fields.pop("doi")
    elif kind == "key":
        candidate = entry(key=data.key, title="Another Work", author="Other, Bob", year="1910")
    elif kind == "version":
        candidate = entry(
            "misc", key="Different", doi="10.5555/example", eprint="1900.00001", eprinttype="arxiv"
        )
    lib = Library.open(manifest)
    decision = lib.route(candidate, destination="books.bib")
    assert decision.status == ("existing" if kind == "exact" else "conflict")
    assert decision.candidates[0]["file"].endswith("inbox.bib")
    with pytest.raises(LibraryRoutingError):
        lib.stage_entry(candidate)


def test_stage_preview_commit_changes_only_destination_and_preserves_source(manifest):
    lib = Library.open(manifest)
    original = {p: p.read_bytes() for p in lib.members}
    candidate = entry()
    staged = lib.stage_entry(candidate)
    candidate.fields["title"] = "Changed by caller"
    assert all(p.read_bytes() == b for p, b in original.items())
    assert "Imaginary Engines" in staged.bibliography.diff()
    staged.bibliography.commit()
    assert (manifest.parent / "books.bib").read_bytes().startswith(b"% Untouched header.\r\n")
    for p in lib.members:
        if p.name != "books.bib":
            assert p.read_bytes() == original[p]
    # Held read view stays unchanged; reopening observes the addition.
    assert lib.lookup("Example1900").total == 0
    assert Library.open(manifest).lookup("Example1900").total == 1


@pytest.mark.parametrize("change", ["member", "manifest", "deleted", "new_member", "bad_manifest"])
def test_commit_guards_whole_library_even_with_force(manifest, change):
    if change == "new_member":
        manifest.write_text(
            manifest.read_text().replace('["books.bib", "engines.bib", "inbox.bib"]', '["*.bib"]')
        )
    lib = Library.open(manifest)
    staged = lib.stage_entry(entry())
    before = (manifest.parent / "books.bib").read_bytes()
    if change == "member":
        (manifest.parent / "inbox.bib").write_text("@book{New, title={Other}}")
    elif change == "deleted":
        (manifest.parent / "inbox.bib").unlink()
    elif change == "manifest":
        manifest.write_text(manifest.read_text().replace("priority = 100", "priority = 0"))
    elif change == "bad_manifest":
        manifest.write_text("broken = [")
    else:
        (manifest.parent / "new.bib").write_text("% new member")
    with pytest.raises(ExternalModificationError):
        staged.bibliography.commit(force=True)
    assert (manifest.parent / "books.bib").read_bytes() == before
    staged.bibliography.reset()
    staged.bibliography.commit()


def test_stale_library_cannot_stage(manifest):
    lib = Library.open(manifest)
    (manifest.parent / "inbox.bib").write_text("% changed")
    with pytest.raises(ExternalModificationError):
        lib.stage_entry(entry())


def test_cli_preview_apply_and_library_precondition(manifest):
    runner = CliRunner()
    args = [
        "library",
        "add",
        str(manifest),
        "Example1900",
        "--type",
        "book",
        "--field",
        "title=Imaginary Engines",
        "--field",
        "author=Example, Alice",
        "--field",
        "year=1900",
        "--json",
    ]
    result = runner.invoke(app, args + ["--dry-run", "--diff"])
    assert result.exit_code == 0, result.output
    preview = json.loads(result.output)
    assert preview["action"] == "library_add"
    assert preview["routing"]["destination"].endswith("books.bib")
    assert "Example1900" in preview["diff"]
    assert not Bibliography.open(manifest.parent / "books.bib").entries
    bad = runner.invoke(app, args + ["--expect-sha256", "0" * 64])
    assert bad.exit_code == 2 and json.loads(bad.output)["error"] == "ExternalModification"
    bad = runner.invoke(app, args + ["--expect-library-sha256", "0" * 64])
    assert bad.exit_code == 2
    applied = runner.invoke(
        app,
        args
        + [
            "--expect-sha256",
            preview["source_sha256"],
            "--expect-library-sha256",
            preview["library_sha256"],
        ],
    )
    assert applied.exit_code == 0, applied.output
    repeated = runner.invoke(app, args)
    assert repeated.exit_code == 2
    assert json.loads(repeated.output)["error"] == "LibraryRoutingConflict"


def test_cli_incomplete_and_invalid_input(manifest):
    runner = CliRunner()
    args = ["library", "add", str(manifest), "New", "--json"]
    result = runner.invoke(app, args + ["--destination", "other.bib"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    (manifest.parent / "books.bib").unlink()
    result = runner.invoke(app, args)
    assert result.exit_code == 1 and json.loads(result.output)["routing"]["status"] == "incomplete"
