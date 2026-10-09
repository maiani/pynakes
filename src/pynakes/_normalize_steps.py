"""The steps ``normalize`` runs, and how a run is narrowed to some of them.

``--only`` names steps from :data:`STEPS`; a ``--key``/``--where`` selection
runs the per-entry steps against :func:`entry_view` and leaves out the
whole-file ones. Both reasons a step did not run are recorded in a report's
``skipped`` under the fixed wording below, so a caller can tell them apart from
a step the library's own settings turned off.
"""

import copy
from collections.abc import Collection

from pynakes.model import BibFile, EntryStore

#: ``skipped`` reason for a step ``--only`` left out.
NOT_IN_ONLY = "not selected by --only"
#: ``skipped`` reason for a whole-file step under a selection of entries.
WHOLE_FILE = "acts on the whole file, so it does not run on a selection of entries"

#: Every step, in the order normalize runs them: the names ``--only`` accepts
#: (CLI spelling uses hyphens) and the keys of a report's ``skipped``.
STEPS: tuple[str, ...] = (
    "metadata",
    "drop_fields",
    "titles",
    "authors",
    "dois",
    "pages",
    "journals",
    "save_actions",
    "months",
    "identifier_case",
    "sort",
    "keys",
)

#: Steps that act on the file as a whole rather than on its entries one by one:
#: adopting and consolidating metadata, and sorting. A selection of entries
#: cannot run them.
WHOLE_FILE_STEPS = frozenset({"metadata", "sort"})


def step_name(value: str) -> str:
    """Return the step a CLI-spelled name refers to, or raise ``ValueError``."""
    name = value.strip().lower().replace("-", "_")
    if name not in STEPS:
        choices = ", ".join(step.replace("_", "-") for step in STEPS)
        raise ValueError(f"Unknown normalize step {value!r}; choose from {choices}")
    return name


def entry_view(lib: BibFile, keys: Collection[str]) -> BibFile:
    """Return ``lib`` restricted to the entries named in ``keys``.

    A shallow copy: settings, strings, and metadata are shared, and so are the
    entries themselves, so every in-place edit a step makes lands in ``lib``.
    Only the entry store differs, which is what every per-entry step iterates.
    """
    view = copy.copy(lib)
    view.entries = EntryStore([entry for entry in lib.entries.values() if entry.key in keys])
    return view
