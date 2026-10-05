"""The catalogue of error codes the CLI emits, with the exit code each carries.

Every failure the command line reports names one of these codes in the JSON
envelope's ``error`` field. The catalogue is the single source of truth for a
code's status and exit code: :func:`pynakes.cli_common._emit_error` looks the
code up here rather than taking an exit code from its caller, so a code cannot
be reported as an error in one command and as a conflict in another, and the
``capabilities`` description is generated from the same table.

Exit code 1 is an error: the request was malformed, or could not be carried
out. Exit code 2 is a conflict: the request was well formed, but carrying it out
needs a decision only the caller can make, and the envelope lists the
``options``.
"""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """A code the CLI may report in the JSON envelope's ``error`` field."""

    # --- errors (exit 1) ---
    USAGE_ERROR = "UsageError"
    INVALID_INPUT = "InvalidInput"
    FILE_NOT_FOUND = "FileNotFound"
    FILE_EXISTS = "FileExists"
    OUTPUT_IS_INPUT = "OutputIsInput"
    PARSE_ERROR = "ParseError"
    IO_ERROR = "IOError"
    INTERNAL_ERROR = "InternalError"
    KEY_NOT_FOUND = "KeyNotFound"
    NO_SOURCES = "NoSources"
    MISSING_TEX_SOURCE = "MissingTexSource"
    INVALID_NORMALIZE_OPTION = "InvalidNormalizeOption"
    RECURSIVE_FORMAT_ERROR = "RecursiveFormatError"
    FORMAT_LINT_ERROR = "FormatLintError"
    MISSING_CONVERT_TARGET = "MissingConvertTarget"
    UNSUPPORTED_CONVERSION = "UnsupportedConversion"
    NO_SUCH_DUPLICATE = "NoSuchDuplicate"
    INVALID_IDENTIFIER = "InvalidIdentifier"
    UNSUPPORTED_IDENTIFIER = "UnsupportedIdentifier"
    REFERENCE_IMPORT_ERROR = "ReferenceImportError"
    ONLINE_LOOKUP_REQUIRED = "OnlineLookupRequired"
    PROVIDER_UNAVAILABLE = "ProviderUnavailable"
    # --- conflicts (exit 2) ---
    EXTERNAL_MODIFICATION = "ExternalModification"
    CITATION_KEY_CONFLICT = "CitationKeyConflict"
    DUPLICATE_CITATION_KEY = "DuplicateCitationKey"
    GROUP_CONFLICT = "GroupConflict"
    DUPLICATE_METADATA = "DuplicateMetadata"
    DUPLICATE_MERGE_KEY = "DuplicateMergeKey"
    DEDUPE_CONFLICT = "DedupeConflict"
    DUPLICATE_REFERENCE = "DuplicateReference"


@dataclass(frozen=True)
class ErrorSpec:
    """How one code is reported: its exit code and what it means."""

    exit_code: int
    description: str

    @property
    def status(self) -> str:
        """The envelope ``status`` this code accompanies."""
        return "conflict" if self.exit_code == 2 else "error"


_E = ErrorCode

CATALOGUE: dict[ErrorCode, ErrorSpec] = {
    _E.USAGE_ERROR: ErrorSpec(
        1,
        "The command line was malformed: an unknown option, a missing or extra argument, "
        "an invalid choice, or a library path in the wrong position.",
    ),
    _E.INVALID_INPUT: ErrorSpec(1, "An argument, option value, or predicate was invalid."),
    _E.FILE_NOT_FOUND: ErrorSpec(1, "A given file does not exist."),
    _E.FILE_EXISTS: ErrorSpec(
        1, "An output file already exists; pass --force to overwrite it (includes 'file')."
    ),
    _E.OUTPUT_IS_INPUT: ErrorSpec(
        1, "The output path is also one of the command's inputs (includes 'file')."
    ),
    _E.PARSE_ERROR: ErrorSpec(1, "A .bib or source file could not be parsed (includes 'line')."),
    _E.IO_ERROR: ErrorSpec(1, "A read or write failed."),
    _E.INTERNAL_ERROR: ErrorSpec(
        1, "An unexpected failure inside pynakes (a bug; please report it)."
    ),
    _E.KEY_NOT_FOUND: ErrorSpec(
        1, "A named citation key, group, or metadata key is not in the library."
    ),
    _E.NO_SOURCES: ErrorSpec(
        1, "No TeX sources were given, and none are linked through 'tex-sources' metadata."
    ),
    _E.MISSING_TEX_SOURCE: ErrorSpec(
        1,
        "normalize: key regeneration found a missing linked TeX source; pass "
        "--ignore-missing-tex to proceed without rewriting it (includes 'sources').",
    ),
    _E.INVALID_NORMALIZE_OPTION: ErrorSpec(1, "normalize: an option value was not allowed."),
    _E.RECURSIVE_FORMAT_ERROR: ErrorSpec(1, "format --recursive: one or more files failed."),
    _E.FORMAT_LINT_ERROR: ErrorSpec(
        1, "format: lint findings make a lossless rewrite unsafe (includes 'issues')."
    ),
    _E.MISSING_CONVERT_TARGET: ErrorSpec(1, "convert: neither --to nor --from was given."),
    _E.UNSUPPORTED_CONVERSION: ErrorSpec(
        1, "convert: an import produces BibTeX, so --to names no interchange format with --from."
    ),
    _E.NO_SUCH_DUPLICATE: ErrorSpec(
        1, "dedupe merge: a --key names an entry that is in no duplicate cluster."
    ),
    _E.INVALID_IDENTIFIER: ErrorSpec(1, "ref import: an identifier value was malformed."),
    _E.UNSUPPORTED_IDENTIFIER: ErrorSpec(
        1, "ref import: no provider recognized the identifier or URL."
    ),
    _E.REFERENCE_IMPORT_ERROR: ErrorSpec(
        1, "ref import: provider metadata could not be resolved or imported."
    ),
    _E.ONLINE_LOOKUP_REQUIRED: ErrorSpec(
        1, "The command needs the network and --online was not given."
    ),
    _E.PROVIDER_UNAVAILABLE: ErrorSpec(1, "A metadata provider or index could not be reached."),
    _E.EXTERNAL_MODIFICATION: ErrorSpec(
        2,
        "The file changed on disk since it was read, or no longer matches --expect-sha256 "
        "(includes 'expected_sha256' and 'source_sha256' for the precondition).",
    ),
    _E.CITATION_KEY_CONFLICT: ErrorSpec(
        2, "The citation key to create or rename to already exists (includes 'key')."
    ),
    _E.DUPLICATE_CITATION_KEY: ErrorSpec(
        2, "The citation key identifies several entries, so the target is ambiguous."
    ),
    _E.GROUP_CONFLICT: ErrorSpec(
        2, "The group to create or rename to already exists (includes 'group')."
    ),
    _E.DUPLICATE_METADATA: ErrorSpec(
        2, "Several metadata blocks match the key, so the target is ambiguous."
    ),
    _E.DUPLICATE_MERGE_KEY: ErrorSpec(
        2, "corpus combine/split --dedupe: a shared citation key has differing content."
    ),
    _E.DEDUPE_CONFLICT: ErrorSpec(2, "dedupe merge: a cluster has irreconcilable field values."),
    _E.DUPLICATE_REFERENCE: ErrorSpec(
        2, "ref import: the work is already in the library (includes 'existing_keys')."
    ),
}


def spec_for(code: str) -> ErrorSpec:
    """Return the catalogued spec for *code*.

    An uncatalogued code is a bug in pynakes, not a user error, so it raises
    ``AssertionError``, which the CLI reports as ``InternalError``.
    """
    try:
        return CATALOGUE[ErrorCode(code)]
    except ValueError:
        raise AssertionError(f"error code {code!r} is not catalogued") from None


def catalogue_description() -> dict:
    """Describe the catalogue for ``capabilities``, grouped by status."""
    groups: dict[str, dict] = {}
    for code, spec in CATALOGUE.items():
        group = groups.setdefault(spec.status, {"exit_code": spec.exit_code, "codes": {}})
        group["codes"][code.value] = spec.description
    return groups
