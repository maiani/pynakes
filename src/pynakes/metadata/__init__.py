"""Structured support for library metadata comments.

pynakes stores library-level settings as top-level comments: JabRef's own
``@comment{jabref-meta: key:value;}`` and pynakes' superset
``@comment{pynakes-meta: key:value;}``. This package layers three concerns:

- :mod:`.core` — namespace-neutral comment mechanics (parse/format/set/remove/
  consolidate), no knowledge of which keys mean what.
- :mod:`.schema` — pynakes' canonical, JabRef-unaware key registry and the
  pure native reads for concepts that also have a JabRef counterpart.
- :mod:`.jabref` — the JabRef compatibility adapter: its key vocabulary, its
  encoded value grammars, and the cross-namespace arbitration (owner,
  namespace routing) that only exists because pynakes and JabRef share one
  file format.

Domain code should import from this package (or ``.jabref`` for the
fallback-aware accessors), not reach into ``.core``/``.schema`` directly. See
the "JabRef Compatibility" guide in the pynakes docs for the boundary this
layering draws.
"""

from pynakes.metadata.core import (
    JABREF_PREFIX,
    PYNAKES_PREFIX,
    DuplicateMetadataError,
    MetadataUpdate,
    consolidate_metadata,
    format_metadata_comment,
    format_metadata_list,
    format_pynakes_meta_block,
    metadata_blocks_to_dict,
    metadata_bool,
    metadata_list,
    metadata_list_values,
    metadata_value,
    metadata_values,
    remove_in_namespace,
    set_in_namespace,
)
from pynakes.metadata.core import parse_metadata_comment as _parse_metadata_comment_raw
from pynakes.metadata.jabref import (
    JABREF_EXACT_KEYS,
    JABREF_PREFIX_KEYS,
    SAVE_ORDER_KEY_FIELDS,
    SAVE_ORDER_TYPES,
    JabRefAdoptReport,
    MetadataOwner,
    SaveActions,
    SaveOrder,
    aliased_drift_warnings,
    default_namespace,
    format_save_order,
    is_known_metadata_key,
    jabref_projection,
    library_dialect,
    library_is_jabref_tracked,
    library_key_pattern,
    library_save_actions,
    library_save_order,
    library_sort_order,
    metadata_category,
    metadata_owner,
    parse_save_actions,
    parse_save_order,
    project_aliased_to_jabref,
    raw_database_type,
    raw_key_pattern,
    remove_metadata,
    set_metadata,
)
from pynakes.metadata.schema import (
    CATEGORY_CITATION_KEY,
    CATEGORY_FILES,
    CATEGORY_GROUPS,
    CATEGORY_LIBRARY,
    CATEGORY_LINT,
    CATEGORY_NORMALIZATION,
    CATEGORY_PINAX,
    CATEGORY_SAVE,
    CATEGORY_SELECTORS,
    CATEGORY_UNKNOWN,
    CATEGORY_USAGE,
    PYNAKES_EXACT_KEYS,
    PYNAKES_PREFIX_KEYS,
    MetadataCategory,
    native_dialect,
    native_key_pattern,
    native_sort_order,
    parse_sort_order_value,
    validate_metadata_value,
)


def parse_metadata_comment(
    comment_text: str,
    *,
    raw: str | None = None,
    comment_index: int = -1,
):
    """Parse a top-level metadata comment, classifying keys across both namespaces.

    Thin wrapper over :func:`pynakes.metadata.core.parse_metadata_comment` that
    supplies :func:`pynakes.metadata.jabref.metadata_category` as the
    classifier, so parsed blocks carry accurate ``known``/``category`` values.
    """
    return _parse_metadata_comment_raw(
        comment_text, raw=raw, comment_index=comment_index, classify=metadata_category
    )


# Back-compat alias: `library_database_type` is now dialect-aware (checks
# pynakes' native `dialect` key before falling back to JabRef's `databaseType`).
library_database_type = library_dialect

__all__ = [
    "CATEGORY_CITATION_KEY",
    "CATEGORY_FILES",
    "CATEGORY_GROUPS",
    "CATEGORY_LIBRARY",
    "CATEGORY_LINT",
    "CATEGORY_NORMALIZATION",
    "CATEGORY_PINAX",
    "CATEGORY_SAVE",
    "CATEGORY_SELECTORS",
    "CATEGORY_UNKNOWN",
    "CATEGORY_USAGE",
    "JABREF_EXACT_KEYS",
    "JABREF_PREFIX",
    "JABREF_PREFIX_KEYS",
    "PYNAKES_EXACT_KEYS",
    "PYNAKES_PREFIX",
    "PYNAKES_PREFIX_KEYS",
    "SAVE_ORDER_KEY_FIELDS",
    "SAVE_ORDER_TYPES",
    "DuplicateMetadataError",
    "JabRefAdoptReport",
    "MetadataCategory",
    "MetadataOwner",
    "MetadataUpdate",
    "SaveActions",
    "SaveOrder",
    "aliased_drift_warnings",
    "consolidate_metadata",
    "default_namespace",
    "format_metadata_comment",
    "format_metadata_list",
    "format_pynakes_meta_block",
    "format_save_order",
    "is_known_metadata_key",
    "jabref_projection",
    "library_database_type",
    "library_dialect",
    "library_is_jabref_tracked",
    "library_key_pattern",
    "library_save_actions",
    "library_save_order",
    "library_sort_order",
    "metadata_blocks_to_dict",
    "metadata_bool",
    "metadata_category",
    "metadata_list",
    "metadata_list_values",
    "metadata_owner",
    "metadata_value",
    "metadata_values",
    "native_dialect",
    "native_key_pattern",
    "native_sort_order",
    "parse_metadata_comment",
    "validate_metadata_value",
    "parse_save_actions",
    "parse_save_order",
    "parse_sort_order_value",
    "project_aliased_to_jabref",
    "raw_database_type",
    "raw_key_pattern",
    "remove_in_namespace",
    "remove_metadata",
    "set_in_namespace",
    "set_metadata",
]
