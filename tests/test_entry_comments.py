"""Comments directly above an entry belong to it and travel with it."""

from pathlib import Path

from typer.testing import CliRunner

from pynakes._entry_comments import attached_comment_indices
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import CanonicalLayout, write_bib_canonical
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.normalize import sort_entries

runner = CliRunner()

# A suppression comment for the entry below it, the way a linter reads one.
LIBRARY = (
    "@article{Newton1687, title={Principia}, year={1687}}\n"
    "\n"
    "@comment{lint skip unknown-field: bookkeeping}\n"
    "@article{Euler1748, title={Introductio}, year={1748}, customfield={x}}\n"
    "\n"
    "@article{Darwin1859, title={Origin of Species}, year={1859}, customfield={y}}\n"
)
SKIP = "@comment{lint skip unknown-field: bookkeeping}"


def _attached(text: str) -> dict[str, list[str]]:
    lib = parse_bib(text)
    by_id = attached_comment_indices(lib)
    return {
        entry.key: [lib.raw_comments[index].strip() for index in by_id[id(entry)]]
        for entry in lib.entries.values()
        if id(entry) in by_id
    }


def _above(text: str, key: str) -> str:
    """Return the line directly above ``key``'s declaration in *text*."""
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if f"{{{key}," in line)
    return lines[index - 1] if index else ""


class TestAttachment:
    def test_a_comment_directly_above_an_entry_belongs_to_it(self) -> None:
        assert _attached(LIBRARY) == {"Euler1748": [SKIP]}

    def test_a_blank_line_leaves_a_comment_free(self) -> None:
        assert _attached("@comment{about the file}\n\n@misc{Hooke1665, title={M}}\n") == {}

    def test_a_run_of_comments_attaches_as_a_whole(self) -> None:
        text = "@comment{one}\n% two\n@misc{Hooke1665, title={M}}\n"
        assert _attached(text) == {"Hooke1665": ["@comment{one}", "% two"]}

    def test_a_blank_line_after_a_percent_comment_still_separates(self) -> None:
        # A ``%`` comment's text includes its newline; the blank line still counts.
        assert _attached("% header\n\n@misc{Hooke1665, title={M}}\n") == {}

    def test_metadata_blocks_never_attach(self) -> None:
        text = "@comment{jabref-meta: databaseType:bibtex;}\n@misc{Hooke1665, title={M}}\n"
        assert _attached(text) == {}


class TestRemoval:
    def test_ref_remove_takes_the_entrys_comments_with_it(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(LIBRARY, encoding="utf-8", newline="")

        result = runner.invoke(app, ["ref", "remove", str(bib), "Euler1748"])

        assert result.exit_code == 0, result.output
        assert bib.read_text(encoding="utf-8") == (
            "@article{Newton1687, title={Principia}, year={1687}}\n"
            "\n"
            "@article{Darwin1859, title={Origin of Species}, year={1859}, customfield={y}}\n"
        )

    def test_a_free_comment_survives_removing_the_entry_below_it(self) -> None:
        coll = Bibliography.from_text(
            "@comment{about the file}\n\n@misc{Hooke1665, title={M}}\n\n@misc{Boyle1660, title={N}}\n"
        )
        coll.remove_entry("Hooke1665")

        assert coll.preview() == "@comment{about the file}\n\n@misc{Boyle1660, title={N}}\n"

    def test_dedupe_merge_drops_the_merged_away_entrys_comments(self) -> None:
        coll = Bibliography.from_text(
            "@article{Boyle1660, title={New Experiments}, year={1660}, doi={10.5555/boyle}}\n"
            "\n"
            "@comment{note on the duplicate}\n"
            "@article{Boyle1660b, title={New Experiments}, year={1660}, doi={10.5555/BOYLE}}\n"
        )

        report = coll.dedupe_merge()

        assert report.removed_entry_count == 1
        assert "note on the duplicate" not in coll.preview()


class TestReordering:
    def test_format_by_key_keeps_the_comment_directly_above_its_entry(self) -> None:
        layout = CanonicalLayout(entry_order="key")
        text = write_bib_canonical(parse_bib(LIBRARY), layout)

        assert _above(text, "Euler1748") == SKIP
        assert text.index("Darwin1859") < text.index(SKIP) < text.index("Euler1748")
        assert write_bib_canonical(parse_bib(text), layout) == text

    def test_preserve_block_order_moves_an_attached_comment_with_its_entry(self) -> None:
        layout = CanonicalLayout(block_order="preserve", entry_order="key")
        text = write_bib_canonical(parse_bib(LIBRARY), layout)

        assert _above(text, "Euler1748") == SKIP
        assert text.index("Darwin1859") < text.index("Euler1748") < text.index("Newton1687")

    def test_sorting_keeps_the_comment_with_its_entry(self) -> None:
        lib = parse_bib(LIBRARY)
        sort_entries(lib, [("year", True)])
        text = write_bib(lib)

        assert _above(text, "Euler1748") == SKIP
        assert text.index("Darwin1859") < text.index("Euler1748")

    def test_a_percent_comment_gets_one_blank_line_not_two(self) -> None:
        lib = parse_bib(
            "% A library\n\n@comment{jabref-meta: databaseType:bibtex;}\n\n@misc{B, title={T}}\n"
        )
        text = write_bib_canonical(lib, CanonicalLayout(entry_order="key"))

        assert text.startswith("% A library\n\n@misc{B,")


class TestDerivedLibraries:
    def test_split_sends_the_comment_only_to_its_entrys_bucket(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(LIBRARY, encoding="utf-8", newline="")
        old, new = tmp_path / "old.bib", tmp_path / "new.bib"

        result = runner.invoke(
            app,
            ["corpus", "split", str(bib), "--to", f"{old}=year<1800", "--to", f"{new}=*"],
        )

        assert result.exit_code == 0, result.output
        assert _above(old.read_text(encoding="utf-8"), "Euler1748") == SKIP
        assert SKIP not in new.read_text(encoding="utf-8")

    def test_combine_carries_comments_from_every_input(self, tmp_path: Path) -> None:
        first = tmp_path / "first.bib"
        first.write_text("@misc{Hooke1665, title={M}}\n", encoding="utf-8")
        second = tmp_path / "second.bib"
        second.write_text(LIBRARY, encoding="utf-8", newline="")
        out = tmp_path / "all.bib"

        result = runner.invoke(
            app, ["corpus", "combine", str(first), str(second), "--out", str(out)]
        )

        assert result.exit_code == 0, result.output
        text = out.read_text(encoding="utf-8")
        assert _above(text, "Euler1748") == SKIP
        assert text.count(SKIP) == 1
