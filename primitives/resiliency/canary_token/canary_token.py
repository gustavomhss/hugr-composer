from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
import hashlib


@dataclass(frozen=True)
class CanaryToken:
    """A registered canary token.

    Attributes:
        token_id: Unique identifier for this canary.
        canary_type: 'honeypot', 'credential', or 'decoy_record'.
        description: Human-readable description.
        fingerprint: Stable SHA-256-based fingerprint for attribution.
    """
    token_id: str
    canary_type: str
    description: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute the fingerprint from token_id + type."""
        fp = hashlib.sha256(f'{self.token_id}:{self.canary_type}'.encode()).hexdigest()[:16]
        object.__setattr__(self, 'fingerprint', fp)
