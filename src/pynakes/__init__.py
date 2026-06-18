"""pynakes: Agent-friendly BibTeX library management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pynakes")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"
