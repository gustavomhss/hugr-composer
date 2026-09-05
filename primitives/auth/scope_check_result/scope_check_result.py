from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeCheckResult:
    """Result of a single scope evaluation.

    Attributes:
        allowed: Whether the key has a matching granted scope.
        matched_scope: The specific scope string that matched, or None.
        reason: Human-readable explanation of the decision.
    """
    allowed: bool
    matched_scope: str | None
    reason: str
