#!/usr/bin/env python3
"""Time pynakes on a large synthetic library, to find and watch quadratic paths.

Developer-only: not part of the package, and not run by the test suite. The benchmark
measures parsing, ``lint``, and ``format --check`` on a 20,000-entry library,
with timings recorded rather than asserted, since
wall-clock time depends on the machine.

The library is generated deterministically from the entry index: invented
authors and titles, every common entry type, ``@string`` macros, braced and
quoted values, and comments between entries, so it exercises the same parser
paths a real library does without being derived from one.

Usage:
    python scripts/bench_scale.py                 # 1,000 / 5,000 / 20,000 entries
    python scripts/bench_scale.py 8000 --only parse
"""

import argparse
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app

SURNAMES = ["Ashby", "Brandt", "Castell", "Dorn", "Elling", "Farrow", "Gisler", "Hale"]
GIVEN = ["Ada", "Bruno", "Clara", "Dmitri", "Elena", "Felix", "Greta", "Hugo"]
TYPES = ["article", "inproceedings", "book", "misc", "phdthesis", "techreport"]
WORDS = ["Notes", "on", "the", "Theory", "of", "Lattice", "Waves", "in", "Ordered", "Media"]


def entry(index: int) -> str:
    """Return the text of entry ``index``; the same index always gives the same text."""
    kind = TYPES[index % len(TYPES)]
    authors = " and ".join(
        f"{SURNAMES[(index + n) % len(SURNAMES)]}, {GIVEN[(index * 3 + n) % len(GIVEN)]}"
        for n in range(1 + index % 4)
    )
    title = " ".join(WORDS[(index + n) % len(WORDS)] for n in range(4 + index % 6))
    lines = [
        f"@{kind}{{Key{index:06d},",
        f"  author = {{{authors}}},",
        f"  title = {{{{{title}}} for {{DNA}} Models}},",
        f"  year = {1900 + index % 125},",
    ]
    if kind == "article":
        lines.append("  journal = jphys,")
        lines.append(f'  pages = "{index % 900 + 1}--{index % 900 + 9}",')
    if index % 5 == 0:
        lines.append(f"  doi = {{10.5555/bench.{index}}},")
    if index % 7 == 0:
        lines.append(f"  abstract = {{{' '.join(WORDS * 12)}}},")
    lines.append("}")
    text = "\n".join(lines) + "\n"
    if index % 50 == 0:
        text = f"% Section {index // 50}\n" + text
    return text


def library(count: int) -> str:
    """Return a library of ``count`` entries with its ``@string`` preamble."""
    head = '@string{jphys = "Journal of Invented Physics"}\n\n'
    return head + "\n".join(entry(index) for index in range(count))


def timed(label: str, action: Callable[[], object]) -> None:
    start = time.perf_counter()
    action()
    print(f"  {label:<16} {time.perf_counter() - start:8.2f} s", flush=True)


def cli(*args: str) -> Callable[[], object]:
    def run() -> None:
        result = CliRunner().invoke(app, list(args))
        if result.exit_code not in (0, 1):
            sys.exit(f"{' '.join(args)} failed:\n{result.output}")

    return run


def bench(count: int, only: set[str] | None) -> None:
    text = library(count)
    print(f"{count} entries, {len(text) / 1e6:.1f} MB", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        bib = Path(tmp) / "bench.bib"
        bib.write_text(text, encoding="utf-8")
        steps = {
            "parse": lambda: parse_bib(text),
            "write": lambda: write_bib(parse_bib(text)),
            "lint": cli("lint", str(bib), "--json"),
            "format --check": cli("format", str(bib), "--check", "--json"),
            "normalize": cli("normalize", str(bib), "--dry-run", "--json"),
        }
        for label, action in steps.items():
            if only is None or label in only:
                timed(label, action)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("counts", nargs="*", type=int, default=[1000, 5000, 20000])
    parser.add_argument("--only", action="append", help="Run only this step (repeatable)")
    args = parser.parse_args()
    for count in args.counts:
        bench(count, set(args.only) if args.only else None)


if __name__ == "__main__":
    main()
