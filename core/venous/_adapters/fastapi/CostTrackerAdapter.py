"""FastAPI adapter over the `CostTracker` primitive.

Installs a ``CostMiddleware`` that annotates every response with an
``X-Request-Cost-Estimate`` header, exposes the tracker on
``app.state.cost_tracker``, and wires the three default estimators. Cost
observation is fail-open (INV_01): a broken estimator never fails a request.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.CostTrackerAdapter import install

    app = FastAPI()
    install(app, db_rate=0.00001, s3_rate=0.023, api_rate=0.0001)
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from starlette.responses import Response

from core.venous.resiliency.CostTracker.CostTracker import (
    APICostEstimator,
    CostTracker,
    DBQueryCostEstimator,
    RequestContext,
    S3CostEstimator,
)

_SKIP_PATHS = ("/healthz", "/docs", "/redoc", "/openapi", "/metrics")


def install(
    app: FastAPI,
    *,
    db_rate: float = 0.00001,
    s3_rate: float = 0.023,
    api_rate: float = 0.0001,
) -> CostTracker:
    """Install CostTracker + middleware on *app*; return the live tracker."""
    tracker = CostTracker()
    tracker.register(DBQueryCostEstimator(rate_per_query=db_rate))
    tracker.register(S3CostEstimator(rate_per_gb=s3_rate))
    tracker.register(APICostEstimator(rate_per_call=api_rate))
    app.state.cost_tracker = tracker

    @app.middleware("http")
    async def _cost(request: Request, call_next) -> Response:  # noqa: ANN001
        if any(request.url.path.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)
        ctx = RequestContext(request_id=str(uuid.uuid4()), path=request.url.path, method=request.method)
        request.state.cost_context = ctx
        t0 = time.monotonic()
        response = await call_next(request)
        ctx.duration_ms = int((time.monotonic() - t0) * 1000)
        try:  # COST_TRACKER_INV_01 — fail-open
            est = tracker.estimate_request(ctx)
            response.headers["X-Request-Cost-Estimate"] = est.as_header_value()
            response.headers["X-Request-Id"] = ctx.request_id
        except Exception:  # noqa: BLE001
            pass
        return response

    return tracker
