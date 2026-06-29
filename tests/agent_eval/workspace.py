"""Workspace creation for the agent beta-test harness."""

from __future__ import annotations

import os
import shlex
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabWorkspace:
    root: Path
    bib: Path
    tex: Path
    docs_dir: Path
    bin_dir: Path
    env: dict[str, str]


def create_lab_workspace(
    repo_root: Path, *, seed: int, lab_root: Path | None = None
) -> LabWorkspace:
    """Create an isolated bibliography workspace for the beta tester."""

    root = lab_root or Path(tempfile.mkdtemp(prefix=f"pynakes-agent-eval-{seed}-"))
    root.mkdir(parents=True, exist_ok=True)
    docs_dir = root / "docs"
    bin_dir = root / "bin"
    docs_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)

    bib = root / "refs.bib"
    bib.write_text(
        "@article{Smith2020,\n"
        "  author = {Jane Smith and Alan Doe},\n"
        "  title = {A Small Study of Deterministic Widgets},\n"
        "  journal = {Journal of Widget Studies},\n"
        "  year = {2020},\n"
        "  doi = {https://doi.org/10.5555/widget.2020}\n"
        "}\n\n"
        "@article{Smith2020,\n"
        "  author = {Jane Smith and Alan Doe},\n"
        "  title = {A Small Study of Deterministic Widgets},\n"
        "  journal = {Journal of Widget Studies},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/widget.2020}\n"
        "}\n\n"
        "@book{Knuth1984,\n"
        "  author = {Donald E. Knuth},\n"
        "  title = {The TeXbook},\n"
        "  year = {1984},\n"
        "  publisher = {Addison-Wesley}\n"
        "}\n"
    )

    tex = root / "paper.tex"
    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "We cite widgets~\\cite{Smith2020} and typesetting~\\cite{Knuth1984}.\n"
        "\\bibliography{refs}\n"
        "\\end{document}\n"
    )

    source_doc = repo_root / "docs" / "guides" / "llm-integration.md"
    if source_doc.exists():
        (docs_dir / "llm-integration.md").write_text(source_doc.read_text())

    wrapper = bin_dir / "pynakes"
    src_path = shlex.quote(str(repo_root / "src"))
    python = shlex.quote(sys.executable)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"PYTHONPATH={src_path}${{PYTHONPATH:+:$PYTHONPATH}} "
        f'{python} -m pynakes "$@"\n'
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": f"{repo_root / 'src'}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    return LabWorkspace(root=root, bib=bib, tex=tex, docs_dir=docs_dir, bin_dir=bin_dir, env=env)
