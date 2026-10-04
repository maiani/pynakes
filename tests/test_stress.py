"""Stress tests: large libraries and many entries.

Files are normally small, but the parser/writer/operations must stay correct
and finish quickly on the large end. These are deterministic (no randomness).
"""

from pynakes import keys as keys_ops
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.lint import lint


def _build_library_text(n: int) -> str:
    blocks = []
    for i in range(n):
        blocks.append(
            f"@article{{Author{i}_{i % 7}_{2000 + i % 25},\n"
            f"  author = {{Author{i % 50}, Given}},\n"
            f"  title = {{A Study of Topic Number {i}}},\n"
            f"  journal = {{Journal of Things}},\n"
            f"  year = {{{2000 + i % 25}}}\n"
            f"}}"
        )
    return "\n\n".join(blocks) + "\n"


def test_parse_write_large_library() -> None:
    text = _build_library_text(2000)
    lib = parse_bib(text)
    assert len(lib.entries) == 2000

    # Unmodified round-trip preserves every entry block verbatim.
    output = write_bib(lib)
    for entry in lib.entries.values():
        assert entry.raw_content in output


def test_lint_large_library_is_clean() -> None:
    lib = parse_bib(_build_library_text(1500))
    issues = lint(lib)
    # Every generated entry is a complete article, so no required-field errors.
    assert [i for i in issues if i.severity == "error"] == []


def test_repair_keys_on_many_duplicates() -> None:
    # Force heavy key collision: many entries sharing few distinct keys.
    blocks = [
        f"@article{{Dup{i % 5},\n  title = {{T{i}}},\n  year = {{2020}}\n}}" for i in range(200)
    ]
    lib = parse_bib("\n\n".join(blocks) + "\n")
    assert lib.entries.duplicate_keys()

    renames = keys_ops.repair_duplicate_keys(lib)
    assert renames  # something was renamed
    # After repair, no duplicate keys remain.
    assert not lib.entries.duplicate_keys()
    assert len(set(e.key for e in lib.entries.values())) == len(lib.entries)
