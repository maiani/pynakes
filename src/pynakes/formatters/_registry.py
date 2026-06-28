"""FormattersRegistry class and FIELD_FORMATTERS dispatch table."""

from collections.abc import Callable

from pynakes.formatters._case import (
    capitalize,
    lower_case,
    sentence_case,
    title_case,
    upper_case,
)
from pynakes.formatters._date import normalize_date, normalize_month
from pynakes.formatters._latex import (
    html_to_latex,
    html_to_unicode,
    latex_cleanup,
    latex_to_unicode,
    unicode_to_latex,
)
from pynakes.formatters._pages import normalize_page_numbers
from pynakes.formatters._units import ordinals_to_superscript, units_to_latex

# JabRef saveActions formatter key -> pynakes formatter. Author-name
# normalization (``normalize_names``) is handled via the author-style path and
# DOI cleanup via the DOI normalizer, so they are intentionally absent here.
FIELD_FORMATTERS: dict[str, Callable[[str], str]] = {
    "capitalize": capitalize,
    "html_to_latex": html_to_latex,
    "html_to_unicode": html_to_unicode,
    "latex_cleanup": latex_cleanup,
    "latex_to_unicode": latex_to_unicode,
    "lower_case": lower_case,
    "normalize_date": normalize_date,
    "normalize_month": normalize_month,
    "normalize_page_numbers": normalize_page_numbers,
    "ordinals_to_superscript": ordinals_to_superscript,
    "sentence_case": sentence_case,
    "title_case": title_case,
    "unicode_to_latex": unicode_to_latex,
    "upper_case": upper_case,
    "units_to_latex": units_to_latex,
}


class FormattersRegistry:
    """Registry mapping formatter names to callable transforms.

    Wraps ``FIELD_FORMATTERS`` for programmatic lookup and extension.
    """

    def __init__(self, formatters: dict[str, Callable[[str], str]] | None = None) -> None:
        self._formatters: dict[str, Callable[[str], str]] = (
            dict(FIELD_FORMATTERS) if formatters is None else formatters
        )

    def get(self, name: str) -> Callable[[str], str] | None:
        """Return the formatter for *name*, or ``None`` if not registered."""
        return self._formatters.get(name)

    def register(self, name: str, fn: Callable[[str], str]) -> None:
        """Add or replace a formatter by *name*."""
        self._formatters[name] = fn

    def names(self) -> list[str]:
        """Return all registered formatter names in sorted order."""
        return sorted(self._formatters)

    def __contains__(self, name: object) -> bool:
        return name in self._formatters
