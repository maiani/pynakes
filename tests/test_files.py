"""Tests for JabRef linked-file validation."""

from pathlib import Path

from pynakes.bibtex_parser import parse_bib
from pynakes.files import check_linked_files, metadata_file_directories, parse_linked_files


def test_parse_jabref_file_descriptors() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  title = {T},\n"
        "  file = {Paper:papers/A.pdf:PDF; Supplement:papers/A data.csv:CSV}\n"
        "}\n"
    )

    linked = parse_linked_files(lib)

    assert len(linked) == 2
    assert linked[0].entry_key == "A"
    assert linked[0].description == "Paper"
    assert linked[0].path == "papers/A.pdf"
    assert linked[0].kind == "PDF"
    assert linked[1].description == "Supplement"
    assert linked[1].path == "papers/A data.csv"


def test_parse_plain_path_and_directory_descriptor() -> None:
    lib = parse_bib(
        "@article{A,\n  title = {T},\n  file = {/tmp/A.pdf; :papers/data:directory}\n}\n"
    )

    linked = parse_linked_files(lib)

    assert linked[0].description is None
    assert linked[0].path == "/tmp/A.pdf"
    assert linked[0].kind is None
    assert linked[1].description is None
    assert linked[1].path == "papers/data"
    assert linked[1].kind == "directory"


def test_parse_escaped_delimiters() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  title = {T},\n"
        r"  file = {Name\: with colon:papers/A\;B.pdf:PDF}"
        "\n}\n"
    )

    linked = parse_linked_files(lib)

    assert len(linked) == 1
    assert linked[0].description == "Name: with colon"
    assert linked[0].path == "papers/A;B.pdf"


def test_plain_windows_path_is_not_treated_as_description() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  file = {C:\\\\papers\\\\A.pdf}\n}\n")

    linked = parse_linked_files(lib)

    assert linked[0].description is None
    assert linked[0].path == "C:\\\\papers\\\\A.pdf"


def test_check_resolves_relative_to_bib_dir(tmp_path: Path) -> None:
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "A.pdf").write_text("pdf")
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n"
        "  title = {T},\n"
        "  file = {A:papers/A.pdf:PDF; Missing:papers/Missing.pdf:PDF}\n"
        "}\n"
    )
    lib = parse_bib(bib.read_text())

    report = check_linked_files(lib, bib)

    assert report.checked == 2
    assert report.ok == 1
    assert report.missing == 1
    assert report.files[0].resolved_path == papers / "A.pdf"
    assert report.files[1].status == "missing"


def test_check_resolves_relative_to_explicit_root(tmp_path: Path) -> None:
    root = tmp_path / "attachments"
    root.mkdir()
    (root / "A.pdf").write_text("pdf")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T},\n  file = {A.pdf}\n}\n")
    lib = parse_bib(bib.read_text())

    report = check_linked_files(lib, bib, [root])

    assert report.ok == 1
    assert report.files[0].resolved_path == root / "A.pdf"


def test_check_resolves_relative_to_jabref_file_directory_metadata(tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    (attachments / "A.pdf").write_text("pdf")
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@comment{jabref-meta: fileDirectory:attachments;}\n\n"
        "@article{A,\n  title = {T},\n  file = {A.pdf}\n}\n"
    )
    lib = parse_bib(bib.read_text())

    roots = metadata_file_directories(lib, tmp_path)
    report = check_linked_files(lib, bib)

    assert roots == [attachments]
    assert report.ok == 1
    assert report.files[0].resolved_path == attachments / "A.pdf"


def test_check_reports_wrong_type_for_directory_link_to_file(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("file")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T},\n  file = {:not-a-directory:directory}\n}\n")
    lib = parse_bib(bib.read_text())

    report = check_linked_files(lib, bib)

    assert report.checked == 1
    assert report.wrong_type == 1
    assert report.issues[0].status == "wrong_type"


def test_empty_and_missing_file_fields_are_ignored(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T}\n}\n\n@article{B,\n  title = {T},\n  file = {}\n}\n")
    lib = parse_bib(bib.read_text())

    report = check_linked_files(lib, bib)

    assert report.checked == 0
    assert report.issues == []
