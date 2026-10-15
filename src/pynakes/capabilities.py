"""Machine-readable description of what pynakes can do.

Kept in sync with the actually-implemented CLI commands so agents can introspect
the tool rather than guessing. Update this when commands are added or removed.
"""

import pynakes
from pynakes import __all__ as PUBLIC_API_EXPORTS
from pynakes.analysis import SECTIONS as ANALYSIS_SECTIONS
from pynakes.cli_errors import catalogue_description
from pynakes.entry_reader import INCLUDE_PARTS
from pynakes.metadata.schema import SAVED_QUERY_PREFIX
from pynakes.query import FUZZY_THRESHOLD, WHERE_GRAMMAR

# Stable type vocabulary for command-schema introspection. The on-disk click
# type names are mapped to this small, version-independent set so the pinned
# `capabilities` schema does not change shape when Typer/click internals do.
_TYPE_VOCABULARY = {
    "text": "string",
    "str": "string",
    "boolean": "boolean",
    "integer": "integer",
    # An option with min/max bounds: ``integer range`` up to click 8.1,
    # ``int range`` after it.
    "integer range": "integer",
    # Click's current names.
    "int": "integer",
    "int range": "integer",
    "float": "number",
    "float range": "number",
    "path": "path",
    "filename": "path",
    "file": "path",
    "choice": "choice",
}

# One transversal selector surface: the same grammar for every command that
# addresses a set of entries. Described by `pynakes.query`, so the capability
# description cannot drift from the parser.
_PREDICATE_GRAMMAR = {
    "key_selector": (
        "--key selects by citation key without the expression grammar: "
        "comma-separated, repeatable, equivalent to --where 'key in [...]'. "
        "Every command taking --where takes it, and giving both narrows (they "
        "are ANDed). On ref add and ref import, which create an entry rather "
        "than select one, --key names the key to assign."
    ),
    "bucket_predicates_used_by": ["corpus split (--route)"],
    **WHERE_GRAMMAR,
}

_SEARCH_QUERY_GRAMMAR = {
    "terms": "Whitespace-separated terms are ANDed.",
    "phrases": "Quoted phrases stay together.",
    "field_prefix": "field:term scopes a term to one field; key: and type: are special fields.",
    "search_in": "--in FIELDS scopes every unprefixed term to those stored fields "
    "(key and type stay searchable). It does not change what a match returns; "
    "--select does that.",
    "examples": [
        "learning",
        '"natural language"',
        "title:learning type:article",
        'author:"Jane Example"',
    ],
    "matched_fields": (
        "Each result reports the field(s) it matched: key, type, or any stored "
        "field name (title, author, groups, abstract, ...)."
    ),
    "match_explanations": (
        "Each result also reports one entry per hit in `matches`: field, term, "
        "kind (exact|fuzzy), score, and the matching excerpt; `score` on the "
        "result is the weakest term score."
    ),
    "fuzzy": (
        f"--fuzzy also matches near-misses by normalized similarity >= "
        f"{FUZZY_THRESHOLD} (misspellings, inflections). `--where 'title ~ \"…\"'` "
        f"applies the same similarity as a selector."
    ),
    "selection": (
        "--where narrows which entries are searched using the shared predicate "
        "grammar, covering date ranges (year >= 2020) and missing-field "
        "questions (abstract missing) without command-specific flags. An empty "
        "query selects by predicate alone: search \"\" --where 'doi missing' is "
        "the read-only path for the selector grammar, returning matches in file "
        "order with no matched fields. An empty query without --where is "
        "rejected rather than matching the whole library."
    ),
    "ranking": (
        "Results are ranked by relevance by default: key > title > author > "
        "other fields > groups/abstract, then by match score, ties kept in file "
        "order. --no-rank restores plain file order."
    ),
}


# Old forms that still work, warn with {"type": "deprecated", ...}, and go away
# in the named release. Empty once nothing is being retired.
_DEPRECATIONS = [
    {
        "command": "keys check",
        "old": "keys check",
        "new": "lint --only duplicate_key",
        "removal": "0.9.0",
        "note": "lint reports the same duplicate_key findings, with every entry's position "
        "under instances, and gates them with --strict. Unlike keys check, lint honours "
        "the library's lint-ignore setting.",
    },
    *(
        {
            "command": "tex scan",
            "old": flag,
            "new": replacement,
            "removal": "0.9.0",
            "note": "used works in every --where, so the commands that export and tag "
            "select the cited entries themselves; tex scan only reports. For a public "
            "copy of the cited entries, scrub FILE --where used --out OUT.",
        }
        for flag, replacement in (
            ("--out", "corpus combine FILE --where used --out OUT"),
            ("--group", "fields append FILE groups NAME --where used"),
            ("--keyword", "fields append FILE keywords WORD --where used"),
        )
    ),
    {
        "command": "normalize",
        "old": "--sort-by",
        "new": "format --entry-order SPEC (or profile)",
        "removal": "0.9.0",
        "note": "Sorting by the library's sort-order or saveOrderConfig leaves normalize "
        "too, with the same warning. Entry order is layout, which format owns. "
        "format --entry-order takes "
        "preserve, key, profile (sort-order, else JabRef's saveOrderConfig), or a sort "
        "spec such as author,year:desc. format also rewrites each entry's layout.",
    },
    {
        "command": "search",
        "old": "--in-field",
        "new": "--in and --select",
        "removal": "0.9.0",
        "note": "--in-field restricted both the fields searched and the fields "
        "returned; --in chooses the first and --select the second.",
    },
]

# The bounded-read contract shared by every multi-entry read.
_BOUNDED_READS = {
    "commands": ["ref show (--key, --where)", "search"],
    "options": {
        "--limit N": "at most N entries per page; --limit 0 reports only page.total",
        "--cursor TOKEN": "resume with page.next_cursor from the previous page",
        "--max-chars N": "cut every returned text value to N characters",
        "--select FIELDS": "return only these stored fields (abstract included): "
        "under 'fields' in place of 'summary' on ref show, as each "
        "match's 'fields' on search",
        "--include PARTS": "ref show: add what the library records "
        "outside the entry's fields, each part under its own key",
    },
    "page": {
        "keys": ["offset", "limit", "returned", "total", "complete", "next_cursor"],
        "order": "Deterministic for a snapshot: requested key order for ref show --key, "
        "file order for ref show --where, ranked or file order for search.",
        "snapshot": "A cursor carries a digest of the library it was issued for and of "
        "the selection. Against a changed library it is refused with the StaleCursor "
        "conflict (exit 2); against another selection, with InvalidInput.",
    },
    "missing_vs_omitted": {
        "missing": "The library has no value: a selected field is null and listed in "
        "missing_fields; an included part with nothing recorded is listed in missing.",
        "omitted": "A value exists but was left out: stored fields outside --select are "
        "listed in omitted_fields; values cut by --max-chars are listed in truncated "
        "with their full and returned lengths.",
        "unread": "Entries beyond this page: page.complete is false and "
        "page.next_cursor reads them.",
    },
    "include": {
        "parts": list(INCLUDE_PARTS),
        "materials": "Pinax materials present for the key (pinax.configured is false "
        "without pinax-files-dir) and BibLaTeX file links with their status.",
        "provenance": "The Pinax manifest record for each material (source, dates, "
        "access, checksum) and the per-entry directives with their reasons.",
    },
    "retrieve_full": "When a page truncated any value, retrieve_full names the keys "
    "to re-read without --max-chars.",
    "limits_count": "characters of stored text; never model-dependent tokens",
    "offline": True,
}

# Collecting PDFs for a bibliography, end to end, with what each step reports.
_MATERIAL_COLLECTION = {
    "fetch": "asset fetch --material best-pdf [--access institutional] [--discover] "
    "[--progress jsonl] --json",
    "completeness": "summary counts operations; coverage answers the collection question: "
    "entries, with_pdf, without_pdf, missing (key, materials, reason) and complete. "
    "The envelope's complete is false while a requested PDF is missing or a download failed.",
    "progress": "--progress jsonl writes one JSON event per line on stderr (entry, "
    "artifact_start, artifact_done, artifact_skip, skip, fail, retry with retry_in and "
    "attempt); stdout keeps the final envelope, also with --json.",
    "attempts": "Every request is recorded: stage resolve (DOI landing page, open-access "
    "index; lookup and error name it) or download, with url, final_url, status, "
    "content_type, outcome and retryable. Credentials are never recorded.",
    "classification": "A PDF served by a preprint repository (arXiv) is stored as "
    "preprint_pdf, never published_pdf; an arXiv DOI (10.48550/arXiv.*) is read as the "
    "arXiv id it encodes. asset check reports misclassified files with their evidence "
    "(source_host, arxiv_doi, pdf_arxiv_stamp); asset repair --reclassify moves them.",
    "discovery": "--discover looks up a missing arXiv id by DOI when a preprint is needed "
    "and checks it against arXiv's record: linked (used; eprint written only when absent), "
    "ambiguous (reported, not used), not_found, or not_checked (with retryable).",
    "resume": "Each material is recorded in the Pinax manifest as it lands; rerunning the "
    "same command fetches only what is still missing.",
    "reviewed_enrichment": "enrich --online --dry-run, then the same command with "
    "--only-field NAMES --expect-sha256 <source_sha256> applies only the reviewed fields. "
    "lookups.not_checked names entries whose lookup failed (never read as no match), "
    "lookups.retry the arguments that rerun the retryable ones.",
    "transfer": "corpus combine project.bib scratch.bib --out project.bib --force keeps the "
    "project's pinax-files-dir and copies the scratch materials; --dry-run lists them "
    "under pinax_materials.",
    "compact_reads": "lint --summary / --severity; ref show --key K --select FIELDS "
    "(abstracts only when selected); asset check coverage.",
}
_SAVED_QUERIES = {
    "storage": f"One pynakes-meta line per query: {SAVED_QUERY_PREFIX}NAME: EXPRESSION",
    "grammar": "The shared --where predicate grammar (see predicate_grammar).",
    "name": "Letters, digits, '_', '.', '-', starting with a letter or digit; "
    "compared case-insensitively.",
    "commands": ["query list", "query set", "query remove"],
    "running": 'A saved query is the --where predicate query "NAME", so every '
    "command that selects entries runs it and can narrow it further: "
    "ref show --where 'query \"NAME\"' reads its matches under the bounded-read "
    "contract. A saved expression may refer to other saved queries; a missing or "
    "circular reference is an InvalidInput error.",
    "results": "The library stores the query, never its result: it is evaluated "
    "against the entries as they are now, in file order.",
    "citations": "used/unused resolve against the library's tex-sources wherever "
    "--where is evaluated (NoSources when none are linked).",
    "validation": "query set and metadata set validate the expression; lint reports "
    "a stored query that no longer parses (invalid_metadata_value).",
}

_ANALYSIS = {
    "command": "analyze",
    "module": "pynakes.analysis",
    "sections": list(ANALYSIS_SECTIONS),
    "descriptive_only": True,
    "reconciles": {
        "lint": "Equals lint's summary for the library (after lint-ignore and ignore directives).",
        "entries": "total counts physical entries, duplicate citation keys included; "
        "each per-entry section counts every entry once.",
    },
    "frequency_lists": "authors.top and venues.top are capped by --top, most "
    "frequent first, ties alphabetical; distinct always counts every value.",
    "offline": True,
}

# Single source of truth for how commands are grouped by nature, shared by the
# CLI ``--help`` panels (``cli.py`` reads this for ``rich_help_panel``) and the
# ``command_groups`` field of the capability description. Ordered: panels render
# in this order, and the commands within each panel in this order. Every
# top-level command/group must appear in exactly one panel — guarded by tests.
COMMAND_GROUPS: dict[str, list[str]] = {
    "Inspect & validate": [
        "inspect",
        "search",
        "query",
        "analyze",
        "lint",
        "verify",
        "capabilities",
    ],
    "Edit references": [
        "ref",
        "format",
        "normalize",
        "convert",
        "enrich",
        "dedupe",
        "fields",
        "keys",
        "groups",
        "metadata",
        "tex",
    ],
    "Materials (pinax)": ["asset"],
    "Corpus (multiple files)": ["corpus"],
    "Create": ["init", "scrub"],
}


def _stable_type(param) -> str:
    """Map a click parameter's type to the stable vocabulary, marking lists."""
    if getattr(param, "is_flag", False):
        return "boolean"
    raw = (getattr(param.type, "name", "") or "").lower()
    base = _TYPE_VOCABULARY.get(raw, "string")
    is_list = bool(getattr(param, "multiple", False)) or getattr(param, "nargs", 1) == -1
    return f"list[{base}]" if is_list else base


def _plain_help(text: str) -> str:
    """Strip Rich console-markup escapes from help text.

    Help strings escape ``[`` so Typer's Rich renderer prints literal brackets
    (``in \\[a, b]``). The capability description is data, not a rendered
    console line, so it reports the text as a reader would type it.
    """
    return text.replace("\\[", "[").replace("``", "`")


def _param_schema(param) -> dict:
    """Describe one click argument or option as a JSON-friendly dict."""
    entry: dict[str, object] = {
        "name": param.name,
        "type": _stable_type(param),
        "required": bool(param.required),
    }
    help_text = _plain_help((getattr(param, "help", "") or "").strip())
    if help_text:
        entry["help"] = help_text
    if getattr(param.type, "name", "") == "choice":
        entry["choices"] = list(param.type.choices)
    if param.param_type_name == "argument":
        entry["arg"] = True
        if getattr(param, "nargs", 1) == -1:
            entry["variadic"] = True
    else:
        # Every spelling, including the negative half of a flag pair
        # (``--no-blank-lines``) and short forms (``-f``).
        entry["flags"] = [*param.opts, *getattr(param, "secondary_opts", [])]
        default = param.default
        if isinstance(default, (str, int, float, bool)) or default is None:
            entry["default"] = default
    return entry


def _command_schema(command) -> dict:
    """Describe one click command: its help, arguments, and options."""
    help_text = _plain_help((command.help or command.short_help or "").strip()).splitlines()
    arguments = [_param_schema(p) for p in command.params if p.param_type_name == "argument"]
    options = [_param_schema(p) for p in command.params if p.param_type_name == "option"]
    return {
        "help": help_text[0] if help_text else "",
        "stability": "stable",
        "arguments": arguments,
        "options": options,
    }


def _walk_commands(group, prefix: str, out: dict) -> None:
    # A subcommand group exposes a ``commands`` mapping; a leaf command does not.
    # (Checked structurally rather than by isinstance, since Typer vendors its
    # own click fork whose Group is not the public ``click.Group``.)
    for name, command in sorted(group.commands.items()):
        full = f"{prefix}{name}"
        if hasattr(command, "commands"):
            _walk_commands(command, f"{full} ", out)
        else:
            out[full] = _command_schema(command)


def command_schemas() -> dict:
    """Introspect the live CLI into a per-command schema map.

    Derived from the actual Typer/click application, so it can never drift from
    the real command surface. Each entry (keyed by full command path, e.g.
    ``"groups add-entry"``) lists the command's help, positional ``arguments``,
    and ``options`` with stable type names, flags, defaults, and choices.
    """
    import typer.main

    # Imported first: pynakes.cli wires the shared --file option into
    # typer.main.get_command, which must be looked up after that patch.
    from pynakes.cli import app

    schemas: dict = {}
    _walk_commands(typer.main.get_command(app), "", schemas)
    return schemas


def _write_precondition(schemas: dict) -> dict:
    """Describe ``--expect-sha256``, listing the commands that accept it."""
    return {
        "option": "--expect-sha256",
        "envelope_key": "source_sha256",
        "conflict": "ExternalModification",
        "description": (
            "Every envelope reports source_sha256, the digest of the library it read. "
            "Every modifying command accepts it back as --expect-sha256: if the file "
            "changed in between, the command exits 2 and writes nothing."
        ),
        "commands": sorted(
            name
            for name, schema in schemas.items()
            if any("--expect-sha256" in option.get("flags", []) for option in schema["options"])
        ),
    }


def _selector_surfaces(schemas: dict[str, dict]) -> list[str]:
    """Every place the predicate grammar is accepted, read from the live commands.

    Derived rather than listed, so a command that grows ``--where`` cannot be
    missing from it.
    """
    selecting = sorted(
        name
        for name, schema in schemas.items()
        if "--where" in {flag for option in schema["options"] for flag in option["flags"]}
    )
    return [
        *(f"{name} (--where, --key)" for name in selecting),
        "query set (saved expressions, run as --where 'query \"NAME\"')",
        "corpus split (--route)",
        "batch (fields.* where)",
    ]


def get_capabilities() -> dict:
    """Return a structured description of supported operations and commands."""
    schemas = command_schemas()
    return {
        "tool": "pynakes",
        "version": pynakes.__version__,
        "description": (
            "Reference management engine for BibTeX and BibLaTeX bibliographies and "
            "their research materials: curation, citation tracking, and optional "
            "material management, with "
            "reviewable edits, structured JSON, and JabRef interoperability."
        ),
        "network_access_is_explicit": True,
        "supports_dry_run": True,
        "supports_json_output": True,
        "supports_backup": True,
        "supports_atomic_write": True,
        "supports_multiple_files": True,
        "write_precondition": _write_precondition(schemas),
        "python_api": {
            "stability": "experimental",
            "facade": "pynakes.Bibliography",
            "public_exports": list(PUBLIC_API_EXPORTS),
            "constructors": [
                "Bibliography.open",
                "Bibliography.from_text",
                "Bibliography.from_bibfile",
            ],
            "review": ["preview", "diff", "change_plan", "lint"],
            "persistence": ["commit", "reset", "reload", "externally_changed"],
            "transport_independent": True,
        },
        # Two structurally identical metadata comment namespaces are read and
        # merged (pynakes-meta overrides jabref-meta). `metadata set` routes a
        # JabRef-native key to jabref-meta only when the file is already
        # JabRef-tracked (carries jabref-meta); otherwise it, like every
        # pynakes-owned key, stays in pynakes-meta. `metadata adopt-jabref`
        # establishes tracking so JabRef-native keys are mirrored from then on.
        "metadata_namespaces": ["jabref-meta", "pynakes-meta"],
        "exit_codes": {
            "0": "success",
            "1": "error (usage, parse, validation, I/O)",
            "2": "conflict (operation blocked; options returned)",
        },
        "positional_convention": {
            "library_first": (
                "Every command that reads one library takes it as the leading FILE "
                "argument, or as --file/-f, or not at all when the working directory "
                "holds exactly one .bib file."
            ),
            "library_detection": (
                "The leading positional is the library when it ends in .bib, or when "
                "the positionals fill every argument the command has; otherwise the "
                "lone local .bib is used. A .bib-looking token in any other argument "
                "is refused as a usage error."
            ),
        },
        # Commands with a --strict gate (exit 1, envelope still emitted in
        # full). The read-only checks accept one or more .bib files: a single
        # file keeps the per-file envelope; multiple files emit an aggregate
        # {status, action, strict, files, summary} envelope. `asset fetch
        # --strict` gates completeness: exit 1 when a requested material
        # failed or was unavailable.
        "gate_commands": [
            "lint",
            "verify",
            "keys check",
            "asset check",
            "dedupe check",
            "asset fetch",
        ],
        "capabilities": [
            "parse_bibtex",
            "create_library",
            "inspect_library",
            "inspect_insights",
            "lint",
            "entry_directives",
            "manage_groups",
            "manage_group_tree",
            "manage_fields",
            "protect_title_capitalization",
            "generate_keys",
            "rename_citation_keys",
            "detect_duplicate_keys",
            "repair_duplicate_keys",
            "detect_duplicate_works",
            "compare_work_evidence",
            "merge_duplicate_works",
            "verify_references",
            "check_published_preprints",
            "backfill_arxiv_ids",
            "enrich_metadata",
            "compare_entry_with_remote",
            "compare_entries",
            "normalize_library",
            "format_bibliography",
            "convert_to_biblatex",
            "convert_to_bibtex",
            "export_csl_json",
            "export_ris",
            "export_mods",
            "export_endnote",
            "export_csv",
            "import_csl_json",
            "import_ris",
            "import_mods",
            "import_endnote",
            "normalize_journals",
            "normalize_authors",
            "normalize_dois",
            "normalize_pages",
            "import_reference",
            "search_library",
            "bounded_reads",
            "include_materials_and_provenance",
            "material_collection_coverage",
            "fetch_progress_stream",
            "discover_arxiv_ids",
            "reclassify_materials",
            "enrich_selected_fields",
            "saved_queries",
            "analyze_library",
            "detect_used_citations",
            "remove_entries",
            "combine_libraries",
            "scrub_private_content",
            "partition_library",
            "inspect_metadata",
            "update_metadata",
            "validate_linked_files",
            "pinax_filestore",
            "pinax_arxiv_download_core",
            "pinax_fetch",
            "pinax_agent_surface",
            "pinax_manifest",
            "pinax_setops",
            "pinax_key_edits",
        ],
        # Commands grouped by nature (single source of truth shared with the CLI
        # ``--help`` panels). Mirrors the flat ``commands`` map below.
        "command_groups": {panel: list(names) for panel, names in COMMAND_GROUPS.items()},
        "commands": {
            "init": "Create a new .bib library, optionally seeded with a metadata profile (--pinax for pinax mode)",
            "inspect": "Inspect a .bib file structure",
            "lint": "Validate entries and report issues",
            "ref": "Create, show, edit, compare, find, import, and remove individual "
            "references, and set per-entry directives "
            "(add, show, edit, directive, compare, find, import, remove)",
            "groups": "Manage entry groups and group hierarchy "
            "(list, list-entries, add-entry, remove-entry, tree, add-group, "
            "remove-group, rename-group, move-group, update-group)",
            "keys": "Generate, rename, repair citation keys, and look up "
            "raw-TeX-source citations of one key (usage); check is deprecated",
            "fields": "Bulk-edit fields across matching references "
            "(set, rename, move, append, clear, protect-title)",
            "dedupe": "Detect and conservatively merge duplicate works",
            "verify": "Verify entries against authoritative metadata "
            "(--published also reports published/preprint identity links)",
            "enrich": "Conservatively fill missing metadata "
            "(--published also promotes preprints and backfills arXiv ids)",
            "tex": "Manage linked TeX sources and scan them for citations "
            "(list, add, remove, clear, scan)",
            "metadata": "Inspect and update top-level library metadata "
            "(list, set, remove, adopt-jabref)",
            "normalize": "Normalize entries (titles, authors, journals, DOIs, "
            "identifier case, keys) per the library's configured settings",
            "format": "Lint, then rewrite bibliography layout with portable profile settings "
            "and explicit policy overrides",
            "convert": "Convert between BibTeX/BibLaTeX dialects and interchange "
            "formats (export/import CSL-JSON, RIS, MODS, EndNote, and export CSV)",
            "search": "Search entries by free text, phrases, or field-scoped terms",
            "query": "Save, list, remove, and run named selector queries (list, set, remove, run)",
            "analyze": "Describe a bibliography with offline counts: types, years, "
            "authors, venues, identifier and field coverage, groups, lint, materials",
            "scrub": "Write a public copy with private content removed — private "
            "entry fields, metadata blocks, and free comments (--check gates instead "
            "of writing)",
            "asset": "Fetch and validate Pinax materials — arXiv PDF/source, "
            "open or institutionally entitled published/supplement PDF download, "
            "linked-file checks, and manifest repair (fetch, check, repair)",
            "corpus": "Operate across multiple .bib files (combine, split, batch)",
            "capabilities": "Show this capability description",
        },
        # Self-description for agents: the full per-command schema (args/options/
        # types) derived from the live CLI, the enumerated error/conflict codes,
        # and the one selector grammar shared by every entry-addressable command.
        "command_schemas": schemas,
        "error_codes": catalogue_description(),
        "predicate_grammar": {"used_by": _selector_surfaces(schemas), **_PREDICATE_GRAMMAR},
        "search_query_grammar": _SEARCH_QUERY_GRAMMAR,
        "bounded_reads": _BOUNDED_READS,
        "material_collection": _MATERIAL_COLLECTION,
        "deprecations": _DEPRECATIONS,
        "saved_queries": _SAVED_QUERIES,
        "analysis": _ANALYSIS,
        "formatting": {
            "lint_gate": (
                "Formatting runs lint and refuses findings that make a canonical "
                "rewrite lossy (currently repeated fields)."
            ),
            "profile_prefix": "format-",
            "defaults": {
                "indent": 2,
                "alignment": "compact",
                "trailing_comma": True,
                "blank_lines": True,
                "field_order": "preferred",
                "entry_order": "preserve",
                "block_order": "canonical",
                "wrap_values": "off",
                "line_width": 100,
                "entry_type_case": "lower",
            },
            "choices": {
                "alignment": ["compact", "equals"],
                "field_order": ["preferred", "preserve", "alphabetical"],
                "entry_order": ["preserve", "key", "profile"],
                "block_order": ["preserve", "canonical"],
                "wrap_values": ["off", "stable", "canonical"],
                "entry_type_case": ["lower", "preserve"],
            },
            "wrapping": {
                "never": [
                    "verbatim identifiers and paths",
                    "date fields",
                    "bare macros and numbers",
                    "concatenated expressions",
                ],
                "names": "break only between top-level names",
                "prose": "break only at brace- and math-top-level whitespace",
                "delimiters": "preserved",
            },
            "selection": (
                "--where reformats only the matching entries and leaves every "
                "other byte untouched. A selection owns the layout inside an "
                "entry, so the whole-file options --entry-order, --block-order, "
                "and --blank-lines cannot be combined with it."
            ),
        },
        "work_matching": {
            "module": "pynakes.identity",
            "statuses": ["exact", "probable", "conflict", "unknown"],
            "exact": "At least one normalized identifier matches and none conflict.",
            "probable": "Metadata similarity passes conservative title/year/author rules.",
            "conflict": "The candidates carry incompatible values for one identifier kind.",
            "unknown": "Available evidence does not support a match.",
            "non_work_identity": ["orcid"],
            "relationships_are_separate": True,
            "offline": True,
        },
        # The operations accepted by `batch` (op name → required/optional params).
        "batch_operations": _batch_operations(),
    }


def _batch_operations() -> dict:
    from pynakes.batch import operation_catalog

    return operation_catalog()
