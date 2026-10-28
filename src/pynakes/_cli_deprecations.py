"""Old CLI forms in their deprecation period, for ``capabilities``.

Each still works, warns with ``{"type": "deprecated", ...}``, and goes away in
the named release. The list is empty once nothing is being retired.
"""

DEPRECATIONS: list[dict] = [
    {
        "command": "fields encode",
        "old": "fields encode",
        "new": "normalize --encoding latex|unicode --encoding-field FIELD",
        "removal": "0.10.0",
        "note": "normalize owns value conventions and fields only edits fields. The "
        "encoding step reads normalize-encoding, not fields-encoding, and converts the "
        "prose fields unless --encoding-field or normalize-encoding-fields names others.",
    },
    {
        "command": "fields protect-title",
        "old": "fields protect-title",
        "new": "normalize --only titles --title-protection on",
        "removal": "0.10.0",
        "note": "normalize's titles step already brace-protects title words, with "
        "--title-field, --term, --key and --where.",
    },
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
