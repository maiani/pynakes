"""Fail unless every runtime dependency is installed at its declared floor.

The lowest-dependency CI job resolves ``pyproject.toml``'s direct dependencies
to their lowest allowed versions. This proves it did: a later install step that
quietly upgraded one would otherwise leave the job testing something else.
"""

import re
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
FLOOR = re.compile(r"^\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*>=\s*([^,;\s]+)")


def main() -> int:
    dependencies = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    failures = 0
    for requirement in dependencies:
        match = FLOOR.match(requirement)
        if match is None:
            print(f"::error::no '>=' floor to check in {requirement!r}")
            failures += 1
            continue
        name, floor = match.groups()
        installed = version(name)
        status = "ok" if installed == floor else "MISMATCH"
        print(f"{name:12} floor {floor:10} installed {installed:10} {status}")
        if installed != floor:
            print(f"::error::{name} is {installed}, not its declared floor {floor}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
