"""Key-operation mixin for :class:`~pynakes.engine.Bibliography`.

All methods here delegate to :mod:`pynakes.keys` / :mod:`pynakes.usage` and
call ``self._mark()`` / ``self._stage_pinax_renames()`` to record staging
state.  Do not import this module directly; use ``pynakes.engine``.
"""

from __future__ import annotations

from pynakes import keys as key_ops
from pynakes.io import save_plain_text
from pynakes.usage import (
    iter_tex_files,
    rename_citation_keys_in_tex,
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
        self._mark(bool(renames))
        return renames

    def generate_key(self, key: str) -> tuple[str, str] | None:
        """Regenerate one citation key from its entry metadata."""
        rename = key_ops.regenerate_key(self.lib, key)
        self._stage_pinax_renames([rename] if rename is not None else [])
        self._mark(rename is not None)
        return rename

    def repair_keys(self) -> list[tuple[str, str]]:
        """Repair duplicate citation keys."""
        renames = key_ops.repair_duplicate_keys(self.lib)
        self._stage_pinax_renames(renames)
        self._mark(bool(renames))
        return renames

    def rename_key(self, old: str, new: str) -> int:
        """Rename one unique citation key."""
        count = key_ops.rename_key(self.lib, old, new)
        self._stage_pinax_renames([(old, new)] if count else [])
        self._mark(count)
        return count

    def _rewrite_tex_for_renames(self, renames: list[tuple[str, str]]) -> int:
        """Rewrite linked TeX files, mapping citation keys per *renames*.

        Returns total occurrence count across all rewritten files.
        Skips silently when the library has no ``tex-sources`` metadata or
        ``self.path`` is not set.
        """
        if self.path is None or not renames:
            return 0
        sources = tex_sources_from_metadata(self.lib, self.path.parent)
        if not sources:
            return 0
        total = 0
        for tex_path in iter_tex_files(sources):
            before = tex_path.read_text(encoding="utf-8", errors="replace")
            after, count = rename_citation_keys_in_tex(before, renames)
            total += count
            if count:
                saved = save_plain_text(after, str(tex_path), encoding="utf-8")
                if not saved.success:
                    raise OSError(saved.error or f"Could not write {tex_path}")
        return total

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
