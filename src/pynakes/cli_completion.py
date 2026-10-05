"""Shell-completion callbacks for citation keys, libraries, and metadata keys."""

from pathlib import Path

from click.shell_completion import CompletionItem

from pynakes.bibtex_parser import parse_bib
from pynakes.cli_common import bib_candidates, single_bib_file


def _citekey_completer(ctx, incomplete):
    """Shell-completion callback yielding matching citation keys.

    Intended for use as ``param.shell_complete`` on citekey arguments.
    Auto-detects the ``.bib`` file from ``ctx.params`` or the current directory.

    Click/ShellComplete calls this with ``(ctx, incomplete)`` — see
    ``ShellComplete.get_completions``.
    """
    file = ctx.params.get("file") or ctx.params.get("bib_file")
    if file is None:
        candidate = single_bib_file(Path.cwd())
        if candidate is None:
            return []
        file = str(candidate)
    try:
        lib = parse_bib(Path(file).read_text(encoding="utf-8"))
        return [
            CompletionItem(key)
            for key in sorted(set(lib.entries.keys()))
            if incomplete.lower() in key.lower()
        ]
    except Exception:
        return []


def _bibfile_completer(ctx, incomplete):
    """Shell-completion callback for the ``.bib`` file positional argument.

    When a single ``.bib`` file can be auto-detected, this returns citekeys
    from that library (so the user can Tab complete citekeys without first
    filling in the file argument).  Otherwise it falls back to suggesting
    ``.bib`` filenames.
    """
    candidate = single_bib_file(Path.cwd())
    if candidate is not None:
        name = candidate.name
        items: list[CompletionItem] = []
        if incomplete.lower() in name.lower():
            items.append(CompletionItem(name))
        try:
            lib = parse_bib(candidate.read_text(encoding="utf-8"))
        except Exception:
            return items
        for key in sorted(set(lib.entries.keys())):
            if incomplete.lower() in key.lower():
                items.append(CompletionItem(key))
        return items
    try:
        return [
            CompletionItem(p.name)
            for p in bib_candidates(Path("."))
            if incomplete.lower() in p.name.lower()
        ]
    except Exception:
        return []


def _metadata_key_completer(ctx, incomplete):
    """Shell-completion callback yielding known metadata keys.

    Intended for use as ``param.shell_complete`` on the ``key`` argument of
    ``metadata set``. Suggests all keys known to either JabRef or pynakes.
    """
    from pynakes.metadata.jabref import JABREF_EXACT_KEYS, JABREF_PREFIX_KEYS
    from pynakes.metadata.schema import PYNAKES_EXACT_KEYS, PYNAKES_PREFIX_KEYS

    incomplete_lower = incomplete.lower()
    items: list[CompletionItem] = []
    for key in JABREF_EXACT_KEYS:
        if incomplete_lower in key.lower():
            items.append(CompletionItem(key))
    for key in PYNAKES_EXACT_KEYS:
        if incomplete_lower in key.lower():
            items.append(CompletionItem(key))
    for prefix in JABREF_PREFIX_KEYS:
        if incomplete_lower in prefix.lower():
            items.append(CompletionItem(prefix))
    for prefix in PYNAKES_PREFIX_KEYS:
        if incomplete_lower in prefix.lower():
            items.append(CompletionItem(prefix))
    return items
