from __future__ import annotations

import contextlib
import re
from typing import Any

_REDACTED = "[REDACTED]"

# PII-shaped patterns masked on the logging hot path (emails, card numbers,
# bearer/API tokens). Kept deliberately conservative to avoid clobbering
# legitimate free text — see Redactor.md.
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),          # emails
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),            # card-like digit runs
    re.compile(r"\b(?:sk|pk|rk)_[A-Za-z0-9]{8,}\b"),  # secret/publishable keys
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}\b"),   # bearer tokens
)


def _redact_string(value: str) -> str:
    """Mask PII-shaped substrings (emails, card numbers, tokens) with ``[REDACTED]``."""
    for pattern in _PII_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


class Redactor:
    """Structlog processor that redacts PII patterns in log event strings."""

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        """Redact PII from all string values in *event_dict*.

        Args:
            logger: structlog logger instance (unused).
            method: Log method name (unused).
            event_dict: Mutable log event dictionary.

        Returns:
            event_dict with PII replaced by ``[REDACTED]``. Per REDACTOR_INV_03
            this never raises — a throwing log processor would break the whole
            logging pipeline — so per-value redaction is wrapped defensively.
        """
        for key, value in list(event_dict.items()):
            if isinstance(value, str):
                with contextlib.suppress(Exception):
                    event_dict[key] = _redact_string(value)
        return event_dict
