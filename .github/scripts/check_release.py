"""Refuse a release that is not ready, before anything is built or published.

Run by ``release.yml``. The package version comes from git through
setuptools-scm, so a tag is the release: for a tag push the version is the
tag's (``vX.Y.Z`` releases ``X.Y.Z``) and the tagged commit must be on ``main``.
A dry run takes the version the next release would have, which setuptools-scm
derives from the latest tag (needs ``setuptools-scm`` installed). For every
run, ``CHANGELOG.md`` must have a non-empty section for the version. The
version, and whether it is a pre-release, go to ``$GITHUB_OUTPUT``.

With ``--dist DIR`` it instead checks that the wheel and sdist built into
``DIR`` carry the tag's version, since a tag setuptools-scm does not take as
the version (not on the built commit, not PEP 440, not canonical) would
otherwise publish under a different number.

Locally: ``python .github/scripts/check_release.py [--tag vX.Y.Z] [--dist dist]``.
"""

import argparse
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A final or pre-release version in canonical PEP 440 form: 0.7.0, 0.7.0rc1.
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")


def tag_version(tag: str) -> str | None:
    """Return the version a ``vX.Y.Z`` tag releases, or ``None`` if malformed."""
    version = tag.removeprefix("v")
    if tag == version or RELEASE_VERSION.fullmatch(version) is None:
        return None
    return version


def next_release_version() -> str:
    """Return the version the next release would have, from git via setuptools-scm."""
    result = subprocess.run(
        [sys.executable, "-m", "setuptools_scm", "--strip-dev"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


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


def metadata_version(metadata: str) -> str | None:
    match = re.search(r"^Version:\s*(\S+)\s*$", metadata, re.MULTILINE)
    return match.group(1) if match else None


def dist_versions(dist: Path) -> dict[str, str | None]:
    """Return the ``Version:`` each wheel and sdist in ``dist`` declares, by file name."""
    versions: dict[str, str | None] = {}
    for wheel in sorted(dist.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            versions[wheel.name] = metadata_version(archive.read(name).decode("utf-8"))
    for sdist in sorted(dist.glob("*.tar.gz")):
        with tarfile.open(sdist) as archive:
            # The top-level PKG-INFO, not the copy under src/*.egg-info/.
            member = next(
                m for m in archive.getmembers() if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")
            )
            handle = archive.extractfile(member)
            assert handle is not None
            versions[sdist.name] = metadata_version(handle.read().decode("utf-8"))
    return versions


def check_dist(version: str, dist: Path) -> list[str]:
    versions = dist_versions(dist)
    if not any(name.endswith(".whl") for name in versions):
        return [f"no wheel in {dist}"]
    if not any(name.endswith(".tar.gz") for name in versions):
        return [f"no sdist in {dist}"]
    return [
        f"{name} has version {found}, not the tag's {version}"
        for name, found in versions.items()
        if found != version
    ]


def write_outputs(version: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
            # 0.7.0rc1, 0.7.0b2: anything with letters is not final.
            handle.write(f"prerelease={str(bool(re.search('[a-z]', version))).lower()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="the pushed tag; omit for a dry run")
    parser.add_argument("--dist", type=Path, help="check the distributions built here instead")
    args = parser.parse_args()

    errors: list[str] = []
    if args.tag is not None:
        version = tag_version(args.tag)
        if version is None:
            errors.append(f"tag {args.tag} is not of the form vX.Y.Z (or vX.Y.ZrcN, aN, bN)")
    elif args.dist is not None:
        errors.append("--dist needs --tag")
        version = None
    else:
        version = next_release_version()

    if version is not None and args.dist is not None:
        errors.extend(check_dist(version, args.dist))
    elif version is not None:
        if args.tag is not None and not on_main(args.tag):
            errors.append(f"tag {args.tag} is not on main; release only from main")
        section = changelog_section(version)
        if section is None:
            errors.append(f"CHANGELOG.md has no '## [{version}]' section")
        elif not section.strip():
            errors.append(f"CHANGELOG.md's '## [{version}]' section is empty")

    for error in errors:
        print(f"::error::{error}")
    if errors or version is None:
        return 1

    if args.dist is not None:
        print(f"Distributions in {args.dist} carry version {version}")
        return 0
    print(f"Release checks passed for {version}" + ("" if args.tag else " (dry run)"))
    write_outputs(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
