"""Tests for unified-diff generation."""

from pynakes.diff import generate_diff


def test_diff_is_not_double_spaced() -> None:
    # Regression: a "\n".join over keepends=True lines doubled every newline,
    # rendering every diff double-spaced in the terminal.
    original = "line one\nline two\nline three\n"
    modified = "line one\nline 2\nline three\n"
    diff = generate_diff(original, modified, "refs.bib")
    assert "\n\n" not in diff
    assert "-line two" in diff
    assert "+line 2" in diff


def test_diff_has_unified_headers() -> None:
    diff = generate_diff("a\n", "b\n", "refs.bib")
    lines = diff.splitlines()
    assert lines[0] == "--- refs.bib (original)"
    assert lines[1] == "+++ refs.bib (modified)"
    assert lines[2].startswith("@@")


def test_identical_content_yields_empty_diff() -> None:
    assert generate_diff("same\n", "same\n", "refs.bib") == ""
