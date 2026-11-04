"""Library membership, partial reads and duplicate-safe discovery."""

import hashlib
import json
from pathlib import Path

import pytest

from pynakes import Library
from pynakes import library as library_module
from pynakes.search import search_entries


def _bib(path: Path, text: str = "@book{Newton, title={Principia}, year={1687}}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _manifest(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_named_library_resolves_relative_to_manifest_not_cwd(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    first = _bib(root / "z.bib")
    second = _bib(root / "a.bib")
    _bib(root / "draft.bib")
    manifest = _manifest(
        root / "physics.library.toml",
        'pynakes-library = 1\nname = "Physics"\n'
        'members = ["z.bib", "*.bib"]\nexclude = ["draft.bib"]\n'
        'catalogue = ".cache/catalogue.sqlite"\n',
    )
    monkeypatch.chdir(tmp_path)
    lib = Library.open(manifest)
    assert lib.name == "Physics"
    assert lib.manifest == manifest
    assert lib.members == lib.loaded_members == (first, second)
    assert lib.issues == ()
    assert lib.catalogue == root / ".cache/catalogue.sqlite"
    assert not lib.catalogue.exists()
    assert lib.lookup("Newton").total == 2


def test_recursive_patterns_and_exclusions_include_root_and_hidden(tmp_path):
    paths = [
        _bib(tmp_path / "root.bib"),
        _bib(tmp_path / ".hidden/b.bib"),
        _bib(tmp_path / "deep/nested/c.bib"),
    ]
    _bib(tmp_path / "draft.bib")
    _bib(tmp_path / "deep/draft.bib")
    spec = _manifest(
        tmp_path / "all.library.toml",
        'pynakes-library = 1\nmembers = ["**/*.bib"]\nexclude = ["**/draft.bib"]\n',
    )
    lib = Library.open(spec)
    assert lib.members == tuple(sorted(paths))
    assert lib.lookup("Newton").complete


@pytest.mark.parametrize(
    "content, message",
    [
        ('pynakes-library = 1\nmembers = []\nformat = "canonical"', "Unknown"),
        ("pynakes-library = 1\nmembers = []\n[settings]\nx = true", "Unknown"),
        ("members = []", "pynakes-library"),
        ("pynakes-library = 2\nmembers = []", "pynakes-library"),
        ("pynakes-library = true\nmembers = []", "pynakes-library"),
        ("pynakes-library = 1", "requires members"),
        ('pynakes-library = 1\nmembers = "*.bib"', "array"),
        ("pynakes-library = 1\nmembers = [1]", "array"),
        ('pynakes-library = 1\nmembers = [""]', "array"),
        ("pynakes-library = 1\nmembers = []\nexclude = true", "array"),
        ("pynakes-library = 1\nmembers = []\nname = 1", "non-empty"),
        ('pynakes-library = 1\nmembers = []\ncatalogue = " "', "non-empty"),
        ("pynakes-library = 1\nmembers = []\ncatalogue = []", "non-empty"),
        ("pynakes-library = [", "Invalid value"),
    ],
)
def test_invalid_manifests_fail_before_reading_members(tmp_path, content, message):
    with pytest.raises(ValueError, match=message):
        Library.open(_manifest(tmp_path / "bad.library.toml", content))


@pytest.mark.parametrize("key", ["members", "exclude", "catalogue"])
def test_manifest_paths_must_be_relative(tmp_path, key):
    value = json.dumps(str(tmp_path / "absolute.bib"))
    content = "pynakes-library = 1\n"
    if key != "members":
        content += "members = []\n"
    content += f"{key} = {value if key == 'catalogue' else '[' + value + ']'}\n"
    with pytest.raises(ValueError, match="relative"):
        Library.open(_manifest(tmp_path / "bad.library.toml", content))


def test_manifest_errors_are_not_partial_member_issues(tmp_path):
    with pytest.raises(ValueError, match="named"):
        Library.open(tmp_path / "wrong.toml")
    with pytest.raises(FileNotFoundError):
        Library.open(tmp_path / "missing.library.toml")


def test_explicit_files_keep_duplicates_in_files_but_read_each_path_once(tmp_path):
    first = _bib(tmp_path / "a.bib", "@book{Same, title={First}}\n@book{Same, title={Second}}\n")
    second = _bib(tmp_path / "b.bib", "@misc{Same, title={Third}}\n")
    lib = Library.from_files([first, second, first.parent / "./a.bib"])
    report = lib.lookup("Same")
    assert lib.name is lib.manifest is lib.catalogue is None
    assert report.total == 3
    assert [(hit.file, hit.entry_index) for hit in report.results] == [
        (first, 0),
        (first, 1),
        (second, 0),
    ]
    assert [hit.start_line for hit in report.results] == [1, 2, 1]
    assert report.results[0].source_sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    assert lib.lookup("same").total == 0
    serialized = json.loads(json.dumps(report.to_dict()))
    assert serialized["results"][1]["fields"] == {"title": "Second"}
    assert serialized["complete"] and not serialized["truncated"]
    # Return values cannot mutate the held member view.
    report.results[0].entry.fields["title"] = "Changed"
    assert lib.lookup("Same").results[0].entry.fields["title"] == "First"


def test_search_retains_the_index_of_the_matching_duplicate(tmp_path):
    path = _bib(tmp_path / "a.bib", "@book{Same, title={First}}\n@book{Same, title={Second}}\n")
    (hit,) = Library.from_files([path]).search("title:second").results
    assert hit.entry_index == 1 and hit.start_line == 2
    assert hit.entry.matches[0].field == "title"
    assert hit.entry.matches[0].kind == "exact"


def test_global_search_ranking_limits_and_generator_fields(tmp_path):
    first = _bib(tmp_path / "a.bib", "@book{A, abstract={Principia}}\n")
    second = _bib(
        tmp_path / "b.bib", "@book{B, title={Principia}}\n@book{Principia, title={Other}}\n"
    )
    lib = Library.from_files([first, second])
    report = lib.search("principia", limit=2)
    assert [hit.entry.key for hit in report.results] == ["Principia", "B"]
    assert report.total == 3 and report.truncated and report.complete
    report = lib.search("principia", search_in=(s for s in ["title"]))
    assert [hit.entry.key for hit in report.results] == ["Principia", "B"]
    assert lib.search("title:Principia OR key:A").total == 3  # key terms match substrings
    assert lib.search("principia", case_sensitive=True).total == 0
    assert lib.search("principia", limit=0).total == 3
    assert lib.search("principia", limit=0).results == ()
    assert lib.lookup("B", limit=0).total == 1
    assert lib.lookup("B", limit=0).truncated


def test_search_matches_single_file_semantics(tmp_path):
    path = _bib(tmp_path / "a.bib", "@book{Newton, title={Principia Mathematica}}\n")
    lib = Library.from_files([path])
    bib = library_module._load_source(path)[0]
    for query, kwargs in [
        ("principia", {}),
        ("principa", {"fuzzy": True}),
        ('"Principia Mathematica"', {}),
    ]:
        assert [hit.entry for hit in lib.search(query, **kwargs).results] == search_entries(
            bib, query, **kwargs
        )


@pytest.mark.parametrize("query", ["", "title:x OR", '"unfinished'])
def test_search_validates_even_empty_libraries(query):
    with pytest.raises(ValueError):
        Library.from_files([]).search(query)


def test_bad_limits_and_bare_file_argument(tmp_path):
    with pytest.raises(ValueError, match="iterable"):
        Library.from_files("wrong.bib")
    with pytest.raises(ValueError, match="iterable"):
        Library.from_files(tmp_path / "wrong.bib")
    for method in (Library.from_files([]).search, Library.from_files([]).lookup):
        with pytest.raises(ValueError, match="non-negative"):
            method("Newton", limit=-1)


def test_partial_reads_report_all_failures_and_preserve_valid_hits(tmp_path):
    good = _bib(tmp_path / "good.bib")
    missing = tmp_path / "missing.bib"
    malformed = _bib(tmp_path / "broken.bib", "@book{Broken, title={unclosed")
    directory = tmp_path / "directory.bib"
    directory.mkdir()
    nested = _manifest(tmp_path / "nested.library.toml", "pynakes-library = 1\nmembers = []")
    lib = Library.from_files([good, missing, malformed, directory, nested])
    report = lib.search("Principia")
    assert report.total == 1 and not report.complete
    assert report.loaded_members == (good,)
    assert {issue.source for issue in report.issues} == {
        str(p) for p in [missing, malformed, directory, nested]
    }
    assert {issue.code for issue in report.issues} >= {
        "unreadable",
        "parse_error",
        "invalid_member",
    }
    assert lib.lookup("Newton").issues == report.issues


def test_unmatched_and_unreadable_patterns_are_reported(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    original = Path.iterdir

    def iterdir(path):
        if path == blocked:
            raise PermissionError("blocked directory")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    spec = _manifest(
        tmp_path / "all.library.toml",
        'pynakes-library = 1\nmembers = ["none*.bib", "blocked/*.bib"]',
    )
    report = Library.open(spec).lookup("Newton")
    assert [issue.code for issue in report.issues] == ["unmatched_pattern", "unreadable"]
    assert not report.complete and report.total == 0


def test_member_read_permission_failure_is_not_silently_skipped(tmp_path, monkeypatch):
    path = _bib(tmp_path / "blocked.bib")

    def denied(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(library_module, "_load_source", denied)
    report = Library.from_files([path]).lookup("Newton")
    assert report.members == (path,) and report.loaded_members == ()
    assert report.issues[0].code == "unreadable"


def test_changes_during_a_member_read_exclude_that_member(tmp_path, monkeypatch):
    path = _bib(tmp_path / "changing.bib")
    original = library_module._load_source

    def load_then_edit(source):
        result = original(source)
        source.write_text("@book{Changed, title={A different work}}", encoding="utf-8")
        return result

    monkeypatch.setattr(library_module, "_load_source", load_then_edit)
    report = Library.from_files([path]).lookup("Newton")
    assert report.total == 0 and not report.complete
    assert report.issues[0].code == "changed"


@pytest.mark.parametrize("delete", [False, True])
def test_changes_while_reading_later_members_are_reported(tmp_path, monkeypatch, delete):
    first, second = _bib(tmp_path / "a.bib"), _bib(tmp_path / "b.bib")
    original = library_module._load_source

    def change_previous(source):
        result = original(source)
        if source == second:
            if delete:
                first.unlink()
            else:
                first.write_text("@book{Changed, title={A different work}}", encoding="utf-8")
        return result

    monkeypatch.setattr(library_module, "_load_source", change_previous)
    report = Library.from_files([first, second]).lookup("Newton")
    assert report.loaded_members == (second,)
    assert report.issues[0].code == "changed"


def test_held_view_changes_only_when_reopened_and_never_writes(tmp_path):
    path = _bib(tmp_path / "a.bib")
    original = path.read_bytes()
    lib = Library.from_files([path])
    lib.search("Principia")
    lib.lookup("Newton")
    assert path.read_bytes() == original
    path.write_text("@misc{New, title={New}}\n", encoding="utf-8")
    assert lib.lookup("Newton").total == 1
    assert Library.from_files([path]).lookup("Newton").total == 0


def test_explicit_paths_with_glob_metacharacters_are_literal(tmp_path):
    path = _bib(tmp_path / "refs[old].bib")
    _bib(tmp_path / "refso.bib")
    assert Library.from_files([path]).members == (path,)


def test_excluded_members_do_not_hide_unrelated_unmatched_patterns(tmp_path):
    _bib(tmp_path / "draft.bib")
    spec = _manifest(
        tmp_path / "all.library.toml",
        'pynakes-library = 1\nmembers = ["*.bib", "absent*.bib"]\nexclude = ["draft.bib"]',
    )
    lib = Library.open(spec)
    assert lib.members == ()
    assert [(issue.source, issue.code) for issue in lib.issues] == [
        ("absent*.bib", "unmatched_pattern")
    ]


def test_excluded_subtrees_are_not_read(tmp_path, monkeypatch):
    _bib(tmp_path / "private/draft.bib")
    good = _bib(tmp_path / "good.bib")
    original = Path.iterdir

    def iterdir(path):
        if path.name == "private":
            raise AssertionError("Excluded directory must not be scanned")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    spec = _manifest(
        tmp_path / "all.library.toml",
        'pynakes-library = 1\nmembers = ["**/*.bib"]\nexclude = ["private/**"]',
    )
    lib = Library.open(spec)
    assert lib.members == (good,)
    assert not lib.issues


def test_terminal_recursive_pattern_reports_non_bib_members_but_reads_bib_files(tmp_path):
    good = _bib(tmp_path / "nested/good.bib")
    spec = _manifest(tmp_path / "all.library.toml", 'pynakes-library = 1\nmembers = ["**"]')
    lib = Library.open(spec)
    assert lib.loaded_members == (good,)
    assert lib.issues and all(issue.code == "invalid_member" for issue in lib.issues)


def test_symlink_alias_is_read_once_and_recursive_loops_are_not_followed(tmp_path):
    path = _bib(tmp_path / "a.bib")
    alias = tmp_path / "alias.bib"
    loop = tmp_path / "loop"
    try:
        alias.symlink_to(path)
        loop.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks not available")
    spec = _manifest(tmp_path / "all.library.toml", 'pynakes-library = 1\nmembers = ["**/*.bib"]')
    lib = Library.open(spec)
    assert lib.members == (path,)
    assert lib.lookup("Newton").total == 1


def test_directory_symlinks_require_literal_declaration(tmp_path):
    root = tmp_path / "declared"
    root.mkdir()
    outside = _bib(tmp_path / "outside/refs.bib")
    try:
        (root / "linked").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks not available")
    spec = _manifest(root / "all.library.toml", 'pynakes-library = 1\nmembers = ["*/*.bib"]')
    assert Library.open(spec).members == ()
    spec.write_text('pynakes-library = 1\nmembers = ["linked/*.bib"]', encoding="utf-8")
    assert Library.open(spec).members == (outside,)


def test_member_encoding_uses_the_existing_reader(tmp_path):
    path = tmp_path / "old.bib"
    path.write_bytes("@book{Example, title={Café}}\n".encode("utf-16"))
    (hit,) = Library.from_files([path]).search("café").results
    assert hit.entry.fields["title"] == "Café"


@pytest.mark.parametrize("rank", [False, True])
def test_zero_limit_search_never_emits_a_result(rank):
    from pynakes import parse_bib

    bib = parse_bib("@book{Newton, title={Principia}}")
    assert search_entries(bib, "Principia", limit=0, rank=rank) == []
