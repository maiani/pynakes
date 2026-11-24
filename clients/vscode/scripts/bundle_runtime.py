"""Build native dependency variants; only the build step accesses the network."""

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import distributions
from pathlib import Path

PLATFORMS = (
    "manylinux2014_x86_64",
    "macosx_10_12_x86_64",
    "macosx_11_0_arm64",
    "win_amd64",
)
PYTHONS = ("3.12", "3.13", "3.14", "3.15")


def build(root: Path) -> None:
    """Replace the build interpreter's native dependency with explicit variants."""
    versions = {dist.metadata["Name"]: dist.version for dist in distributions(path=[str(root)])}
    version = versions["pydantic_core"]
    shutil.rmtree(root / "pydantic_core")
    for info in root.glob("pydantic_core-*.dist-info"):
        shutil.rmtree(info)
    # Fail closed if a future dependency introduces another native extension.
    native = [p for p in root.rglob("*") if p.suffix in {".so", ".pyd", ".dylib"}]
    if native:
        raise RuntimeError(f"Unclassified native dependencies: {native}")
    variants = []
    with tempfile.TemporaryDirectory(prefix="pynakes-native-") as scratch:
        for python in PYTHONS:
            for platform in PLATFORMS:
                abi = "cp" + python.replace(".", "")
                destination = Path(scratch) / f"{abi}-{platform}"
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "download",
                        f"pydantic-core=={version}",
                        "--only-binary=:all:",
                        "--no-deps",
                        "--implementation",
                        "cp",
                        "--python-version",
                        python,
                        "--abi",
                        abi,
                        "--platform",
                        platform,
                        "--dest",
                        str(destination),
                        "-q",
                    ],
                    check=True,
                )
                (wheel,) = destination.glob("*.whl")
                relative = Path("native") / wheel.stem
                with zipfile.ZipFile(wheel) as archive:
                    archive.extractall(root / relative)
                variants.append({"wheel": wheel.name, "path": relative.as_posix()})
    (root / "native.json").write_text(json.dumps(variants, indent=2) + "\n")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
