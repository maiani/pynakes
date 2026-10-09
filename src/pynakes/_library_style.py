"""Give a new entry the style its library declares, so a clean file stays clean.

An entry built from provider metadata knows nothing of the library it joins:
it arrives with full journal names in a library that abbreviates them, or
compact ``=`` in a library aligned on it, and ``lint`` flags it at once. This
applies the library's *declared* settings to that one entry — the ``normalize-*``
keys and JabRef saveActions for content, the ``format-*`` keys for layout. A
library that declares nothing gets the entry exactly as the provider described
it, and no other entry is touched.
"""

import copy

from pynakes import normalize as normalize_ops
from pynakes._normalize_steps import STEPS
from pynakes.canonical import format_selected_entries, layout_from_metadata
from pynakes.metadata import metadata_value
from pynakes.metadata.jabref import library_save_actions
from pynakes.metadata.schema import CATEGORY_FORMATTING, PYNAKES_EXACT_KEYS
from pynakes.model import BibEntry, BibFile, EntryStore

#: The ``normalize-*`` key that declares each per-entry step. Key regeneration
#: is left out: whoever adds an entry names its key or has one generated.
_STEP_KEYS = {
    "drop_fields": "normalize-drop-fields",
    "titles": "normalize-protect-titles",
    "authors": "normalize-author-style",
    "dois": "normalize-dois",
    "pages": "normalize-pages",
    "journals": "normalize-journal-style",
    "identifier_case": "normalize-identifier-case",
}

#: JabRef saveActions formatters that stand in for a pynakes step.
_SAVE_ACTION_STEPS = {"normalize_names": "authors", "clean_up_doi": "dois"}


def declared_steps(lib: BibFile) -> list[str]:
    """Return the per-entry normalize steps ``lib`` configures, in run order."""
    declared = {step for step, key in _STEP_KEYS.items() if metadata_value(lib, key) is not None}
    save_actions = library_save_actions(lib)
    if save_actions is not None and save_actions.enabled:
        declared.add("save_actions")
        declared.update(
            step for action, step in _SAVE_ACTION_STEPS.items() if save_actions.has(action)
        )
    return [step for step in STEPS if step in declared]


def declares_layout(lib: BibFile) -> bool:
    """Return whether ``lib`` sets any ``format-*`` layout key."""
    return any(
        metadata_value(lib, key) is not None
        for key, category in PYNAKES_EXACT_KEYS.items()
        if category == CATEGORY_FORMATTING
    )


def apply_library_style(lib: BibFile, entry: BibEntry) -> list[str]:
    """Normalize and lay out ``entry`` as ``lib`` declares; return the steps applied.

    ``entry`` is one ``lib`` does not hold yet, or has only just been given.
    ``"layout"`` in the result means the ``format-*`` settings were applied.
    """
    view = copy.copy(lib)
    view.entries = EntryStore([entry])
    steps = declared_steps(lib)
    if steps:
        normalize_ops.normalize_library(view, normalize_ops.NormalizeOptions(only=steps))
    if declares_layout(lib):
        format_selected_entries(view, layout_from_metadata(lib))
        # The laid-out text is now the entry's source; the writer emits it as is.
        entry.modified = False
        steps.append("layout")
    return steps
