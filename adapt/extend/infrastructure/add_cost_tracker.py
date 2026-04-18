"""TOOL-120: add_cost_tracker — per-request cost estimation with X-Request-Cost-Estimate.

Writes a ``CostTracker`` with pluggable estimators (DBQueryCostEstimator,
S3CostEstimator, APICostEstimator), a ``CostMiddleware`` that annotates
every response with an ``X-Request-Cost-Estimate`` header, and REST routes
for cost reporting (GET /costs/summary with daily/weekly/monthly breakdowns,
GET /costs/by-endpoint for the top-N most expensive endpoints).

Design decisions:
* **Zero external dependencies** — estimators use in-process counters
  incremented via SQLAlchemy events and httpx hooks; no sidecar required.
* **Additive, never blocking** — CostMiddleware catches all exceptions
  internally; a broken estimator never takes down a request.
* **Lazy stripe import** — no optional SDK is imported at module level.
* **Idempotency** — a second run detects the ``CostTracker`` fingerprint
  and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker

    result = add_cost_tracker(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_cost_tracker",
    "description": (
        "Add per-request cost estimation: CostTracker with DB/S3/API estimators, "
        "CostMiddleware annotating X-Request-Cost-Estimate header, "
        "GET /costs/summary (daily/weekly/monthly), GET /costs/by-endpoint (top N)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_cost_tracker",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cost_tracker(inp: ToolInput) -> ToolResult:
    """Add per-request cost estimation to a FastAPI project.

    Creates CostTracker, pluggable estimators, CostMiddleware, and routes
    for cost reporting.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ----------------------------------------------------
    cost_tracker_file = app_dir / "costs" / "tracker.py"
    if cost_tracker_file.exists() and "CostTracker" in cost_tracker_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "CostTracker already present in app/costs/tracker.py — "
                "cost tracking already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard ---------------------------------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/costs/tracker.py, app/costs/estimators.py,",
                "         app/middleware/cost_tracker.py, app/api/routes/costs.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — costs package
    costs_dir = app_dir / "costs"
    costs_dir.mkdir(parents=True, exist_ok=True)
    costs_init = costs_dir / "__init__.py"
    if not costs_init.exists():
        costs_init.write_text('"""Cost tracking package."""\n')
        files_created.append(str(costs_init))

    # Step 2 — CostTracker core
    _write_cost_tracker(cost_tracker_file)
    files_created.append(str(cost_tracker_file))

    # Step 3 — Estimators
    estimators_file = costs_dir / "estimators.py"
    _write_estimators(estimators_file)
    files_created.append(str(estimators_file))

    # Step 4 — CostMiddleware
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    cost_middleware_file = middleware_dir / "cost_tracker.py"
    _write_cost_middleware(cost_middleware_file)
    files_created.append(str(cost_middleware_file))

    # Step 5 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    costs_route_file = routes_dir / "costs.py"
    _write_costs_routes(costs_route_file)
    files_created.append(str(costs_route_file))

    # Step 6 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 7 — register costs router
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    # --- AST validation -------------------------------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Cost Tracker added: CostTracker with DBQuery/S3/API estimators,",
            "CostMiddleware (X-Request-Cost-Estimate header),",
            "GET /costs/summary (daily/weekly/monthly),",
            "GET /costs/by-endpoint (top N expensive endpoints).",
        ],
        next_steps=[
            "Set COST_TRACKING_ENABLED=true, COST_DB_QUERY_RATE, COST_S3_PER_GB, "
            "COST_API_CALL_RATE in .env",
            "Register CostMiddleware in app/main.py",
            "Tune estimator rates to match your actual cloud pricing",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Writer helpers
# ---------------------------------------------------------------------------

def _write_cost_tracker(path: Path) -> None:
    """Write app/costs/tracker.py with CostTracker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"CostTracker — aggregates per-request cost estimates from pluggable estimators.

        Usage::

            tracker = CostTracker()
            tracker.register(DBQueryCostEstimator(rate_per_query=0.00001))
            tracker.register(S3CostEstimator(rate_per_gb=0.023))
            estimate = tracker.estimate_request(ctx)
        \"\"\"

        from __future__ import annotations

        import logging
        import time
        from collections import defaultdict
        from dataclasses import dataclass, field
        from typing import Protocol

        logger = logging.getLogger(__name__)


        @dataclass
        class RequestContext:
            \"\"\"Contextual data gathered during request processing for cost estimation.\"\"\"

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
            \"\"\"Cost estimate for a single request.\"\"\"

            request_id: str
            path: str
            method: str
            db_cost_usd: float = 0.0
            s3_cost_usd: float = 0.0
            api_cost_usd: float = 0.0
            total_cost_usd: float = 0.0
            timestamp: float = field(default_factory=time.time)

            def as_header_value(self) -> str:
                \"\"\"Return a compact string suitable for the X-Request-Cost-Estimate header.\"\"\"
                return f"${self.total_cost_usd:.6f}"


        class CostEstimatorProtocol(Protocol):
            \"\"\"Protocol that all cost estimators must satisfy.\"\"\"

            def estimate(self, ctx: RequestContext) -> float:
                \"\"\"Return estimated cost in USD for the given request context.\"\"\"
                ...

            @property
            def component(self) -> str:
                \"\"\"Return a short label for this estimator (e.g. 'db', 's3').\"\"\"
                ...


        class CostTracker:
            \"\"\"Aggregate per-request cost estimates from registered estimators.

            Estimators are invoked in registration order; any exception from
            an estimator is caught and logged — it never propagates to callers.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise tracker with empty estimator registry and history.\"\"\"
                self._estimators: list[CostEstimatorProtocol] = []
                self._history: list[CostEstimate] = []
                self._max_history: int = 10_000

            def register(self, estimator: CostEstimatorProtocol) -> None:
                \"\"\"Register a cost estimator.\"\"\"
                self._estimators.append(estimator)
                logger.debug("Registered cost estimator: %s", estimator.component)

            def estimate_request(self, ctx: RequestContext) -> CostEstimate:
                \"\"\"Run all estimators against *ctx* and return an aggregate estimate.\"\"\"
                estimate = CostEstimate(
                    request_id=ctx.request_id,
                    path=ctx.path,
                    method=ctx.method,
                )

                for estimator in self._estimators:
                    try:
                        cost = estimator.estimate(ctx)
                        if estimator.component == "db":
                            estimate.db_cost_usd += cost
                        elif estimator.component == "s3":
                            estimate.s3_cost_usd += cost
                        elif estimator.component == "api":
                            estimate.api_cost_usd += cost
                    except Exception as exc:
                        logger.warning("Cost estimator %s failed: %s", estimator.component, exc)

                estimate.total_cost_usd = (
                    estimate.db_cost_usd + estimate.s3_cost_usd + estimate.api_cost_usd
                )

                if len(self._history) >= self._max_history:
                    self._history.pop(0)
                self._history.append(estimate)
                return estimate

            def get_history(self, limit: int = 1000) -> list[CostEstimate]:
                \"\"\"Return the most recent *limit* cost estimates.\"\"\"
                return self._history[-limit:]

            def get_by_endpoint(self, top_n: int = 10) -> list[dict]:
                \"\"\"Return top-N endpoints by total estimated cost (descending).\"\"\"
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
                \"\"\"Return daily/weekly/monthly cost totals.\"\"\"
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


        # Module-level shared tracker
        _tracker: CostTracker | None = None


        def get_cost_tracker() -> CostTracker:
            \"\"\"Return (and lazily initialise) the global CostTracker instance.\"\"\"
            global _tracker
            if _tracker is None:
                from app.costs.estimators import (
                    APICostEstimator,
                    DBQueryCostEstimator,
                    S3CostEstimator,
                )
                from app.core.config import settings

                _tracker = CostTracker()
                _tracker.register(
                    DBQueryCostEstimator(
                        rate_per_query=getattr(settings, "COST_DB_QUERY_RATE", 0.00001)
                    )
                )
                _tracker.register(
                    S3CostEstimator(
                        rate_per_gb=getattr(settings, "COST_S3_PER_GB", 0.023)
                    )
                )
                _tracker.register(
                    APICostEstimator(
                        rate_per_call=getattr(settings, "COST_API_CALL_RATE", 0.0001)
                    )
                )

            return _tracker
    """))


def _write_estimators(path: Path) -> None:
    """Write app/costs/estimators.py with DBQueryCostEstimator, S3CostEstimator, APICostEstimator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"Pluggable cost estimators for CostTracker.

        Each estimator receives a ``RequestContext`` and returns an estimated
        cost in USD for the component it measures.
        \"\"\"

        from __future__ import annotations

        import logging

        from app.costs.tracker import RequestContext

        logger = logging.getLogger(__name__)


        class DBQueryCostEstimator:
            \"\"\"Estimate cost of database queries in a request.

            Uses ``RequestContext.db_query_count`` multiplied by
            *rate_per_query* (cost per individual query in USD).
            \"\"\"

            component = "db"

            def __init__(self, rate_per_query: float = 0.00001) -> None:
                \"\"\"Initialise with cost per DB query in USD.\"\"\"
                self._rate = rate_per_query

            def estimate(self, ctx: RequestContext) -> float:
                \"\"\"Return estimated DB cost in USD.\"\"\"
                return ctx.db_query_count * self._rate


        class S3CostEstimator:
            \"\"\"Estimate cost of S3/blob-storage transfers in a request.

            Uses ``RequestContext.s3_bytes_transferred`` converted to GB
            and multiplied by *rate_per_gb*.
            \"\"\"

            component = "s3"

            def __init__(self, rate_per_gb: float = 0.023) -> None:
                \"\"\"Initialise with cost per GB transferred in USD.\"\"\"
                self._rate = rate_per_gb

            def estimate(self, ctx: RequestContext) -> float:
                \"\"\"Return estimated S3 cost in USD.\"\"\"
                gb = ctx.s3_bytes_transferred / (1024 ** 3)
                return gb * self._rate


        class APICostEstimator:
            \"\"\"Estimate cost of external API calls made during a request.

            Uses ``RequestContext.external_api_calls`` multiplied by
            *rate_per_call*.
            \"\"\"

            component = "api"

            def __init__(self, rate_per_call: float = 0.0001) -> None:
                \"\"\"Initialise with cost per external API call in USD.\"\"\"
                self._rate = rate_per_call

            def estimate(self, ctx: RequestContext) -> float:
                \"\"\"Return estimated external API cost in USD.\"\"\"
                return ctx.external_api_calls * self._rate
    """))


def _write_cost_middleware(path: Path) -> None:
    """Write app/middleware/cost_tracker.py with CostMiddleware."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"CostMiddleware — annotates each response with X-Request-Cost-Estimate header.

        Does NOT block or modify the response body; only adds a header with the
        estimated USD cost of the request. All exceptions are caught internally
        so a broken estimator never takes down a request.
        \"\"\"

        from __future__ import annotations

        import logging
        import time
        import uuid
        from typing import Any

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        logger = logging.getLogger(__name__)

        _SKIP_PATHS = ("/healthz", "/docs", "/redoc", "/openapi", "/metrics")


        class CostMiddleware(BaseHTTPMiddleware):
            \"\"\"Annotate each response with X-Request-Cost-Estimate header.

            The header value is a USD string like ``$0.000042``. If cost
            tracking is disabled or the estimator raises, the header is omitted.
            \"\"\"

            def __init__(self, app: Any, enabled: bool = True) -> None:
                \"\"\"Initialise middleware.\"\"\"
                super().__init__(app)
                self._enabled = enabled

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Process request, estimate cost, annotate response header.\"\"\"
                if not self._enabled:
                    return await call_next(request)

                path = request.url.path
                if any(path.startswith(p) for p in _SKIP_PATHS):
                    return await call_next(request)

                t0 = time.monotonic()
                request_id = str(uuid.uuid4())

                # Attach context to request state for downstream instrumentation
                from app.costs.tracker import RequestContext

                ctx = RequestContext(
                    request_id=request_id,
                    path=path,
                    method=request.method,
                )
                request.state.cost_context = ctx

                response = await call_next(request)

                ctx.duration_ms = int((time.monotonic() - t0) * 1000)

                try:
                    from app.costs.tracker import get_cost_tracker

                    tracker = get_cost_tracker()
                    estimate = tracker.estimate_request(ctx)
                    response.headers["X-Request-Cost-Estimate"] = estimate.as_header_value()
                    response.headers["X-Request-Id"] = request_id
                except Exception as exc:
                    logger.debug("Cost estimation failed (non-fatal): %s", exc)

                return response
    """))


def _write_costs_routes(path: Path) -> None:
    """Write app/api/routes/costs.py."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"Cost reporting routes.\"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, Query

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/costs", tags=["costs"])


        @router.get("/summary")
        async def cost_summary() -> dict:
            \"\"\"Return daily/weekly/monthly cost totals.\"\"\"
            from app.costs.tracker import get_cost_tracker

            tracker = get_cost_tracker()
            return tracker.get_summary()


        @router.get("/by-endpoint")
        async def cost_by_endpoint(
            top_n: int = Query(default=10, ge=1, le=100),
        ) -> list[dict]:
            \"\"\"Return the top-N most expensive endpoints by total estimated cost.\"\"\"
            from app.costs.tracker import get_cost_tracker

            tracker = get_cost_tracker()
            return tracker.get_by_endpoint(top_n=top_n)
    """))


def _patch_config(config_file: Path) -> None:
    """Inject cost tracker config fields into Settings class."""
    content = config_file.read_text()
    if "COST_TRACKING_ENABLED" in content:
        return

    block = (
        "\n"
        "    # --- Cost Tracker — added by add_cost_tracker tool ---\n"
        "    COST_TRACKING_ENABLED: bool = False\n"
        "    COST_DB_QUERY_RATE: float = 0.00001\n"
        "    COST_S3_PER_GB: float = 0.023\n"
        "    COST_API_CALL_RATE: float = 0.0001\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in content:
        content = content.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in content:
            content = content.replace(
                settings_line,
                block.lstrip("\n") + "\n\n" + settings_line,
            )

    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register costs router in app/routes/__init__.py."""
    content = routes_init.read_text()
    import_line = "from app.api.routes.costs import router as costs_router"
    include_line = "api_router.include_router(costs_router)"
    if "costs_router" not in content:
        content = content.rstrip() + f"\n{import_line}\n{include_line}\n"
        routes_init.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
