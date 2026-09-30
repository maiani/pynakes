"""Key-operation mixin for :class:`~pynakes.engine.Bibliography`.

All methods here delegate to :mod:`pynakes.keys` / :mod:`pynakes.usage` and
stage any matching Pinax renames; bibliography dirty state is derived from the
result. Do not import this module directly; use ``pynakes.engine``.
"""

from __future__ import annotations

from pathlib import Path

from pynakes import _tex_rewrite
from pynakes import keys as key_ops
from pynakes.usage import (
    MissingTexSourcesError,
    iter_tex_files,
    tex_sources_from_metadata,
)


class BibliographyKeys:
    """Mixin providing key operations for :class:`~pynakes.engine.Bibliography`.

    Consumers must not instantiate this class directly.
    """

    def generate_keys(self) -> list[tuple[str, str]]:
        """Regenerate all citation keys from entry metadata."""
        renames = key_ops.regenerate_keys(self.lib)
        self._stage_pinax_renames(renames)
        return renames

    def generate_key(self, key: str) -> tuple[str, str] | None:
        """Regenerate one citation key from its entry metadata."""
        rename = key_ops.regenerate_key(self.lib, key)
        self._stage_pinax_renames([rename] if rename is not None else [])
        return rename

    def repair_keys(self) -> list[tuple[str, str]]:
        """Repair duplicate citation keys."""
        renames = key_ops.repair_duplicate_keys(self.lib)
        self._stage_pinax_renames(renames)
        return renames

    def rename_key(self, old: str, new: str) -> int:
        """Rename one unique citation key."""
        count = key_ops.rename_key(self.lib, old, new)
        self._stage_pinax_renames([(old, new)] if count else [])
        return count

    def _rewrite_tex_for_renames(
        self, renames: list[tuple[str, str]], *, allow_missing_sources: bool = False
    ) -> int:
        """Stage rewrites of linked TeX files, mapping citation keys per *renames*.

        The files are written by the next :meth:`commit`, after the ``.bib``
        itself, so a failure cannot leave the manuscript renamed and the
        bibliography not. Returns the total occurrence count to be rewritten.
        Skips silently when the library has no ``tex-sources`` metadata or
        ``self.path`` is not set. Missing declared sources stop the rename
        unless ``allow_missing_sources`` is explicitly set.
        """
        if self.path is None or not renames:
            return 0
        sources = tex_sources_from_metadata(self.lib, self.path.parent)
        if not sources:
            return 0
        missing = [source for source in sources if not Path(source).exists()]
        if missing and not allow_missing_sources:
            raise MissingTexSourcesError(missing)
        sources = [source for source in sources if Path(source).exists()]
        tex_files = iter_tex_files(sources)
        _tex_rewrite.require_inside_project(tex_files, self.path)
        rewrites = [_tex_rewrite.plan_tex_rewrite(path, renames) for path in tex_files]
        self.stage_tex_rewrites(rewrites)
        return sum(rewrite.occurrences for rewrite in rewrites)

    def rename_citekey(
        self,
        old: str,
        new: str,
        *,
        rewrite_tex: bool = True,
    ) -> dict:
        """Rename a citation key consistently.

        Updates the bib entry, Pinax material files, and (when
        *rewrite_tex* is true) linked TeX source files.  Returns::

            {"entry_renamed": bool, "tex_occurrences": int}
        """
        if self.path is None:
            raise ValueError("rename_citekey requires a bound .bib file path")
        entry_renamed = bool(self.rename_key(old, new))
        tex_occurrences = (
            self._rewrite_tex_for_renames([(old, new)]) if rewrite_tex and entry_renamed else 0
        )
        return {"entry_renamed": entry_renamed, "tex_occurrences": tex_occurrences}
