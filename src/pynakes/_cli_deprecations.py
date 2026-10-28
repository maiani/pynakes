"""Old CLI forms in their deprecation period, for ``capabilities``.

Each still works, warns with ``{"type": "deprecated", ...}``, and goes away in
the named release. The list is empty once nothing is being retired.
"""

DEPRECATIONS: list[dict] = [
    *(
        {
            "command": f"groups {old}",
            "old": f"groups {old}",
            "new": new,
            "removal": "0.10.0",
            "note": "groups subcommands are named for what they do to a group, without "
            "repeating the group name; the old form keeps its action until it is removed.",
        }
        for old, new in (
            ("tree", "groups list"),
            ("list-entries", "groups show"),
            ("add-entry", "groups assign"),
            ("remove-entry", "groups unassign"),
            ("add-group", "groups add"),
            ("remove-group", "groups remove"),
            ("rename-group", "groups rename"),
            ("move-group", "groups update --parent"),
            ("update-group", "groups update"),
        )
    ),
    *(
        {
            "command": f"corpus {name}",
            "old": f"corpus {name}",
            "new": name,
            "removal": "0.10.0",
            "note": "The corpus group is retired: combine and split work on plain .bib "
            "files and batch on one, so all three are top-level commands. The old form "
            f"keeps its corpus_{name} action until it is removed.",
        }
        for name in ("combine", "split", "batch")
    ),
    {
        "command": "ref find",
        "old": "ref find",
        "new": "ref lookup",
        "removal": "0.10.0",
        "note": "search reads the library; ref lookup asks an outside index, and the "
        "new name says so. ref find's --online flag was already ignored: a command "
        "that exists to make a network request goes online by being run.",
    },
]
