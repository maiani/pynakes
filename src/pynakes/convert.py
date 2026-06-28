"""Conversion between BibTeX and BibLaTeX conventions, in both directions.

Translates the field and entry-type vocabulary of one dialect into the other,
editing each entry surgically so untouched fields keep their exact formatting.
Unknown fields, groups, and comments are preserved; a conversion never clobbers
a target field that is already present (it reports a warning instead) and never
discards information it cannot safely translate.
"""

from dataclasses import dataclass, field

from pynakes.editing import (
    remove_entry_field,
    rename_entry_field,
    set_entry_field,
    set_entry_type,
)
from pynakes.formatters import _ISO_DATE_RE, _MONTH_NUM_TO_ABBR, month_number_str
from pynakes.model import BibEntry, BibFile

TO_BIBLATEX = "biblatex"
TO_BIBTEX = "bibtex"
TARGETS = (TO_BIBLATEX, TO_BIBTEX)

# Field renames per direction (old → new), applied only when the target field is
# absent. ``school``/``institution`` are deliberately omitted here: ``school``
# only ever maps forward (thesis-only field), and ``institution`` reverts only
# inside a thesis (see ``_revert_thesis``), since elsewhere it is a legitimate
# BibTeX field (e.g. ``@techreport``).
_TO_BIBLATEX_FIELDS: dict[str, str] = {
    "journal": "journaltitle",
    "address": "location",
    "school": "institution",
}
_TO_BIBTEX_FIELDS: dict[str, str] = {
    "journaltitle": "journal",
    "location": "address",
}

# Legacy thesis types → ``@thesis`` plus the BibLaTeX ``type`` field value.
_TO_THESIS: dict[str, tuple[str, str]] = {
    "phdthesis": ("thesis", "phdthesis"),
    "mastersthesis": ("thesis", "mathesis"),
}
# ``@thesis`` ``type`` field value → legacy BibTeX entry type.
_FROM_THESIS: dict[str, str] = {
    "phdthesis": "phdthesis",
    "mathesis": "mastersthesis",
    "masterthesis": "mastersthesis",
    "mastersthesis": "mastersthesis",
}


@dataclass
class ConvertResult:
    """Auditable summary of a BibTeX/BibLaTeX dialect conversion.

    Counters describe the semantic transformations made in place; ``warnings``
    records fields deliberately left unchanged to avoid overwriting data.
    """

    target: str = ""
    entries: int = 0
    fields_renamed: int = 0
    types_changed: int = 0
    dates_changed: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def operations(self) -> dict[str, int]:
        """Return the per-domain conversion counts as a JSON-friendly dict."""
        return {
            "entries": self.entries,
            "fields_renamed": self.fields_renamed,
            "types_changed": self.types_changed,
            "dates_changed": self.dates_changed,
        }


def _rename_fields(entry: BibEntry, field_map: dict[str, str], result: ConvertResult) -> bool:
    """Rename fields per ``field_map``, never clobbering an existing target."""
    changed = False
    for old, new in field_map.items():
        if old not in entry.fields:
            continue
        if new in entry.fields:
            result.warnings.append(
                {
                    "type": "field_conflict",
                    "entry_key": entry.key,
                    "message": f"Both {old!r} and {new!r} present; left {old!r} untouched",
                }
            )
            continue
        if rename_entry_field(entry, old, new):
            result.fields_renamed += 1
            changed = True
    return changed


# --- BibTeX → BibLaTeX -----------------------------------------------------


def _to_thesis(entry: BibEntry, result: ConvertResult) -> bool:
    """Map a legacy thesis type to ``@thesis`` with a ``type`` field."""
    new_type, type_value = _TO_THESIS[entry.type.lower()]
    changed = set_entry_type(entry, new_type)
    if "type" not in entry.fields:
        changed = set_entry_field(entry, "type", type_value) or changed
    if changed:
        result.types_changed += 1
    return changed


def _combine_date(entry: BibEntry, result: ConvertResult) -> bool:
    """Fold ``year`` (+ ``month``) into a BibLaTeX ``date`` field.

    Only runs when no ``date`` is already present. A month that cannot be parsed
    leaves the entry untouched (with a warning) rather than risking data loss.
    """
    if "date" in entry.fields or "year" not in entry.fields:
        return False

    year = entry.fields["year"]
    month = entry.fields.get("month")
    mm = None
    if month is not None:
        mm = month_number_str(month)
        if mm is None:
            result.warnings.append(
                {
                    "type": "unparsed_month",
                    "entry_key": entry.key,
                    "message": f"Could not parse month {month!r}; left year/month untouched",
                }
            )
            return False

    new_date = f"{year}-{mm}" if mm else year
    # Rename keeps ``date`` in ``year``'s original position; then set its value.
    rename_entry_field(entry, "year", "date")
    set_entry_field(entry, "date", new_date)
    if month is not None:
        remove_entry_field(entry, "month")
    result.dates_changed += 1
    return True


def convert_to_biblatex(lib: BibFile) -> ConvertResult:
    """Convert a BibTeX library to BibLaTeX conventions in-place.

    Applies field renames (``journal`` → ``journaltitle``, ``address`` →
    ``location``, ``school`` → ``institution``), thesis type mappings
    (``@phdthesis``/``@mastersthesis`` → ``@thesis`` + ``type``), and folds
    ``year``/``month`` into an ISO ``date``. Unknown fields, groups, and
    comments are left untouched. Returns a :class:`ConvertResult`.
    """
    result = ConvertResult(target=TO_BIBLATEX)
    for entry in lib.entries.values():
        changed = False
        if entry.type.lower() in _TO_THESIS:
            changed = _to_thesis(entry, result) or changed
        changed = _rename_fields(entry, _TO_BIBLATEX_FIELDS, result) or changed
        changed = _combine_date(entry, result) or changed
        if changed:
            result.entries += 1
    return result


# --- BibLaTeX → BibTeX -----------------------------------------------------


def _revert_thesis(entry: BibEntry, result: ConvertResult) -> bool:
    """Map a ``@thesis`` back to ``@phdthesis``/``@mastersthesis`` via its ``type``.

    A ``@thesis`` whose ``type`` is missing or unrecognized is left as-is (BibTeX
    has no ``@thesis``) with a warning, rather than guessing.
    """
    type_value = entry.fields.get("type", "").strip().strip("{}").strip().lower()
    bibtex_type = _FROM_THESIS.get(type_value)
    if bibtex_type is None:
        result.warnings.append(
            {
                "type": "unmapped_thesis",
                "entry_key": entry.key,
                "message": f"@thesis with type {type_value or '(none)'!r} has no BibTeX equivalent; "
                "left as @thesis",
            }
        )
        return False

    set_entry_type(entry, bibtex_type)
    remove_entry_field(entry, "type")
    # In BibTeX, the awarding institution of a thesis is ``school``.
    if "institution" in entry.fields and "school" not in entry.fields:
        if rename_entry_field(entry, "institution", "school"):
            result.fields_renamed += 1
    result.types_changed += 1
    return True


def _split_date(entry: BibEntry, result: ConvertResult) -> bool:
    """Split a BibLaTeX ``date`` into ``year``/``month``/``day``, consuming the ``date`` field.

    Fills in ``year`` and ``month``/``day`` only where they are absent (never
    clobbering existing values), then drops the now-redundant ``date`` (BibTeX
    has no ``date`` field). A ``date`` that is not a plain ISO year/month/day
    (e.g. a range or literal) is left untouched with a warning.
    """
    if "date" not in entry.fields:
        return False

    raw_date = entry.fields["date"]
    match = _ISO_DATE_RE.match(raw_date.strip())
    if not match:
        result.warnings.append(
            {
                "type": "unparsed_date",
                "entry_key": entry.key,
                "message": f"Could not split date {raw_date!r}; left untouched",
            }
        )
        return False

    year, mm, day = match.group(1), match.group(2), match.group(3)
    if "year" not in entry.fields:
        # Rename keeps ``year`` in ``date``'s original position; then set value.
        rename_entry_field(entry, "date", "year")
        set_entry_field(entry, "year", year)
    else:
        remove_entry_field(entry, "date")
    if mm and "month" not in entry.fields:
        set_entry_field(entry, "month", _MONTH_NUM_TO_ABBR.get(mm, str(int(mm))))
    if day and "day" not in entry.fields:
        set_entry_field(entry, "day", str(int(day)))
    result.dates_changed += 1
    return True


def convert_to_bibtex(lib: BibFile) -> ConvertResult:
    """Convert a BibLaTeX library to BibTeX conventions in-place.

    Applies field renames (``journaltitle`` → ``journal``, ``location`` →
    ``address``), reverts ``@thesis`` to ``@phdthesis``/``@mastersthesis`` (with
    ``institution`` → ``school``), and splits an ISO ``date`` into
    ``year``/``month``. Unknown fields, groups, and comments are left untouched.
    Returns a :class:`ConvertResult`.
    """
    result = ConvertResult(target=TO_BIBTEX)
    for entry in lib.entries.values():
        changed = False
        if entry.type.lower() == "thesis":
            changed = _revert_thesis(entry, result) or changed
        changed = _rename_fields(entry, _TO_BIBTEX_FIELDS, result) or changed
        changed = _split_date(entry, result) or changed
        if changed:
            result.entries += 1
    return result


def convert(lib: BibFile, target: str) -> ConvertResult:
    """Convert ``lib`` in-place to ``target`` (``"biblatex"`` or ``"bibtex"``)."""
    normalized = target.lower()
    if normalized == TO_BIBLATEX:
        return convert_to_biblatex(lib)
    if normalized == TO_BIBTEX:
        return convert_to_bibtex(lib)
    raise ValueError(
        f"Unsupported conversion target {target!r}; expected one of: {', '.join(TARGETS)}"
    )
