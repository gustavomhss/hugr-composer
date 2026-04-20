from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
import time


@dataclass
class RequestContext:
    """Contextual data gathered during request processing for cost estimation."""
    request_id: str
    path: str
    method: str
    db_query_count: int = 0
    db_query_duration_ms: int = 0
    s3_bytes_transferred: int = 0
    external_api_calls: int = 0
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)
