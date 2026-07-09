"""Group-operation mixin for :class:`~pynakes.engine.Bibliography`.

All methods here delegate to :mod:`pynakes.groups` / :mod:`pynakes.group_tree`
and call ``self._mark()`` to record staging state.  Do not import this module
directly; use ``pynakes.engine``.
"""

from __future__ import annotations

from pynakes import group_tree as group_tree_ops
from pynakes import groups as group_ops


class BibliographyGroups:
    """Mixin providing group-tree operations for :class:`~pynakes.engine.Bibliography`.

    Consumers must not instantiate this class directly.
    """

    def list_groups(self) -> list[str]:
        """Return all group names in first-seen order."""
        return group_ops.list_groups(self.lib)

    def list_entries_in_group(self, group: str) -> list[str]:
        """Return entry keys that belong to ``group``."""
        return group_ops.list_entries_in_group(self.lib, group)

    def add_to_group(self, key: str, group: str) -> int:
        """Add every entry with ``key`` to ``group``."""
        count = group_ops.add_to_group(self.lib, key, group)
        self._mark(count)
        return count

    def remove_from_group(self, key: str, group: str) -> int:
        """Remove every entry with ``key`` from ``group``."""
        count = group_ops.remove_from_group(self.lib, key, group)
        self._mark(count)
        return count

    def list_tree(self) -> list[group_tree_ops.GroupNode] | None:
        """Return the group hierarchy tree, or ``None`` if none defined."""
        return group_tree_ops.list_tree(self.lib)

    def add_group_node(
        self,
        name: str,
        *,
        parent: str = "",
        context: int = 2,
        color: str = "",
        expanded: bool = True,
    ) -> bool:
        """Add a group node to the tree."""
        ok = group_tree_ops.add_node(
            self.lib, name, parent=parent, context=context, color=color, expanded=expanded
        )
        if ok:
            self._mark(True)
        return ok

    def remove_group_node(self, name: str) -> int:
        """Remove a group node and its descendants from the tree."""
        count = group_tree_ops.remove_node(self.lib, name)
        if count:
            self._mark(True)
        return count

    def rename_group_node(self, old_name: str, new_name: str) -> bool:
        """Rename a group node, updating parent references in children."""
        ok = group_tree_ops.rename_node(self.lib, old_name, new_name)
        if ok:
            self._mark(True)
        return ok

    def move_group_node(self, name: str, new_parent: str) -> bool:
        """Move a group node to a new parent."""
        ok = group_tree_ops.move_node(self.lib, name, new_parent)
        if ok:
            self._mark(True)
        return ok

    def update_group_node(self, name: str, **kwargs) -> bool:
        """Update properties of a group node."""
        ok = group_tree_ops.update_node(self.lib, name, **kwargs)
        if ok:
            self._mark(True)
        return ok

    def list_entries_in_group_tree(self, group: str, *, strict: bool = False) -> list[str]:
        """Return entry keys in *group*, including descendants unless *strict*."""
        return group_tree_ops.list_entries_in_group_tree(self.lib, group, strict=strict)
