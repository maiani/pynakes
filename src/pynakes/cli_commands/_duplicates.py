"""What a ``DuplicateCitationKey`` conflict tells its caller.

Refusing to guess between entries that share a citation key is right; making
the caller run another command just to see what it is choosing between is
waste. Every such conflict therefore carries the candidates: each entry's
position, its triage summary with the fields that tell the entries apart
(named under ``differs``), and a
``--where`` expression that selects exactly that entry — checked against the
library before it is offered, so it is never a guess either.
"""

from pynakes.model import BibEntry, BibFile
from pynakes.query import parse_query
from pynakes.triage import entry_summary

#: The ways out of a duplicate-key conflict, the person-in-the-loop one first.
DUPLICATE_KEY_OPTIONS = [
    {
        "id": "ask_which",
        "description": "Ask which entry is meant: each candidate's fields show what tells "
        "them apart (differs names those fields)",
    },
    {
        "id": "select_one",
        "description": "Act on one entry with a --where command (fields set, ref show, "
        "ref directive, ...) using that candidate's where expression",
    },
    {
        "id": "repair_duplicates",
        "description": "Run keys repair to make the keys unique, then retry with the resulting key",
    },
]


def duplicate_candidates(lib: BibFile, key: str) -> list[dict[str, object]]:
    """Describe every entry sharing ``key``, each with a selector for itself."""
    entries = list(lib.entries.values())
    matches = [(index, entry) for index, entry in enumerate(entries) if entry.key == key]
    differing = _differing_fields([entry for _index, entry in matches])
    return [
        {
            "index": index,
            "line": entry.start_line,
            "type": entry.type,
            # The triage summary plus whatever else differs, each value once.
            "fields": {
                **entry_summary(entry),
                **{name: entry.fields.get(name) for name in differing},
            },
            "differs": differing,
            "where": _selector(lib, key, entry, differing),
        }
        for index, entry in matches
    ]


def _differing_fields(entries: list[BibEntry]) -> list[str]:
    """Return the field names whose values are not the same in every entry."""
    names = sorted({name for entry in entries for name in entry.fields})
    return [name for name in names if len({entry.fields.get(name) for entry in entries}) > 1]


def _selector(lib: BibFile, key: str, entry: BibEntry, differing: list[str]) -> str | None:
    """Return a ``--where`` that matches ``entry`` alone, or ``None`` if none is found.

    Tries one distinguishing field at a time, preferring the ones a person
    reads first, and keeps an expression only after confirming it selects
    exactly this physical entry.
    """
    preferred = ["year", "date", "title", "volume", "edition"]
    ordered = [name for name in preferred if name in differing] + [
        name for name in differing if name not in preferred
    ]
    quoted_key = _quote(key)
    for name in ordered:
        value = entry.fields.get(name)
        quoted = None if value is None else _quote(value)
        if quoted_key is None or (value is not None and quoted is None):
            continue
        expression = (
            f"key = {quoted_key} and {name} missing"
            if value is None
            else f"key = {quoted_key} and {name} = {quoted}"
        )
        try:
            node = parse_query(expression)
        except ValueError:
            continue
        if [candidate for candidate in lib.entries.values() if node(candidate)] == [entry]:
            return expression
    return None


def _quote(value: str) -> str | None:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return None
