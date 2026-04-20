"""CostTracker primitive — aggregates per-request cost estimates.

Framework-agnostic. No HTTP, no FastAPI awareness. Pluggable estimators
each label themselves by ``component`` ("db" | "s3" | "api"); the tracker
fan-outs a :class:`RequestContext` through every registered estimator,
sums the per-component costs, and retains a FIFO-bounded history.

Invariants (full text in ``CostTracker.contract.json``):

- COST_TRACKER_INV_01: An exception from an estimator MUST NOT propagate.
- COST_TRACKER_INV_02: ``_history`` length MUST NEVER exceed ``_max_history``.
- COST_TRACKER_INV_03: ``total_cost_usd`` == ``db_cost_usd + s3_cost_usd + api_cost_usd``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """Context gathered during request processing for cost estimation."""

    request_id: str
    path: str
    method: str
    db_query_count: int = 0
    db_query_duration_ms: int = 0
    s3_bytes_transferred: int = 0
    external_api_calls: int = 0
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


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
        """Return compact string suitable for an X-Request-Cost-Estimate header."""
        return f"${self.total_cost_usd:.6f}"


@runtime_checkable
class CostEstimatorProtocol(Protocol):
    """Protocol every cost estimator must satisfy."""

    component: str

    def estimate(self, ctx: RequestContext) -> float: ...


class CostTracker:
    """Aggregate per-request cost estimates from registered estimators.

    Estimators are invoked in registration order; any exception from an
    estimator is caught and logged — it NEVER propagates (INV_01).
    """

    def __init__(self, max_history: int = 10_000) -> None:
        self._estimators: list[CostEstimatorProtocol] = []
        self._history: list[CostEstimate] = []
        self._max_history: int = max_history

    def register(self, estimator: CostEstimatorProtocol) -> None:
        """Register a cost estimator."""
        self._estimators.append(estimator)
        logger.debug("Registered cost estimator: %s", estimator.component)

    def estimate_request(self, ctx: RequestContext) -> CostEstimate:
        """Run all estimators against *ctx* and return an aggregate estimate."""
        estimate = CostEstimate(request_id=ctx.request_id, path=ctx.path, method=ctx.method)
        for estimator in self._estimators:
            try:
                cost = estimator.estimate(ctx)
                if estimator.component == "db":
                    estimate.db_cost_usd += cost
                elif estimator.component == "s3":
                    estimate.s3_cost_usd += cost
                elif estimator.component == "api":
                    estimate.api_cost_usd += cost
            except Exception as exc:  # COST_TRACKER_INV_01 — fail-open
                logger.warning("Cost estimator %s failed: %s", estimator.component, exc)
        estimate.total_cost_usd = (
            estimate.db_cost_usd + estimate.s3_cost_usd + estimate.api_cost_usd
        )
        if len(self._history) >= self._max_history:
            self._history.pop(0)  # COST_TRACKER_INV_02 — FIFO eviction
        self._history.append(estimate)
        return estimate

    def get_history(self, limit: int = 1000) -> list[CostEstimate]:
        """Return the most recent *limit* cost estimates."""
        return self._history[-limit:]

    def get_by_endpoint(self, top_n: int = 10) -> list[dict]:
        """Return top-N endpoints by total estimated cost (descending)."""
        aggregated: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        for est in self._history:
            key = f"{est.method} {est.path}"
            aggregated[key] += est.total_cost_usd
            counts[key] += 1
        ranked = sorted(aggregated.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {
                "endpoint": k,
                "total_cost_usd": round(v, 6),
                "request_count": counts[k],
                "avg_cost_usd": round(v / counts[k], 6),
            }
            for k, v in ranked[:top_n]
        ]

    def get_summary(self) -> dict:
        """Return daily/weekly/monthly cost totals."""
        now = time.time()
        day_s = 86_400
        result = {"daily": 0.0, "weekly": 0.0, "monthly": 0.0}
        for est in self._history:
            age = now - est.timestamp
            if age <= day_s:
                result["daily"] += est.total_cost_usd
            if age <= day_s * 7:
                result["weekly"] += est.total_cost_usd
            if age <= day_s * 30:
                result["monthly"] += est.total_cost_usd
        return {k: round(v, 6) for k, v in result.items()}


# ---------------------------------------------------------------------------
# Default estimators (framework-agnostic; pure functions over RequestContext)
# ---------------------------------------------------------------------------


class DBQueryCostEstimator:
    """Estimate DB cost = ``ctx.db_query_count * rate_per_query``."""

    component = "db"

    def __init__(self, rate_per_query: float = 0.00001) -> None:
        self._rate = rate_per_query

    def estimate(self, ctx: RequestContext) -> float:
        return ctx.db_query_count * self._rate


class S3CostEstimator:
    """Estimate S3/blob cost = ``ctx.s3_bytes_transferred / 1 GiB * rate_per_gb``."""

    component = "s3"

    def __init__(self, rate_per_gb: float = 0.023) -> None:
        self._rate = rate_per_gb

    def estimate(self, ctx: RequestContext) -> float:
        gb = ctx.s3_bytes_transferred / (1024 ** 3)
        return gb * self._rate


class APICostEstimator:
    """Estimate external-API cost = ``ctx.external_api_calls * rate_per_call``."""

    component = "api"

    def __init__(self, rate_per_call: float = 0.0001) -> None:
        self._rate = rate_per_call

    def estimate(self, ctx: RequestContext) -> float:
        return ctx.external_api_calls * self._rate


__all__ = [
    "APICostEstimator",
    "CostEstimate",
    "CostEstimatorProtocol",
    "CostTracker",
    "DBQueryCostEstimator",
    "RequestContext",
    "S3CostEstimator",
]
