from __future__ import annotations
from typing import Any


class Redactor:
    """Structlog processor that redacts PII patterns in log event strings."""

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        """Redact PII from all string values in *event_dict*.

        Args:
            logger: structlog logger instance (unused).
            method: Log method name (unused).
            event_dict: Mutable log event dictionary.

        Returns:
            event_dict with PII replaced by ``[REDACTED]``.
        """
        for key, value in list(event_dict.items()):
            if isinstance(value, str):
                event_dict[key] = _redact_string(value)
        return event_dict
