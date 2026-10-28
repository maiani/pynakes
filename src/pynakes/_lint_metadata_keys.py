"""Findings about ``pynakes-meta`` key names: removed, renamed, or deprecated."""

from pynakes._lint_issue import LintIssue
from pynakes.metadata.schema import (
    DEPRECATED_METADATA_KEYS,
    RENAMED_METADATA_KEYS,
    RETIRED_METADATA_KEYS,
    validate_metadata_value,
)
from pynakes.model import MetadataBlock


def deprecated_metadata_key_issue(block: MetadataBlock) -> LintIssue | None:
    """Report a key that still works but is deprecated, naming what replaces it."""
    replacement = DEPRECATED_METADATA_KEYS.get(block.key.lower())
    if replacement is None:
        return None
    return LintIssue(
        "deprecated_metadata_key",
        "warning",
        f"Metadata key {block.key!r} in pynakes-meta is deprecated and is removed in "
        f"0.10.0: {replacement}",
        key=block.key,
        field=block.key,
        line=block.start_line,
    )


def unknown_metadata_key_issues(block: MetadataBlock) -> list[LintIssue]:
    """Report an unrecognized pynakes-meta key, naming its replacement if renamed.

    A former key name (``fetch-policy``) is silently ignored by every command,
    so a library carrying one is not configured the way it reads. The finding
    names the replacement and the commands that migrate it, and checks the
    value against the replacement's grammar, so a typo (``prepring``) is
    caught now rather than after the rename.
    """
    retired = RETIRED_METADATA_KEYS.get(block.key.lower())
    if retired is not None:
        return [
            LintIssue(
                "unknown_metadata_key",
                "warning",
                f"Metadata key {block.key!r} in pynakes-meta was removed and is no longer "
                f"read: {retired}; remove it: `pynakes metadata remove FILE {block.key}`",
                key=block.key,
                field=block.key,
                line=block.start_line,
            )
        ]
    replacement = RENAMED_METADATA_KEYS.get(block.key.lower())
    if replacement is None:
        return [
            LintIssue(
                "unknown_metadata_key",
                "warning",
                f"Metadata key {block.key!r} in pynakes-meta is not recognized by the "
                "pynakes key schema",
                key=block.key,
                field=block.key,
                line=block.start_line,
            )
        ]
    issues = [
        LintIssue(
            "unknown_metadata_key",
            "warning",
            f"Metadata key {block.key!r} in pynakes-meta is the former name of "
            f"{replacement!r} and is no longer read; rename it: `pynakes metadata set FILE "
            f"{replacement} VALUE` then `pynakes metadata remove FILE {block.key}`",
            key=block.key,
            field=block.key,
            line=block.start_line,
        )
    ]
    try:
        validate_metadata_value(replacement, block.value)
    except ValueError as exc:
        issues.append(
            LintIssue(
                "invalid_metadata_value",
                "warning",
                f"Metadata key {block.key!r} in pynakes-meta has a value that would be "
                f"invalid as {replacement!r}: {exc}",
                key=block.key,
                field=block.key,
                line=block.start_line,
            )
        )
    return issues
