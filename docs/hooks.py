"""Generate the CLI reference before MkDocs collects documentation files."""

from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig

from pynakes._cli_reference import render_command_reference


def on_pre_build(config: MkDocsConfig, **kwargs: object) -> None:
    target = Path(config["docs_dir"]) / "guides" / "command-reference.md"
    content = render_command_reference()
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
