"""Offline entry point for the bundled engine, independent of ambient packages."""

import json
import os
import sys
from pathlib import Path


def select_variant(variants, supported_tags):
    """Select the best wheel for the interpreter, ABI and platform together."""
    from packaging.utils import parse_wheel_filename

    wheels = [(variant, parse_wheel_filename(variant["wheel"])[3]) for variant in variants]
    for tag in supported_tags:
        for variant, tags in wheels:
            if tag in tags:
                return variant["path"]
    return None


def main():
    if sys.version_info < (3, 12):
        sys.stderr.write("The bundled engine needs CPython 3.12–3.15.\n")
        return 1
    root = Path(__file__).resolve().parent
    # Discovery uses -I -S. Re-exec direct invocations too so neither PYTHONPATH,
    # site customizations nor ambient dependencies can mask a broken bundle.
    if not sys.flags.isolated or not sys.flags.no_site:
        os.execv(
            sys.executable,
            [sys.executable, "-I", "-S", str(root / Path(__file__).name), *sys.argv[1:]],
        )
    sys.path.insert(0, str(root))
    from packaging.tags import sys_tags

    variants = json.loads((root / "native.json").read_text())
    selected = select_variant(variants, sys_tags())
    if selected is None:
        sys.stderr.write(
            "No bundled native runtime matches this interpreter. Use standard CPython "
            "3.12–3.15 on Linux x64 (glibc), macOS x64/ARM64, or Windows x64; "
            "or configure an installed pynakes engine.\n"
        )
        return 1
    sys.path.insert(0, str(root / selected))
    from pynakes.cli import app

    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
