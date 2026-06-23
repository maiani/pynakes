"""Journal title abbreviation and expansion.

The resolver order is intentionally explicit:

1. user-provided title/ISSN mappings,
2. bundled exact title mappings for known exceptions,
3. LTWA-style word abbreviation generation,
4. leave unchanged and warn.

The built-in LTWA data is a small seed table for common words. For broader
coverage, pass an LTWA CSV export with ``--ltwa-table`` or through normalize
metadata. User journal tables are still preferred because exact journal
abbreviations are less ambiguous than word-level generation.
"""

import csv
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Optional

from pynakes.editing import set_entry_field
from pynakes.model import BibEntry, BibFile

JOURNAL_FIELDS = ("journal", "journaltitle")
ISSN_FIELDS = ("issn", "eissn", "e-issn")
JOURNAL_STYLES = {"abbreviated", "full", "none"}

BUILTIN_EXACT_ABBREVIATIONS = {
    "ACM Transactions": "ACM Trans.",
    "American Economic Review": "Am. Econ. Rev.",
    "Econometrica": "Econometrica",
    "Journal of Finance": "J. Finance",
    "Journal of Financial Economics": "J. Financ. Econ.",
    "Journal of Machine Learning Research": "J. Mach. Learn. Res.",
    "Journal of Money, Credit and Banking": "J. Money Credit Bank.",
    "Journal of Political Economy": "J. Polit. Econ.",
    "Nature": "Nature",
    "Nature Machine Intelligence": "Nat. Mach. Intell.",
    "Physical Review B": "Phys. Rev. B",
    "Physical Review Letters": "Phys. Rev. Lett.",
    "Proceedings of the National Academy of Sciences": "Proc. Natl. Acad. Sci.",
    "Review of Economic Studies": "Rev. Econ. Stud.",
    "Science": "Science",
}

BUILTIN_LTWA_WORDS = {
    "academy": "Acad.",
    "acm": "ACM",
    "advanced": "Adv.",
    "advances": "Adv.",
    "american": "Am.",
    "analysis": "Anal.",
    "applied": "Appl.",
    "artificial": "Artif.",
    "association": "Assoc.",
    "banking": "Bank.",
    "biological": "Biol.",
    "biology": "Biol.",
    "chemistry": "Chem.",
    "communications": "Commun.",
    "computer": "Comput.",
    "computing": "Comput.",
    "cryptography": "Cryptogr.",
    "data": "Data",
    "economic": "Econ.",
    "economics": "Econ.",
    "european": "Eur.",
    "finance": "Finance",
    "financial": "Financ.",
    "intelligence": "Intell.",
    "international": "Int.",
    "journal": "J.",
    "learning": "Learn.",
    "letters": "Lett.",
    "machine": "Mach.",
    "management": "Manag.",
    "mathematics": "Math.",
    "medicine": "Med.",
    "money": "Money",
    "national": "Natl.",
    "nature": "Nat.",
    "pattern": "Pattern",
    "physical": "Phys.",
    "physics": "Phys.",
    "political": "Polit.",
    "polymer": "Polym.",
    "proceedings": "Proc.",
    "review": "Rev.",
    "science": "Sci.",
    "scientific": "Sci.",
    "studies": "Stud.",
    "systems": "Syst.",
    "transactions": "Trans.",
}

LTWA_OMIT_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
}


@dataclass(frozen=True)
class JournalMapping:
    """One authoritative mapping between a full journal title and abbreviation.

    ``issn`` disambiguates titles when available; ``source`` records whether
    the mapping came from a user table, bundled data, or another loader.
    """

    title: str
    abbreviated: str
    issn: Optional[str] = None
    source: str = "user"


@dataclass
class JournalSources:
    """The layered lookup index used to resolve journal-title conventions.

    Exact title and ISSN mappings take precedence over ``ltwa_words`` because
    a journal-specific abbreviation is less ambiguous than word-level rules.
    """

    title_mappings: dict[str, JournalMapping] = dataclass_field(default_factory=dict)
    issn_mappings: dict[str, JournalMapping] = dataclass_field(default_factory=dict)
    ltwa_words: dict[str, str] = dataclass_field(default_factory=lambda: dict(BUILTIN_LTWA_WORDS))


@dataclass
class JournalResult:
    """Outcome of an in-place journal-title normalization pass.

    ``resolved`` records the mappings applied; ``unknown`` records titles left
    intact because none of the configured sources could resolve them.
    """

    changed: int = 0
    unknown: list[str] = dataclass_field(default_factory=list)
    resolved: list[dict[str, str]] = dataclass_field(default_factory=list)


def _journal_key(value: str) -> str:
    lowered = value.lower().replace("&", "and")
    stripped = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return " ".join(stripped.split())


def _issn_key(value: str) -> str:
    return re.sub(r"[^0-9xX]", "", value).upper()


def _clean_cell(value: str | None) -> str:
    return (value or "").strip()


def _first_present(row: dict[str, str], names: tuple[str, ...]) -> str:
    normalized = {key.strip().lower(): value for key, value in row.items()}
    for name in names:
        value = _clean_cell(normalized.get(name))
        if value:
            return value
    return ""


TITLE_COLUMNS = ("title", "full", "full_title", "journal")
ABBREV_COLUMNS = ("abbreviation", "abbreviated", "abbrev", "short", "short_title")
TABLE_ISSN_COLUMNS = ("issn", "eissn", "e-issn")


def _sniff_dialect(sample: list[str]) -> csv.Dialect | type[csv.Dialect]:
    return csv.Sniffer().sniff("\n".join(sample[:5]), delimiters=",\t;")


def _sniff_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV/TSV file into row dicts, sniffing the delimiter (`,`/tab/`;`)."""
    sample = path.read_text(encoding="utf-8-sig").splitlines()
    if not sample:
        return []
    dialect = _sniff_dialect(sample)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, dialect=dialect))


def _read_table_rows(path: Path) -> list[list[str]]:
    """Read a CSV/TSV file into raw cell lists, sniffing the delimiter."""
    sample = path.read_text(encoding="utf-8-sig").splitlines()
    if not sample:
        return []
    dialect = _sniff_dialect(sample)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle, dialect=dialect) if row]


def _looks_like_header(row: list[str]) -> bool:
    """Whether the first row names columns rather than carrying data.

    JabRef's own abbreviation lists (from ``abbrv.jabref.org``) are headerless
    — ``"Full Name","Abbreviation"[,"Shortest unique abbreviation"]`` — so we
    treat a file as having a header only when the first row contains both a
    recognized title column *and* a recognized abbreviation column.
    """
    cells = {cell.strip().lower() for cell in row}
    return bool(cells & set(TITLE_COLUMNS)) and bool(cells & set(ABBREV_COLUMNS))


def unknown_journal_warnings(titles: list[str]) -> list[dict[str, str]]:
    """Build the standard ``unknown_journal`` warning dicts for unresolved titles.

    Single source of truth for the warning shape shared by ``pynakes journals``
    and the ``normalize`` routine.
    """
    return [
        {
            "type": "unknown_journal",
            "message": f"No abbreviation table entry for journal {title!r}; left unchanged",
            "journal": title,
        }
        for title in titles
    ]


def add_mapping(sources: JournalSources, mapping: JournalMapping) -> None:
    """Add a title/ISSN mapping. Later mappings for the same key win."""
    sources.title_mappings[_journal_key(mapping.title)] = mapping
    if mapping.issn:
        sources.issn_mappings[_issn_key(mapping.issn)] = mapping


def builtin_sources() -> JournalSources:
    """Return bundled exact mappings plus the seed LTWA word table."""
    sources = JournalSources()
    for title, abbreviated in BUILTIN_EXACT_ABBREVIATIONS.items():
        add_mapping(
            sources,
            JournalMapping(
                title=title,
                abbreviated=abbreviated,
                source="builtin_exact",
            ),
        )
    return sources


def load_journal_table(path: str | Path, sources: JournalSources | None = None) -> JournalSources:
    """Load exact journal mappings from CSV/TSV.

    Two layouts are accepted:

    * **Headed** — a first row naming the columns. Recognized names:
      ``title``/``full``/``full_title``/``journal``,
      ``abbreviation``/``abbreviated``/``abbrev``/``short``/``short_title``,
      and optional ``issn``/``eissn``.
    * **Headerless** — JabRef's own ``abbrv.jabref.org`` format,
      ``"Full Name","Abbreviation"[,"Shortest unique abbreviation"]``. The
      first two columns are used; any third column is ignored.
    """
    target = sources or JournalSources()
    table_path = Path(path)
    rows = _read_table_rows(table_path)
    if not rows:
        return target

    if _looks_like_header(rows[0]):
        header = [cell.strip() for cell in rows[0]]
        for raw in rows[1:]:
            record = dict(zip(header, raw))
            title = _first_present(record, TITLE_COLUMNS)
            abbreviated = _first_present(record, ABBREV_COLUMNS)
            issn = _first_present(record, TABLE_ISSN_COLUMNS) or None
            _add_table_mapping(target, table_path, title, abbreviated, issn)
    else:
        for raw in rows:
            title = _clean_cell(raw[0]) if raw else ""
            abbreviated = _clean_cell(raw[1]) if len(raw) > 1 else ""
            _add_table_mapping(target, table_path, title, abbreviated, None)
    return target


def _add_table_mapping(
    target: JournalSources,
    table_path: Path,
    title: str,
    abbreviated: str,
    issn: str | None,
) -> None:
    if not title or not abbreviated:
        return
    add_mapping(
        target,
        JournalMapping(
            title=title,
            abbreviated=abbreviated,
            issn=issn,
            source=str(table_path),
        ),
    )


def load_ltwa_table(path: str | Path, sources: JournalSources | None = None) -> JournalSources:
    """Load title-word abbreviations from an LTWA-style CSV/TSV export."""
    target = sources or JournalSources()
    for row in _sniff_rows(Path(path)):
        word = _first_present(row, ("word", "title word", "title_word"))
        abbreviation = _first_present(row, ("abbreviation", "abbr", "short"))
        if not word:
            continue
        if abbreviation.lower() == "none":
            abbreviation = word
        if abbreviation:
            target.ltwa_words[_journal_key(word)] = abbreviation
    return target


def load_sources(
    journal_table: str | Path | None = None,
    ltwa_table: str | Path | None = None,
) -> JournalSources:
    """Load bundled sources plus optional user exact and LTWA tables."""
    sources = builtin_sources()
    if journal_table:
        load_journal_table(journal_table, sources)
    if ltwa_table:
        load_ltwa_table(ltwa_table, sources)
    return sources


def _entry_issns(entry: BibEntry) -> list[str]:
    values: list[str] = []
    for field in ISSN_FIELDS:
        raw = entry.fields.get(field)
        if not raw:
            continue
        values.extend(part.strip() for part in re.split(r"[;,]", raw) if part.strip())
    return values


def _lookup_exact(title: str, entry: BibEntry, sources: JournalSources) -> tuple[str, str] | None:
    for issn in _entry_issns(entry):
        mapping = sources.issn_mappings.get(_issn_key(issn))
        if mapping:
            return mapping.abbreviated, mapping.source
    mapping = sources.title_mappings.get(_journal_key(title))
    if mapping:
        return mapping.abbreviated, mapping.source
    return None


def _lookup_expansion(title: str, sources: JournalSources) -> tuple[str, str] | None:
    key = _journal_key(title)
    for mapping in sources.title_mappings.values():
        if _journal_key(mapping.abbreviated) == key:
            return mapping.title, mapping.source
    return None


def _word_abbreviation(word: str, sources: JournalSources) -> str | None:
    key = _journal_key(word)
    if not key:
        return ""
    # Single capital letters are section/series identifiers ("Phys. Rev. A",
    # "Series B") and must be kept verbatim — including "A", which would
    # otherwise be swallowed by the omitted stop word "a".
    if len(word) == 1 and word.isupper():
        return word
    if key in LTWA_OMIT_WORDS:
        return ""
    if word.isupper() and len(word) <= 6:
        return word
    return sources.ltwa_words.get(key)


def abbreviate_title_with_ltwa(title: str, sources: JournalSources | None = None) -> str | None:
    """Generate an ISO-4-style abbreviation from title words.

    Returns ``None`` (meaning "leave unchanged and warn") when the title cannot
    be abbreviated *in full*: if any significant word is missing from the
    abbreviation sources we decline rather than emit a half-abbreviated,
    inconsistent title such as ``Nat. Nanotechnology``. ``None`` is likewise
    returned when nothing actually changes (already-abbreviated input).
    """
    active = sources or builtin_sources()
    tokens = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[^\w\s]", title)
    output: list[str] = []
    changed = False

    for token in tokens:
        if re.fullmatch(r"[^\w\s]", token):
            # Punctuation attaches to the preceding word with no leading space;
            # skip a doubled separator when the abbreviation already carries one
            # (e.g. "Commun." followed by a source period).
            if not output:
                output.append(token)
            elif not output[-1].endswith(token):
                output[-1] = output[-1] + token
            continue
        parts = token.split("-")
        abbreviated_parts: list[str] = []
        for part in parts:
            abbreviation = _word_abbreviation(part, active)
            if abbreviation == "":
                changed = True
                continue
            if abbreviation is None:
                # An unresolved significant word means we cannot build a
                # trustworthy abbreviation; decline the whole title.
                return None
            if abbreviation != part:
                changed = True
            abbreviated_parts.append(abbreviation)
        if abbreviated_parts:
            output.append("-".join(abbreviated_parts))

    if not changed:
        return None
    return " ".join(part for part in output if part)


def _target_for_title(
    title: str,
    entry: BibEntry,
    style: str,
    sources: JournalSources,
) -> tuple[str, str] | None:
    if style == "full":
        return _lookup_expansion(title, sources)
    exact = _lookup_exact(title, entry, sources)
    if exact:
        return exact
    generated = abbreviate_title_with_ltwa(title, sources)
    if generated:
        return generated, "ltwa"
    return None


def expected_journal_title(
    title: str,
    entry: BibEntry,
    style: str,
    sources: JournalSources | None = None,
) -> str | None:
    """Return the configured canonical title, or ``None`` when it is unknown.

    Unlike :func:`normalize_journals`, this function never mutates an entry.
    A missing result is deliberately not a lint violation: without a mapping,
    pynakes cannot reliably determine whether an unknown value is full or
    abbreviated.
    """
    if style not in JOURNAL_STYLES:
        raise ValueError(f"Unsupported journal style: {style!r}")
    if style == "none":
        return title
    target = _target_for_title(title, entry, style, sources or builtin_sources())
    return target[0] if target is not None else None


def classify_journal(title: str, entry: BibEntry, sources: JournalSources) -> str:
    """Describe how ``title`` would resolve for abbreviation.

    Returns the exact-mapping source label (e.g. ``builtin_exact`` or a table
    path) when an exact title/ISSN mapping exists, ``ltwa`` when an abbreviation
    can be generated from title words, or ``unknown`` otherwise.
    """
    exact = _lookup_exact(title, entry, sources)
    if exact is not None:
        return exact[1]
    if abbreviate_title_with_ltwa(title, sources) is not None:
        return "ltwa"
    return "unknown"


def normalize_journals(
    lib: BibFile,
    style: str = "abbreviated",
    sources: JournalSources | None = None,
) -> JournalResult:
    """Abbreviate or expand journal titles."""
    if style not in JOURNAL_STYLES:
        raise ValueError(f"Unsupported journal style: {style!r}")
    if style == "none":
        return JournalResult()

    active = sources or builtin_sources()
    result = JournalResult()
    seen_unknown: set[str] = set()

    for entry in lib.entries.values():
        for field in JOURNAL_FIELDS:
            value = entry.fields.get(field)
            if not value:
                continue
            target = _target_for_title(value, entry, style, active)
            if target is None:
                if value not in seen_unknown:
                    seen_unknown.add(value)
                    result.unknown.append(value)
                continue
            target_value, source = target
            if set_entry_field(entry, field, target_value):
                result.changed += 1
                result.resolved.append(
                    {
                        "entry_key": entry.key,
                        "field": field,
                        "source": source,
                        "old": value,
                        "new": target_value,
                    }
                )

    return result
