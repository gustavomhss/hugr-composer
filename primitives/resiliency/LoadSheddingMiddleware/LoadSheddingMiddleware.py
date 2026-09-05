"""Load shedder for request prioritization and shedding."""

from __future__ import annotations
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from collections import deque


class RequestPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class LoadShedder:
    """Load shedder that sheds low-priority requests under load."""

    max_concurrent: int = 1000
    latency_window: int = 100
    p99_threshold_ms: float = 500.0
    shed_strategy: str = "priority"
    
    _active_requests: int = field(default=0, init=False)
    _latencies: deque = field(default_factory=lambda: deque(maxlen=100), init=False)
    _tier: int = field(default=0, init=False)

    def classify_request(self, path: str, method: str) -> RequestPriority:
        critical_paths = ["/health", "/healthz", "/readyz", "/metrics"]
        if path in critical_paths:
            return RequestPriority.CRITICAL
        if method in ("GET", "HEAD") and path.startswith("/api/"):
            return RequestPriority.NORMAL
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return RequestPriority.HIGH
        return RequestPriority.LOW

    def is_shedding(self) -> bool:
        return self._tier >= 2

    def get_tier(self) -> int:
        return self._tier

    def try_acquire(self, priority: RequestPriority) -> bool:
        if self._active_requests >= self.max_concurrent:
            return False
        self._active_requests += 1
        return True

    def release(self, priority: RequestPriority) -> None:
        self._active_requests = max(0, self._active_requests - 1)

    def record_latency(self, latency_ms: float) -> None:
        self._latencies.append(latency_ms)
        if len(self._latencies) >= self.latency_window:
            sorted_latencies = sorted(self._latencies)
            p99_idx = int(len(sorted_latencies) * 0.99)
            p99 = sorted_latencies[p99_idx] if p99_idx < len(sorted_latencies) else sorted_latencies[-1]
            if p99 > self.p99_threshold_ms:
                self._tier = min(self._tier + 1, 2)
            elif p99 < self.p99_threshold_ms * 0.5:
                self._tier = max(self._tier - 1, 0)


# Global instances
_load_shedder = None
_degradation_manager = None


def get_load_shedder() -> LoadShedder:
    global _load_shedder
    if _load_shedder is None:
        _load_shedder = LoadShedder()
    return _load_shedder


def get_degradation_manager():
    global _degradation_manager
    if _degradation_manager is None:
        _degradation_manager = DegradationManager()
    return _degradation_manager


def _is_enabled() -> bool:
    return True


class DegradationManager:
    def __init__(self):
        self.tier = 0

    def set_tier(self, tier: int) -> None:
        self.tier = max(0, min(tier, 2))


_RETRY_AFTER_SECONDS = 60


def classify_request(path: str, method: str) -> RequestPriority:
    shedder = get_load_shedder()
    return shedder.classify_request(path, method)


from fastapi import Request, Response
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class LoadSheddingMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces load shedding based on p99 latency."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not _is_enabled():
            return await call_next(request)
        priority = classify_request(request.url.path, request.method)
        shedder = get_load_shedder()
        if shedder.is_shedding() and priority == RequestPriority.LOW:
            return JSONResponse(status_code=429, content={'detail': 'Service under load — low priority request shed.'}, headers={'Retry-After': str(_RETRY_AFTER_SECONDS)})
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = (time.monotonic() - start) * 1000.0
        shedder.record_latency(latency_ms)
        manager = get_degradation_manager()
        manager.set_tier(shedder.get_tier())
        return response
