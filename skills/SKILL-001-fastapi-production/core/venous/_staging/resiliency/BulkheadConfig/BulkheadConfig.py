from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field


@dataclass
class BulkheadConfig:
    """Configuration for per-group concurrency limits.

    Attributes:
        limits: Dict mapping group name → max_concurrent integer.
    """
    limits: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate that all limits are positive integers."""
        for group, limit in self.limits.items():
            if limit < 1:
                raise ValueError(f"Bulkhead limit for '{group}' must be >= 1, got {limit}")
