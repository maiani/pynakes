#!/usr/bin/env python3
"""Time pynakes on a large synthetic library, to find and watch quadratic paths.

Developer-only: not part of the package, and not run by the test suite. Measures
parsing, writing, checks, bounded reads and analysis. Timings are observations,
not assertions. Each operation runs again under tracemalloc to measure peak
Python allocations separately; this is not total process RSS.

The library is generated deterministically from the entry index: invented
authors and titles, every common entry type, ``@string`` macros, braced and
quoted values, and comments between entries, so it exercises the same parser
paths a real library does without being derived from one.

Usage:
    python scripts/bench_scale.py                 # 1,000 / 5,000 / 20,000 entries
    python scripts/bench_scale.py 8000 --only parse
    python scripts/bench_scale.py 100 1000 --shape dense --only coauthors --out dense.json
"""

import argparse
import json
import platform
import sys
import tempfile
import time
import tracemalloc
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


def library(count: int, shape: str = "mixed") -> str:
    """Return a mixed library, unrelated names, or one dense surname block."""
    if shape != "mixed":
        rows = []
        for i in range(count):
            family = "Example" if shape == "dense" else f"Family{i}"
            # Many distinct names in one surname block exercise candidate comparisons.
            rows.append(
                f"@article{{Key{i:06d}, author={{{family}, Given{i} and Peer{i}, Ada}}, "
                f"title={{Invented work {i}}}, year={{1900}}, abstract={{{'context ' * 80}}}}}"
            )
        return "\n".join(rows)
    head = '@string{jphys = "Journal of Invented Physics"}\n\n'
    return head + "\n".join(entry(index) for index in range(count))


def timed(label: str, action: Callable[[], object]) -> dict[str, object]:
    start = time.perf_counter()
    action()
    elapsed = time.perf_counter() - start
    # A separate pass avoids charging allocation tracing to the timing.
    tracemalloc.start()
    action()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  {label:<16} {elapsed:8.2f} s  {peak / 1e6:8.2f} MB Python allocations", flush=True)
    return {"operation": label, "seconds": elapsed, "peak_python_bytes": peak}


def cli(*args: str, allowed: tuple[int, ...] = (0,)) -> Callable[[], object]:
    def run() -> None:
        result = CliRunner().invoke(app, list(args))
        if result.exit_code not in allowed:
            sys.exit(f"{' '.join(args)} failed:\n{result.output}")

    return run


def bench(count: int, only: set[str] | None, shape: str) -> list[dict[str, object]]:
    text = library(count, shape)
    records = []
    print(f"{count} entries, {len(text) / 1e6:.1f} MB", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        bib = Path(tmp) / "bench.bib"
        bib.write_text(text, encoding="utf-8")
        steps = {
            "parse": lambda: parse_bib(text),
            "write": lambda: write_bib(parse_bib(text)),
            "lint": cli("lint", str(bib), "--json", allowed=(0, 1)),
            "format --check": cli("format", str(bib), "--check", "--json", allowed=(0, 1)),
            "normalize": cli("normalize", str(bib), "--dry-run", "--json"),
        }
        steps.update(
            {
                "bounded": cli(
                    "ref",
                    "show",
                    str(bib),
                    "--where",
                    "year >= 1900",
                    "--select",
                    "title,abstract",
                    "--limit",
                    "20",
                    "--max-chars",
                    "100",
                    "--json",
                ),
                "analyze": cli(
                    "analyze", str(bib), "--section", "authors", "--section", "coauthors", "--json"
                ),
                "coauthors": cli("coauthors", str(bib), "--json"),
            }
        )
        if only and only - steps.keys():
            raise ValueError(f"Unknown operations: {sorted(only - steps.keys())}")
        for label, action in steps.items():
            if only is None or label in only:
                records.append({"entries": count, "shape": shape, **timed(label, action)})
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("counts", nargs="*", type=int, default=[1000, 5000, 20000])
    parser.add_argument("--only", action="append", help="Run only this step (repeatable)")
    parser.add_argument("--shape", choices=["mixed", "unrelated", "dense"], default="mixed")
    parser.add_argument("--out", type=Path, help="Write machine-readable measurements")
    args = parser.parse_args()
    if any(count <= 0 for count in args.counts):
        parser.error("counts must be positive")
    records = []
    for count in args.counts:
        records.extend(bench(count, set(args.only) if args.only else None, args.shape))
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "memory": "peak traced Python allocations in a separate warm pass, not total RSS",
                    "measurements": records,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
