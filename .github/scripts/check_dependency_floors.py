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


def same_release(installed: str, floor: str) -> bool:
    """Treat ``1.26.0`` as the floor ``1.26``; other forms must match exactly."""
    try:
        a, b = ([int(part) for part in v.split(".")] for v in (installed, floor))
    except ValueError:
        return installed == floor
    width = max(len(a), len(b))
    return a + [0] * (width - len(a)) == b + [0] * (width - len(b))


def main() -> int:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    # The job also installs the pdf extra, whose floor is a promise too.
    dependencies = [*project["dependencies"], *project["optional-dependencies"]["pdf"]]
    failures = 0
    for requirement in dependencies:
        match = FLOOR.match(requirement)
        if match is None:
            print(f"::error::no '>=' floor to check in {requirement!r}")
            failures += 1
            continue
        name, floor = match.groups()
        installed = version(name)
        matches = same_release(installed, floor)
        status = "ok" if matches else "MISMATCH"
        print(f"{name:12} floor {floor:10} installed {installed:10} {status}")
        if not matches:
            print(f"::error::{name} is {installed}, not its declared floor {floor}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
