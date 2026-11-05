"""Lazy distribution version shared by the public API and provider transport."""

from functools import cache


@cache
def package_version() -> str:
    """Read installed metadata once, with a fallback for an uninstalled checkout."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("pynakes")
    except PackageNotFoundError:
        return "0.0.0+unknown"
