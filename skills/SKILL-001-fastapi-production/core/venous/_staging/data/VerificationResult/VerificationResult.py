from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field


@dataclass
class VerificationResult:
    """Result of a hash-chain verification run.

    Attributes:
        total_entries: Number of entries examined.
        broken_at: Entry id where the chain first breaks, or None.
        is_intact: True if every hash in the range is valid.
        errors: Human-readable descriptions of any integrity violations.
    """
    total_entries: int = 0
    broken_at: str | None = None
    is_intact: bool = True
    errors: list[str] = field(default_factory=list)
