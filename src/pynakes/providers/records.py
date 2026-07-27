"""Provider-neutral records shared by reference import backends."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReferenceMetadata:
    """Normalized metadata returned by an import provider.

    Provider clients translate their native response format into this record.
    ``fields`` contains semantic BibTeX/BibLaTeX field values ready for the
    target dialect, while ``identifiers`` keeps canonical identifier evidence
    available to duplicate detection and cross-provider comparison. The record is
    deliberately independent of :class:`~pynakes.model.BibEntry`: citation-key
    assignment and library mutation remain importer responsibilities.
    """

    provider: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)
    field_expressions: dict[str, str] = field(default_factory=dict)
    identifiers: dict[str, str] = field(default_factory=dict)
    provider_key: str | None = None

    def __post_init__(self) -> None:
        """Normalize field and identifier names without changing their values."""
        self.provider = self.provider.strip()
        self.entry_type = self.entry_type.strip().lower()
        self.fields = {name.strip(): value for name, value in self.fields.items()}
        self.field_expressions = {
            name.strip(): value for name, value in self.field_expressions.items()
        }
        self.identifiers = {name.strip().lower(): value for name, value in self.identifiers.items()}

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
