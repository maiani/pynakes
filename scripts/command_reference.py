"""Write the generated command reference from the live CLI.

Run it before building the documentation: ``python scripts/command_reference.py``.
``--check`` exits 1 without writing when the committed page is stale, as
``tests/test_doc_examples.py`` also asserts.
"""

import sys
from pathlib import Path

from pynakes._cli_reference import render_command_reference

TARGET = Path(__file__).resolve().parents[1] / "docs" / "guides" / "command-reference.md"


def main(argv: list[str]) -> int:
    content = render_command_reference()
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if "--check" in argv:
        if current != content:
            print(f"{TARGET} is stale; run python scripts/command_reference.py", file=sys.stderr)
            return 1
        return 0
    if current != content:
        TARGET.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
