"""Property-based tests (hypothesis) for parser/writer robustness.

These complement the example-based tests by exercising the parser and writer
over a wide, randomly generated space of valid and arbitrary inputs. Two
guarantees are checked:

1. **Round-trip fidelity** — for generated valid BibTeX, ``parse → write →
   parse`` preserves every key, type, and field/value pair.
2. **No tracebacks on garbage** — ``parse_bib`` over arbitrary text either
   returns a ``BibFile`` or raises the declared ``ParseError`` (never an
   unexpected exception).
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib

# Citation keys: start with a letter, alphanumeric thereafter (no comma/space/brace).
_keys = st.from_regex(r"[A-Za-z][A-Za-z0-9]{0,15}", fullmatch=True)
# Entry types: plain lowercase words.
_types = st.sampled_from(["article", "book", "inproceedings", "misc", "techreport", "thesis"])
# Field names: lowercase ascii words.
_field_names = st.from_regex(r"[a-z][a-z0-9]{0,12}", fullmatch=True)
# Field values: printable text without the brace/quote/comma/newline/percent
# characters that carry structural meaning, and no trailing backslash.
_value_chars = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        blacklist_characters="{}\"'%,\\@",
    ),
    max_size=40,
)
_values = _value_chars.map(str.strip)


@st.composite
def _libraries(draw: st.DrawFn) -> str:
    """Render a structured set of entries as canonical BibTeX text."""
    n = draw(st.integers(min_value=1, max_value=6))
    keys = draw(st.lists(_keys, min_size=n, max_size=n, unique_by=str.lower))
    blocks = []
    for key in keys:
        etype = draw(_types)
        names = draw(st.lists(_field_names, min_size=1, max_size=6, unique=True))
        rendered = ",\n".join(f"  {name} = {{{draw(_values)}}}" for name in names)
        blocks.append(f"@{etype}{{{key},\n{rendered}\n}}")
    return "\n\n".join(blocks) + "\n"


@st.composite
def _paren_libraries(draw: st.DrawFn) -> str:
    """Render entries using the parenthesis delimiter form ``@type(key,...)``.

    BibTeX 0.99d accepts both ``{...}`` and ``(...)`` as entry delimiters.
    This strategy exercises the parser's paren path and the writer's round-trip
    guarantee on that form.
    """
    n = draw(st.integers(min_value=1, max_value=4))
    keys = draw(st.lists(_keys, min_size=n, max_size=n, unique_by=str.lower))
    blocks = []
    for key in keys:
        etype = draw(_types)
        names = draw(st.lists(_field_names, min_size=1, max_size=5, unique=True))
        rendered = ",\n".join(f"  {name} = {{{draw(_values)}}}" for name in names)
        # Use parenthesis delimiter — syntactically equivalent to braces.
        blocks.append(f"@{etype}({key},\n{rendered}\n)")
    return "\n\n".join(blocks) + "\n"


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(_libraries())
def test_parse_write_parse_preserves_content(text: str) -> None:
    """parse → write → parse keeps every key, type, and field/value pair."""
    lib1 = parse_bib(text)
    lib2 = parse_bib(write_bib(lib1))

    keys1 = [e.key for e in lib1.entries.values()]
    keys2 = [e.key for e in lib2.entries.values()]
    assert keys1 == keys2

    for e1, e2 in zip(lib1.entries.values(), lib2.entries.values()):
        assert e1.type == e2.type
        assert e1.fields == e2.fields


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(_libraries())
def test_unmodified_entries_write_back_verbatim(text: str) -> None:
    """Each unmodified entry's raw_content is reused byte-for-byte on write.

    (The per-entry guarantee — invariant #1. Whole-file blank-line spacing is a
    separate concern handled by the CLI's surgical splice path, not ``write_bib``.)
    """
    lib = parse_bib(text)
    output = write_bib(lib)
    for entry in lib.entries.values():
        assert entry.modified is False
        assert entry.raw_content is not None
        assert entry.raw_content in output


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(_paren_libraries())
def test_paren_entries_parse_and_round_trip(text: str) -> None:
    """Parenthesized entries ``@type(key,...)`` parse and survive write → re-parse.

    Unmodified paren entries must write back byte-for-byte (invariant #1).
    After re-parse the entry records must match the original.
    """
    lib = parse_bib(text)
    output = write_bib(lib)

    # Unmodified paren entries must reuse raw_content byte-for-byte.
    for entry in lib.entries.values():
        assert entry.raw_content is not None
        assert entry.raw_content in output
        assert entry.raw_content.startswith("@") and "(" in entry.raw_content

    # Re-parse of written output must preserve keys, types, and fields.
    lib2 = parse_bib(output)
    for e1, e2 in zip(lib.entries.values(), lib2.entries.values()):
        assert e1.key == e2.key
        assert e1.type == e2.type
        assert e1.fields == e2.fields


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(max_size=200))
def test_parser_never_crashes_on_arbitrary_text(text: str) -> None:
    """Arbitrary input yields a BibFile or a declared ParseError — never a traceback."""
    try:
        lib = parse_bib(text)
    except ParseError:
        return
    # If it parsed, the result must be writable without error.
    assert isinstance(write_bib(lib), str)
