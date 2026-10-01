"""Refuse a release that is not ready, before anything is built or published.

Run by ``release.yml``. For a tag push it checks that the tag names the version
in ``pyproject.toml`` and that the tagged commit is on ``main``; for every run,
tag or dry run, that ``CHANGELOG.md`` has a non-empty section for the version.
The version, and whether it is a pre-release, go to ``$GITHUB_OUTPUT``.

Locally: ``python .github/scripts/check_release.py [--tag vX.Y.Z]``.
"""

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def package_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


def changelog_section(version: str) -> str | None:
    """Return the body of the ``## [version]`` section, or ``None`` if absent."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        return None
    following = re.search(r"^## ", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[match.end() : end]


def on_main(ref: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, "origin/main"],
        cwd=ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="the pushed tag; omit for a dry run")
    args = parser.parse_args()

    version = package_version()
    errors: list[str] = []

    if args.tag is not None:
        if args.tag != f"v{version}":
            errors.append(f"tag {args.tag} does not match pyproject.toml version {version}")
        if not on_main(args.tag):
            errors.append(f"tag {args.tag} is not on main; release only from main")

    section = changelog_section(version)
    if section is None:
        errors.append(f"CHANGELOG.md has no '## [{version}]' section")
    elif not section.strip():
        errors.append(f"CHANGELOG.md's '## [{version}]' section is empty")

    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1

    print(f"Release checks passed for {version}" + ("" if args.tag else " (dry run)"))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
            # 0.7.0rc1, 0.7.0b2, 0.7.0.dev3: anything with letters is not final.
            handle.write(f"prerelease={str(bool(re.search('[a-z]', version))).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
