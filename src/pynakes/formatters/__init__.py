"""BibTeX field formatters with JabRef-compatible behavior.

These mirror JabRef's ``saveActions`` field formatters so a JabRef-configured
library normalizes the same way under pynakes (a 1.0 feature-parity goal). Each
formatter is a pure ``str -> str`` transform and keeps the input unchanged when
it does not recognize the value — matching JabRef's "keep if it doesn't match"
behavior.

Algorithms are derived from JabRef (MIT License),
``jablib/src/main/java/org/jabref/logic/formatter/bibtexfields/``:
``NormalizeDateFormatter``, ``NormalizeMonthFormatter``,
``NormalizePagesFormatter``, ``LatexCleanupFormatter``, and
``HtmlToLatexFormatter`` / ``HtmlToUnicodeFormatter``. Parity is asserted
in ``tests/test_jabref_parity.py`` against vectors lifted from JabRef's own
tests.
"""

from pynakes._calendar import MONTH_NUM_TO_ABBR as _MONTH_NUM_TO_ABBR
from pynakes.formatters._case import (
    capitalize,
    lower_case,
    sentence_case,
    title_case,
    upper_case,
)
from pynakes.formatters._date import (
    _ISO_DATE_RE,
    month_number_str,
    normalize_date,
    normalize_month,
)
from pynakes.formatters._extra import (
    clean_up_doi,
    cleanup_url,
    clear,
    escape_ampersands,
    escape_underscores,
    minify_name_list,
    remove_braces,
    unprotect_terms,
)
from pynakes.formatters._latex import (
    html_to_latex,
    html_to_unicode,
    latex_cleanup,
    latex_to_plain_text,
    latex_to_unicode,
    unicode_to_latex,
)
from pynakes.formatters._pages import first_page, last_page, normalize_page_numbers, page_prefix
from pynakes.formatters._registry import FIELD_FORMATTERS, FormattersRegistry
from pynakes.formatters._units import ordinals_to_superscript, units_to_latex

__all__ = [
    # case
    "capitalize",
    "lower_case",
    "sentence_case",
    "title_case",
    "upper_case",
    # date
    "_ISO_DATE_RE",
    "_MONTH_NUM_TO_ABBR",
    "month_number_str",
    "normalize_date",
    "normalize_month",
    # extra
    "cleanup_url",
    "clear",
    "clean_up_doi",
    "escape_ampersands",
    "escape_underscores",
    "minify_name_list",
    "remove_braces",
    "unprotect_terms",
    # latex / html
    "html_to_latex",
    "html_to_unicode",
    "latex_cleanup",
    "latex_to_plain_text",
    "latex_to_unicode",
    "unicode_to_latex",
    # pages
    "first_page",
    "last_page",
    "normalize_page_numbers",
    "page_prefix",
    # registry
    "FIELD_FORMATTERS",
    "FormattersRegistry",
    # units
    "ordinals_to_superscript",
    "units_to_latex",
]
