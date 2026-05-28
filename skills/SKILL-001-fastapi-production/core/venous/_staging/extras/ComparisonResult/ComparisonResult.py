from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field


@dataclass
class ComparisonResult:
    """Result of comparing two OpenAPI schemas.

    Attributes:
        classification: Overall severity of detected changes.
        breaking: List of breaking-change violation strings.
        compatible: List of compatible-change descriptions.
        additive: List of additive-change descriptions.
        summary: Human-readable one-line summary.
    """
    classification: ChangeClass
    breaking: list[str] = field(default_factory=list)
    compatible: list[str] = field(default_factory=list)
    additive: list[str] = field(default_factory=list)
    summary: str = ''

    @property
    def is_breaking(self) -> bool:
        """Return True when classification is BREAKING."""
        return self.classification == ChangeClass.BREAKING
