from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
import time


@dataclass
class CostEstimate:
    """Cost estimate for a single request."""
    request_id: str
    path: str
    method: str
    db_cost_usd: float = 0.0
    s3_cost_usd: float = 0.0
    api_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def as_header_value(self) -> str:
        """Return a compact string suitable for the X-Request-Cost-Estimate header."""
        return f'${self.total_cost_usd:.6f}'
