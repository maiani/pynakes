"""Provider-neutral records shared by reference import backends.

"Provider-neutral" is not "format-neutral": a record's field values are
declared ready for the target BibTeX/BibLaTeX dialect, and
:class:`ReferenceMetadata` enforces that where a provider's own spelling would
break it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pynakes.formatters._pages import normalize_page_numbers


@dataclass
class ReferenceMetadata:
    """Normalized metadata returned by an import provider.

    Provider clients translate their native response format into this record.
    ``fields`` contains semantic BibTeX/BibLaTeX field values ready for the
    target dialect, while ``identifiers`` keeps canonical identifier evidence
    available to duplicate detection and cross-provider comparison. The record is
    deliberately independent of :class:`~pynakes.model.BibEntry`: citation-key
    assignment and library mutation remain importer responsibilities.

    Because ``fields`` is declared ready for the target dialect, a provider
    spelling that the dialect cannot carry is a broken invariant rather than a
    value to pass along, and :meth:`__post_init__` repairs it. Doing that here
    is what covers every route: most providers build their record through
    :func:`~pynakes.providers._common.repository_metadata`, four construct one
    directly, and :func:`~pynakes.integrity.enrich_library` reads a supplement
    record's fields without ever rendering it to a
    :class:`~pynakes.model.BibEntry`.
    """

    provider: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)
    field_expressions: dict[str, str] = field(default_factory=dict)
    identifiers: dict[str, str] = field(default_factory=dict)
    provider_key: str | None = None

    def __post_init__(self) -> None:
        """Normalize field and identifier names, and repair provider page ranges."""
        self.provider = self.provider.strip()
        self.entry_type = self.entry_type.strip().lower()
        self.fields = {name.strip(): value for name, value in self.fields.items()}
        self.field_expressions = {
            name.strip(): value for name, value in self.field_expressions.items()
        }
        self.identifiers = {name.strip().lower(): value for name, value in self.identifiers.items()}
        self._normalize_pages()

    def _normalize_pages(self) -> None:
        """Rewrite an en/em-dash page range to BibTeX's ``start--end``.

        Providers hand back ranges punctuated with U+2013 (Crossref renders
        ``3--56`` as ``3–56``, and so do several of the repository APIs). The
        character survives UTF-8 plus ``inputenc`` but breaks under 8-bit
        ``bibtex`` with some styles, and it is visually near-identical to a
        hyphen, so it passes review and propagates once imported. Repairing it
        here rather than in one provider covers every import, ``--fetch`` and
        ``enrich`` route at once, costs no extra request, and stays offline and
        deterministic. :func:`~pynakes.formatters.normalize_page_numbers` leaves
        anything that is not a simple range alone, so an article number or a
        ``7,41,73--97`` list passes through untouched.
        """
        value = self.fields.get("pages", "")
        if not value:
            return
        normalized = normalize_page_numbers(value)
        if normalized != value:
            self.fields["pages"] = normalized
            self.field_expressions["pages"] = f"{{{normalized}}}"

    def identifier(self, kind: str) -> str | None:
        """Return one canonical identifier, if the provider supplied it."""
        return self.identifiers.get(kind.lower())

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation for diagnostics and tests."""
        return {
            "provider": self.provider,
            "entry_type": self.entry_type,
            "fields": dict(self.fields),
            "field_expressions": dict(self.field_expressions),
            "identifiers": dict(self.identifiers),
            "provider_key": self.provider_key,
        }
