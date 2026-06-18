"""Diff generation utilities."""

from difflib import unified_diff


def generate_diff(original: str, modified: str, file_name: str = "file") -> str:
    """Generate a unified diff between two strings.

    Args:
        original: Original content
        modified: Modified content
        file_name: Name to use in diff header

    Returns:
        Unified diff as string
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff_lines = unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"{file_name} (original)",
        tofile=f"{file_name} (modified)",
        lineterm="",
    )

    return "\n".join(diff_lines)
