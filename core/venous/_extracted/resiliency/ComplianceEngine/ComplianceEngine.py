from __future__ import annotations
from typing import Any


class ComplianceEngine:
    """Central registry for PII fields and compliance operations."""

    def __init__(self) -> None:
        """Initialise with built-in PII patterns."""
        self._pii_patterns: list[str] = list(_PII_PATTERNS)

    def register_pii_field(self, pattern: str) -> None:
        """Register an additional column-name pattern as PII.

        Args:
            pattern: Substring to match (case-insensitive) against column names.
        """
        if pattern not in self._pii_patterns:
            self._pii_patterns.append(pattern)

    def is_pii_column(self, column_name: str) -> bool:
        """Return True when *column_name* looks like a PII field.

        Args:
            column_name: Name of the SQLAlchemy column (snake_case).

        Returns:
            True if the column matches any registered PII pattern.
        """
        lower = column_name.lower()
        return any((p in lower for p in self._pii_patterns))

    def detect_pii_columns(self, model_class: Any) -> list[str]:
        """Return PII column names found on a SQLAlchemy model class.

        Args:
            model_class: A mapped SQLAlchemy model (has ``__table__``).

        Returns:
            Sorted list of PII column names detected on the model.
        """
        try:
            table = model_class.__table__
        except AttributeError:
            return []
        return sorted((col.name for col in table.columns if self.is_pii_column(col.name)))

    def anonymise_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of *data* with PII values replaced by '[REDACTED]'.

        Args:
            data: Dictionary of field name -> value (e.g. model.__dict__).

        Returns:
            New dict with PII fields replaced.
        """
        return {k: '[REDACTED]' if self.is_pii_column(k) else v for k, v in data.items()}
