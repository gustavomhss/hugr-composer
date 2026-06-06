<!--
{
  "tool_num": "041",
  "tool_name": "error_rate_analyzer",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 1705.6518947430013,
  "prompt_tokens": 48808,
  "completion_tokens": 11775,
  "cost_usd": 0.03972291,
  "calls": 6
}
-->

# TOOL-041: error_rate_analyzer

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_error_rate_analyzer` |
| Category | OPERATE |
| Complexity | High |
| Dependencies | FastAPI, structlog, Prometheus, optional Loki |
| Signature | `error_rate_analyzer(project_dir: str, lookback_hours: int = 24, group_by: list[str] | None = None, threshold_5xx_pct: float = 1.0, threshold_4xx_pct: float = 5.0, sink: str = "prometheus") -> dict` |
| Parameters | `project_dir`: project root<br>`lookback_hours`: retention window for in-memory aggregation<br>`group_by`: dimensions to aggregate by, e.g., `["route","status","user_id"]`<br>`threshold_5xx_pct`: alert if 5xx rate exceeds this percentage<br>`threshold_4xx_pct`: alert if 4xx rate exceeds this percentage<br>`sink`: `prometheus`, `loki`, or `console` |

## 2. Purpose

The `fastapi_error_rate_analyzer` aggregates and categorizes errors across all routes in a FastAPI application, answering "which endpoints are breaking and for whom?". It groups 4xx/5xx errors by route, status code, and optional user dimension, exposing live error rates via Prometheus and writing structured log events to Loki. The tool computes sliding windows (1m, 5m, 1h) to enable operators to spot spikes immediately and generates trend reports (e.g., "error rate for /orders up 300% over last hour"). It classifies errors into "expected" (4xx validation) vs "unexpected" (5xx), routing alerts accordingly. Without this tool, operators risk losing visibility into endpoint failures until customers report issues. The analyzer integrates as FastAPI middleware, ensuring it captures every response without blocking the request path.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Middleware overhead | < 100 µs per request | Ensures minimal impact on request latency |
| Files modified | ≤ 3 (main.py, config.py, pyproject.toml) | Limits changes to core project files |
| Files created | ≥ 8 (middleware, aggregator, metrics, alert rules, dashboard, tests, docs, Makefile) | Provides comprehensive tooling and documentation |
| Metric export | < 50 ms | Keeps Prometheus scrape times low |
| Memory overhead | Max 10 MB for 24h window at 1k rps | Prevents excessive memory usage |
| Migration runtime | 0s — no DB changes | Ensures zero downtime during deployment |
| Alert latency | < 1s from threshold breach | Guarantees timely notifications |
| Cardinality | < 1000 unique label combinations | Prevents Prometheus label explosion |

---

## 4. Code Examples (Before / After)

### 4.1 Middleware: BEFORE
```python
# app/middleware/base.py
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class BaseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        return await call_next(request)
```

### 4.2 Middleware: AFTER
```python
# app/middleware/error_rate.py
from fastapi import Request
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time


HTTP_ERRORS_TOTAL = Counter(
    "http_errors_total",
    "Total HTTP errors by route and status class",
    ["route_pattern", "status_class", "user_tier"]
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["route_pattern"]
)


class ErrorRateMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, route_patterns: dict[str, str]):
        super().__init__(app)
        self.route_patterns = route_patterns

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        path = request.url.path
        route_pattern = self._resolve_route_pattern(path)
        user_tier = getattr(request.state, "user_tier", "anonymous")

        try:
            response = await call_next(request)
            status_class = f"{response.status_code // 100}xx"
            if status_class in ("4xx", "5xx"):
                HTTP_ERRORS_TOTAL.labels(
                    route_pattern=route_pattern,
                    status_class=status_class,
                    user_tier=user_tier
                ).inc()
        except Exception:
            HTTP_ERRORS_TOTAL.labels(
                route_pattern=route_pattern,
                status_class="5xx",
                user_tier=user_tier
            ).inc()
            raise

        HTTP_REQUEST_DURATION.labels(route_pattern=route_pattern).observe(
            time.time() - start_time
        )
        return response

    def _resolve_route_pattern(self, path: str) -> str:
        return next(
            (pattern for pattern in self.route_patterns if path.startswith(pattern)),
            "unknown_route"
        )
```

### 4.3 Error Aggregator (NEW)
```python
# app/services/error_aggregator.py
from collections import defaultdict
from datetime import datetime, timedelta
from typing import DefaultDict, Dict, Tuple
import threading


class ErrorAggregator:
    def __init__(self, lookback_hours: int = 24):
        self.lookback = timedelta(hours=lookback_hours)
        self.data: DefaultDict[str, Dict[Tuple[str, str, str], int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.timestamps: Dict[Tuple[str, str, str, str], datetime] = {}
        self.lock = threading.Lock()

    def record(
        self,
        route_pattern: str,
        status_class: str,
        error_type: str,
        user_tier: str
    ) -> None:
        key = (route_pattern, status_class, error_type, user_tier)
        with self.lock:
            self.data[user_tier][(route_pattern, status_class, error_type)] += 1
            self.timestamps[key] = datetime.now()

    def prune_old_entries(self) -> None:
        cutoff = datetime.now() - self.lookback
        with self.lock:
            for user_tier in list(self.data.keys()):
                for key in list(self.data[user_tier].keys()):
                    lookup_key = (*key, user_tier)
                    if self.timestamps.get(lookup_key, datetime.min) < cutoff:
                        del self.data[user_tier][key]
                        del self.timestamps[lookup_key]

    def get_error_rates(self, window: timedelta) -> Dict[Tuple[str, str, str], float]:
        self.prune_old_entries()
        cutoff = datetime.now() - window
        with self.lock:
            return {
                key: count / window.total_seconds()
                for user_tier, counts in self.data.items()
                for key, count in counts.items()
                if self.timestamps.get((*key, user_tier), datetime.min) >= cutoff
            }
```

### 4.4 Alert Manager (NEW)
```python
# app/services/alert_manager.py
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional
import threading


class AlertType(Enum):
    HIGH_5XX = "high_5xx_rate"
    HIGH_4XX = "high_4xx_rate"
    TREND_UP = "error_rate_trend_up"


class AlertManager:
    def __init__(self):
        self.active_alerts: Dict[str, datetime] = {}
        self.lock = threading.Lock()

    def check_thresholds(
        self,
        error_rates: Dict[Tuple[str, str, str], float],
        threshold_5xx: float,
        threshold_4xx: float
    ) -> Dict[AlertType, bool]:
        with self.lock:
            results = {
                AlertType.HIGH_5XX: False,
                AlertType.HIGH_4XX: False
            }
            
            for (_, status_class, _), rate in error_rates.items():
                if status_class == "5xx" and rate > threshold_5xx:
                    results[AlertType.HIGH_5XX] = True
                elif status_class == "4xx" and rate > threshold_4xx:
                    results[AlertType.HIGH_4XX] = True
            
            return results

    def fire_alert(self, alert_type: AlertType) -> None:
        with self.lock:
            self.active_alerts[alert_type.value] = datetime.now()

    def resolve_alert(self, alert_type: AlertType) -> None:
        with self.lock:
            self.active_alerts.pop(alert_type.value, None)

    def is_alert_active(self, alert_type: AlertType) -> bool:
        with self.lock:
            return alert_type.value in self.active_alerts
```

### 4.5 Error Rate API (NEW)
```python
# app/api/error_rates.py
from fastapi import APIRouter, Depends
from app.services.error_aggregator import ErrorAggregator
from app.services.alert_manager import AlertManager, AlertType
from pydantic import BaseModel
from datetime import timedelta
from typing import List


router = APIRouter()


class ErrorRateResponse(BaseModel):
    route: str
    status_class: str
    error_type: str
    rate_per_min: float


class AlertStatusResponse(BaseModel):
    alert_type: str
    is_active: bool
    since: Optional[str]


@router.get("/rates", response_model=List[ErrorRateResponse])
async def get_error_rates(
    aggregator: ErrorAggregator = Depends(),
    window_min: int = 5
):
    rates = aggregator.get_error_rates(timedelta(minutes=window_min))
    return [
        ErrorRateResponse(
            route=route,
            status_class=status_class,
            error_type=error_type,
            rate_per_min=rate * 60  # Convert to per-minute rate
        )
        for (route, status_class, error_type), rate in rates.items()
    ]


@router.get("/alerts", response_model=List[AlertStatusResponse])
async def get_active_alerts(
    alert_manager: AlertManager = Depends()
):
    return [
        AlertStatusResponse(
            alert_type=alert.value,
            is_active=alert_manager.is_alert_active(alert),
            since=alert_manager.active_alerts.get(alert.value, None)
        )
        for alert in AlertType
    ]
```

### 4.6 Configuration (NEW)
```python
# app/core/config.py
from pydantic import BaseSettings
from typing import List


class ErrorRateConfig(BaseSettings):
    ERROR_RATE_LOOKBACK_HOURS: int = 24
    ERROR_RATE_5XX_THRESHOLD: float = 1.0  # 1% threshold
    ERROR_RATE_4XX_THRESHOLD: float = 5.0  # 5% threshold
    ERROR_RATE_ROUTE_PATTERNS: List[str] = [
        "/api/v1/auth",
        "/api/v1/users",
        "/api/v1/orders"
    ]
    ERROR_RATE_METRIC_PREFIX: str = "fastapi_errors"
    ERROR_RATE_LOG_SINK: str = "prometheus"  # or "loki", "console"

    class Config:
        env_file = ".env"
        env_prefix = "ERROR_RATE_"


config = ErrorRateConfig()
```

### 4.7 Structured Logging (NEW)
```python
# app/core/logging.py
import structlog
from typing import Optional
from uuid import UUID
from datetime import datetime


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.PrintLoggerFactory()
    )


def log_error(
    route_pattern: str,
    status_code: int,
    error_type: str,
    user_id: Optional[UUID] = None,
    trace_id: Optional[str] = None,
    exception: Optional[str] = None
) -> None:
    logger = structlog.get_logger("error_rate")
    logger.error(
        "http_error",
        route=route_pattern,
        status=status_code,
        type=error_type,
        user=str(user_id) if user_id else None,
        trace=trace_id or "no-trace",
        exception=exception,
        timestamp=datetime.utcnow().isoformat()
    )
```

### 4.8 Migration (NEW)
```python
# alembic/versions/0009_add_error_rate_tables.py
"""Add error rate monitoring tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "error_rate_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("route_pattern", sa.String(255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(32), nullable=False),
        sa.Column("user_tier", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index("ix_error_rate_metrics_timestamp", "timestamp"),
        sa.Index(
            "ix_error_rate_metrics_route_status",
            "route_pattern",
            "status_code"
        ),
    )

    op.create_table(
        "error_rate_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("first_triggered", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Index("ix_error_rate_alerts_active", "is_active"),
        sa.Index("ix_error_rate_alerts_type", "alert_type"),
    )


def downgrade() -> None:
    op.drop_table("error_rate_alerts")
    op.drop_table("error_rate_metrics")
```

### 4.9 CLI Command (NEW)
```python
# app/cli/error_rates.py
import typer
from datetime import timedelta
from typing import Optional
from app.services.error_aggregator import ErrorAggregator
from app.core.logging import configure_logging


app = typer.Typer()
configure_logging()


@app.command()
def show_rates(
    window_min: int = typer.Option(5, help="Time window in minutes"),
    route: Optional[str] = typer.Option(None, help="Filter by route pattern"),
    status: Optional[str] = typer.Option(None, help="Filter by status class (4xx,5xx)")
):
    aggregator = ErrorAggregator()
    rates = aggregator.get_error_rates(timedelta(minutes=window_min))
    
    filtered = [
        (route_pattern, status_class, error_type, rate)
        for (route_pattern, status_class, error_type), rate in rates.items()
        if (route is None or route in route_pattern)
        and (status is None or status == status_class)
    ]
    
    for route_pattern, status_class, error_type, rate in sorted(
        filtered, key=lambda x: x[3], reverse=True
    ):
        print(
            f"{route_pattern:<30} {status_class:<4} {error_type:<10} "
            f"{rate * 60:.2f} errors/min"
        )

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Middleware NEVER throws on its own errors** | `ErrorRateMiddleware` wraps all logic in try/except with fallback logging via `structlog.get_logger()` in `app/middleware/error_rate.py` |
| QS-2 | **Labels are ALWAYS bounded to prevent cardinality explosion** | Route patterns normalized via `route_pattern()` function in `app/core/utils.py` before Prometheus label assignment |
| QS-3 | **4xx and 5xx errors are ALWAYS counted separately** | `HTTP_ERRORS_TOTAL` counter in `app/middleware/error_rate.py` uses distinct `status_class` labels for 4xx vs 5xx |
| QS-4 | **Alerts ALWAYS fire through the configured sink** | `AlertManager` class in `app/core/alerts.py` validates sink connectivity before sending and retries on failure |
| QS-5 | **Cardinality is ALWAYS < 1000 unique label combinations** | `CardinalityLimiter` middleware in `app/middleware/cardinality.py` rejects new label combinations beyond threshold |
| QS-6 | **Trace IDs are ALWAYS propagated to log entries** | `TracePropagator` extension in `app/extensions/trace.py` injects trace context into structlog via `structlog.contextvars.bind_contextvars()` |
| QS-7 | **Error classification is DETERMINISTIC given same inputs** | `ErrorClassifier` class in `app/core/classification.py` uses pure functions with no side effects for classification |
| QS-8 | **Middleware overhead ALWAYS < 100 µs per request** | `BenchmarkMiddleware` in `app/middleware/benchmark.py` measures and logs timing for each request |
| QS-9 | **Memory usage ALWAYS bounded by lookback window** | `ErrorAggregator.prune_old()` method in `app/core/aggregator.py` removes entries older than `lookback_hours` |
| QS-10 | **Tool is ALWAYS idempotent on re-run** | `IdempotencyChecker` class in `app/core/idempotency.py` verifies no duplicate metrics or logs created |
| QS-11 | **Custom classifiers ALWAYS fall back to default on error** | `SafeClassifier` wrapper in `app/core/classification.py` catches and logs exceptions from custom classifiers |
| QS-12 | **Alert windows ALWAYS roll without duplicates** | `WindowManager` class in `app/core/windows.py` uses atomic timestamps to prevent overlapping alerts |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `ErrorRateMiddleware` exists at `app/middleware/error_rate.py` | File exists, parses |
| CC-02 | `HTTP_ERRORS_TOTAL` counter declared with correct labels | Inspect `app/middleware/error_rate.py` |
| CC-03 | `HTTP_REQUEST_DURATION` histogram declared with route label | Inspect `app/middleware/error_rate.py` |
| CC-04 | `ErrorAggregator` class exists at `app/core/aggregator.py` | File exists, contains `record()` method |
| CC-05 | `ErrorRateResponse` schema exists at `app/schemas/error_rate.py` | File exists, contains `route`, `status_class`, `count` fields |
| CC-06 | `ErrorTrendResponse` schema exists at `app/schemas/error_rate.py` | File exists, contains `current_rate`, `baseline_rate`, `trend` fields |
| CC-07 | `/error-rates` endpoint exists at `app/api/endpoints/error_rate.py` | grep `@router.get("/error-rates"` |
| CC-08 | `/error-trends` endpoint exists at `app/api/endpoints/error_rate.py` | grep `@router.get("/error-trends"` |
| CC-09 | `ERROR_RATE_LOOKBACK_HOURS` setting exists in `app/core/config.py` | grep `ERROR_RATE_LOOKBACK_HOURS` |
| CC-10 | `ERROR_RATE_THRESHOLD_5XX_PCT` setting exists in `app/core/config.py` | grep `ERROR_RATE_THRESHOLD_5XX_PCT` |
| CC-11 | `ERROR_RATE_THRESHOLD_4XX_PCT` setting exists in `app/core/config.py` | grep `ERROR_RATE_THRESHOLD_4XX_PCT` |
| CC-12 | `ERROR_RATE_SINK` setting exists in `app/core/config.py` | grep `ERROR_RATE_SINK` |
| CC-13 | `ERROR_RATE_GROUP_BY` setting exists in `app/core/config.py` | grep `ERROR_RATE_GROUP_BY` |
| CC-14 | Prometheus alert rules YAML exists at `config/prometheus/alerts.yml` | File exists, contains `http_errors_total` rule |
| CC-15 | Grafana dashboard JSON exists at `config/grafana/dashboards/error_rates.json` | File exists, contains `HTTP Errors` panel |
| CC-16 | `ErrorRateMiddleware` registered in `main.py` after auth middleware | grep `app.add_middleware(ErrorRateMiddleware` |
| CC-17 | `ErrorAggregator` dependency injected into endpoints | grep `aggregator: ErrorAggregator = Depends()` |
| CC-18 | `ErrorRateMiddleware` handles exceptions without throwing | Inspect `try/except` block in `dispatch()` |
| CC-19 | Route patterns normalized before label assignment | Inspect `route_pattern()` function in `app/core/utils.py` |
| CC-20 | Custom classifier interface exists at `app/core/classification.py` | File exists, contains `classify()` method |
| CC-21 | `CardinalityLimiter` middleware exists at `app/middleware/cardinality.py` | File exists, contains `1000` threshold |
| CC-22 | `TracePropagator` extension exists at `app/extensions/trace.py` | File exists, contains `bind_contextvars()` call |
| CC-23 | `BenchmarkMiddleware` exists at `app/middleware/benchmark.py` | File exists, contains timing measurement |
| CC-24 | `IdempotencyChecker` exists at `app/core/idempotency.py` | File exists, contains duplicate detection |
| CC-25 | `SafeClassifier` wrapper exists at `app/core/classification.py` | File exists, contains exception handling |
| CC-26 | `WindowManager` exists at `app/core/windows.py` | File exists, contains atomic timestamp logic |
| CC-27 | Existing test suite passes | pytest 0 failures |
| CC-28 | New file `tests/test_error_rate.py` created with 30 tests | File exists |
| CC-29 | All target models verified with `ast.parse` after edit | Tool internal step |
| CC-30 | Tool execution time < 5s | Time measurement |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] Middleware overhead < 100 µs per request (T-30)
- [ ] Memory usage < 10 MB for 24h window at 1k rps (T-29)
- [ ] Prometheus metrics exported in < 50 ms (T-28)
- [ ] Alert latency < 1s from threshold breach (T-27)
- [ ] Cardinality < 1000 unique label combinations (T-26)
- [ ] Existing test suite passes with 0 failures
- [ ] New test file `tests/test_error_rate.py` created with 30 tests
- [ ] Grafana dashboard JSON created at `config/grafana/dashboards/error_rates.json`
- [ ] Prometheus alert rules YAML created at `config/prometheus/alerts.yml`
- [ ] Documentation created at `docs/error_rate_analyzer.md`
- [ ] Makefile targets for install/run/test created
- [ ] CI/CD pipeline updated to include new tests and metrics

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ERA-01 | Middleware NEVER throws on its own errors | `ErrorRateMiddleware` wraps all logic in try/except with fallback logging via `structlog.get_logger()` in `app/middleware/error_rate.py` | T-01, T-02 |
| INV-ERA-02 | Labels are ALWAYS bounded to prevent cardinality explosion | Route patterns normalized via `route_pattern()` function in `app/core/utils.py` before Prometheus label assignment | T-03, T-04 |
| INV-ERA-03 | 4xx and 5xx errors are ALWAYS counted separately | `HTTP_ERRORS_TOTAL` counter in `app/middleware/error_rate.py` uses distinct `status_class` labels for 4xx vs 5xx | T-05, T-06 |
| INV-ERA-04 | Alerts ALWAYS fire through the configured sink | `AlertManager` class in `app/core/alerts.py` validates sink connectivity before sending and retries on failure | T-07, T-08 |
| INV-ERA-05 | Cardinality is ALWAYS < 1000 unique label combinations | `CardinalityLimiter` middleware in `app/middleware/cardinality.py` rejects new label combinations beyond threshold | T-09, T-10 |
| INV-ERA-06 | Trace IDs are ALWAYS propagated to log entries | `TracePropagator` extension in `app/extensions/trace.py` injects trace context into structlog via `structlog.contextvars.bind_contextvars()` | T-11, T-12 |
| INV-ERA-07 | Error classification is DETERMINISTIC given same inputs | `ErrorClassifier` class in `app/core/classification.py` uses pure functions with no side effects for classification | T-13, T-14 |
| INV-ERA-08 | Middleware overhead ALWAYS < 100 µs per request | `BenchmarkMiddleware` in `app/middleware/benchmark.py` measures and logs timing for each request | T-15, T-16 |

---

## 9. User Stories

### 9.1 Core Functionality (US-01 .. US-05)

**US-01: Track 4xx and 5xx errors separately**
- **As a** backend engineer
- **I want** to track client (4xx) and server (5xx) errors separately
- **So that** I can distinguish between user input issues and system failures
- **Given:** `/orders` route with 400 and 500 responses
- **When:** Requests return 400 and 500 status codes
- **Then:**
  - `HTTP_ERRORS_TOTAL` counter increments for `status_class="4xx"` (INV-ERA-03)
  - `HTTP_ERRORS_TOTAL` counter increments for `status_class="5xx"` (INV-ERA-03)
  - Separate Prometheus metrics for 4xx and 5xx (CC-02)

**US-02: Label errors by route**
- **As a** site reliability engineer
- **I want** to see which routes are failing
- **So that** I can prioritize fixes for high-traffic endpoints
- **Given:** `/orders` and `/users` routes
- **When:** Requests to `/orders` return 500
- **Then:**
  - `HTTP_ERRORS_TOTAL` counter labels include `route="/orders"` (INV-ERA-02)
  - Grafana dashboard shows `/orders` in error rate panel (CC-15)
  - Route pattern normalized to prevent cardinality explosion (T-03)

**US-03: Track user tier for errors**
- **As a** product manager
- **I want** to see which user tiers are experiencing errors
- **So that** I can prioritize fixes for paying customers
- **Given:** Request with `user_tier="premium"`
- **When:** Request to `/orders` returns 500
- **Then:**
  - `HTTP_ERRORS_TOTAL` counter labels include `user_tier="premium"` (CC-02)
  - Error logged with `user_tier="premium"` (CC-18)
  - Cardinality remains below 1000 combinations (INV-ERA-05)

**US-04: Measure request latency**
- **As a** performance engineer
- **I want** to track how long requests take
- **So that** I can identify slow endpoints
- **Given:** `/orders` route with 200ms response time
- **When:** Request completes successfully
- **Then:**
  - `HTTP_REQUEST_DURATION` histogram records 0.2s (CC-03)
  - Grafana dashboard shows `/orders` latency (CC-15)
  - Middleware overhead remains < 100 µs (INV-ERA-08)

**US-05: Aggregate errors over time**
- **As a** data analyst
- **I want** to see error trends over the last hour
- **So that** I can spot spikes in failures
- **Given:** `/orders` route with increasing errors
- **When:** Querying `/error-trends`
- **Then:**
  - Response includes `current_rate` and `baseline_rate` (CC-06)
  - Trend marked as "up" if rate exceeds baseline (CC-08)
  - Data pruned after 24 hours (INV-ERA-09)

### 9.2 Alerting & Thresholds (US-06 .. US-10)

**US-06: Alert on 5xx threshold breach**
- **As a** on-call engineer
- **I want** to be notified when 5xx errors exceed 1%
- **So that** I can investigate server failures immediately
- **Given:** `/orders` route with 5% 5xx rate
- **When:** Error rate exceeds `threshold_5xx_pct=1.0`
- **Then:**
  - Prometheus alert fires (CC-14)
  - Alert sent via configured sink (INV-ERA-04)
  - Alert latency < 1s (T-27)

**US-07: Alert on 4xx threshold breach**
- **As a** product owner
- **I want** to be notified when 4xx errors exceed 5%
- **So that** I can improve client-side validation
- **Given:** `/users` route with 10% 4xx rate
- **When:** Error rate exceeds `threshold_4xx_pct=5.0`
- **Then:**
  - Prometheus alert fires (CC-14)
  - Alert sent via configured sink (INV-ERA-04)
  - Alert latency < 1s (T-27)

**US-08: Console sink for local development**
- **As a** developer
- **I want** to see error rates in my console
- **So that** I can debug locally without Prometheus
- **Given:** `sink="console"` in config
- **When:** `/orders` returns 500
- **Then:**
  - Error logged to stdout (CC-18)
  - No Prometheus metrics exported (CC-12)
  - Console output includes route and status (T-01)

**US-09: Loki sink for structured logs**
- **As a** log analyst
- **I want** errors logged to Loki
- **So that** I can correlate errors with traces
- **Given:** `sink="loki"` in config
- **When:** `/orders` returns 500
- **Then:**
  - Structured log sent to Loki (CC-18)
  - Log includes trace ID (INV-ERA-06)
  - Fallback to stdout if Loki unavailable (T-08)

**US-10: Reset thresholds after breach**
- **As a** site reliability engineer
- **I want** thresholds to reset after a breach
- **So that** I don't receive duplicate alerts
- **Given:** `/orders` route with 5xx breach
- **When:** Error rate drops below threshold
- **Then:**
  - Alert resolves (CC-14)
  - No duplicate alerts sent (INV-ERA-12)
  - Window rolls without overlap (T-24)

### 9.3 Edge Cases & Resilience (US-11 .. US-15)

**US-11: Handle middleware exceptions**
- **As a** developer
- **I want** the middleware to handle its own errors
- **So that** requests complete even if monitoring fails
- **Given:** Middleware raises an exception
- **When:** Request to `/orders` is processed
- **Then:**
  - Request completes successfully (INV-ERA-01)
  - Error logged via fallback logger (T-02)
  - Middleware overhead remains < 100 µs (INV-ERA-08)

**US-12: Skip WebSocket connections**
- **As a** real-time systems engineer
- **I want** WebSocket connections to be ignored
- **So that** I don't track non-HTTP errors
- **Given:** WebSocket upgrade request
- **When:** Connection upgrades to WebSocket
- **Then:**
  - No error metrics recorded (CC-02)
  - No latency measurement (CC-03)
  - Middleware skips silently (T-01)

**US-13: Handle missing trace ID**
- **As a** trace analyst
- **I want** errors without trace IDs to be logged
- **So that** I can still investigate issues
- **Given:** Request without trace context
- **When:** `/orders` returns 500
- **Then:**
  - Error logged with `trace_id="no-trace"` (INV-ERA-06)
  - Metrics still recorded (CC-02)
  - Log entry includes route and status (T-12)

**US-14: Cap high cardinality user IDs**
- **As a** Prometheus administrator
- **I want** user IDs to be grouped by tier
- **So that** I avoid label explosion
- **Given:** Request with `user_id="12345"`
- **When:** `/orders` returns 500
- **Then:**
  - Metrics labeled by `user_tier` only (INV-ERA-05)
  - Cardinality remains < 1000 (T-10)
  - Log entry includes `user_tier` (CC-18)

**US-15: Handle streaming responses**
- **As a** backend engineer
- **I want** streaming errors to be captured
- **So that** I can monitor long-running requests
- **Given:** Streaming response from `/stream`
- **When:** Stream aborts with 500
- **Then:**
  - Error captured on abort (CC-02)
  - Latency measured for full stream (CC-03)
  - Middleware overhead remains < 100 µs (INV-ERA-08)

### 9.4 Integration & Configuration (US-16 .. US-20)

**US-16: Configure lookback window**
- **As a** system administrator
- **I want** to set the error retention period
- **So that** I can balance memory usage and history
- **Given:** `lookback_hours=48` in config
- **When:** Querying `/error-rates`
- **Then:**
  - Data retained for 48 hours (CC-09)
  - Memory usage bounded (INV-ERA-09)
  - Old data pruned automatically (T-29)

**US-17: Custom error classification**
- **As a** domain expert
- **I want** to classify errors based on business rules
- **So that** I can prioritize critical failures
- **Given:** Custom classifier in `app/core/classification.py`
- **When:** `/orders` returns 500
- **Then:**
  - Error classified by custom rules (CC-20)
  - Fallback to default on classifier error (INV-ERA-11)
  - Classification deterministic (INV-ERA-07)

**US-18: Idempotent tool execution**
- **As a** DevOps engineer
- **I want** the tool to be idempotent
- **So that** I can re-run it safely
- **Given:** Tool already configured
- **When:** Running `error_rate_analyzer` again
- **Then:**
  - No duplicate metrics created (INV-ERA-10)
  - No duplicate logs written (CC-18)
  - Tool reports "already configured" (CC-24)

**US-19: Validate sink connectivity**
- **As a** reliability engineer
- **I want** the tool to validate sink connectivity
- **So that** I don't lose alerts
- **Given:** Prometheus unreachable
- **When:** `/orders` returns 500
- **Then:**
  - Metrics buffered in memory (CC-02)
  - Alert retried until successful (INV-ERA-04)
  - Fallback to console if all sinks fail (T-08)

**US-20: Configure group-by dimensions**
- **As a** data engineer
- **I want** to customize aggregation dimensions
- **So that** I can analyze errors by relevant factors
- **Given:** `group_by=["route", "status_class", "user_tier"]`
- **When:** Querying `/error-rates`
- **Then:**
  - Response grouped by specified dimensions (CC-13)
  - Cardinality remains < 1000 (INV-ERA-05)
  - Grafana dashboard reflects grouping (CC-15)

### 9.5 Performance & Observability (US-21 .. US-25)

**US-21: Handle 1000 rps load**
- **As a** performance engineer
- **I want** the middleware to handle high traffic
- **So that** I can monitor production systems
- **Given:** 1000 requests per second
- **When:** Monitoring `/orders`
- **Then:**
  - Middleware overhead < 100 µs (INV-ERA-08)
  - Memory usage < 10 MB (INV-ERA-09)
  - No dropped metrics (CC-02)

**US-22: Measure alert latency**
- **As a** on-call engineer
- **I want** alerts to fire within 1 second
- **So that** I can respond quickly to outages
- **Given:** `/orders` route with 5xx breach
- **When:** Error rate exceeds threshold
- **Then:**
  - Alert fires within 1s (T-27)
  - Alert sent via configured sink (INV-ERA-04)
  - No duplicate alerts (INV-ERA-12)

**US-23: Monitor middleware overhead**
- **As a** site reliability engineer
- **I want** to track middleware performance
- **So that** I can ensure low latency
- **Given:** `/orders` route with 200ms response
- **When:** Request completes successfully
- **Then:**
  - Middleware overhead < 100 µs (INV-ERA-08)
  - Latency measured accurately (CC-03)
  - No impact on request timing (T-16)

**US-24: Validate cardinality limits**
- **As a** Prometheus administrator
- **I want** to ensure label cardinality is bounded
- **So that** I avoid Prometheus OOM
- **Given:** High-traffic routes with many users
- **When:** Monitoring `/orders`
- **Then:**
  - Cardinality < 1000 unique combinations (INV-ERA-05)
  - Labels normalized (INV-ERA-02)
  - No label explosion (T-10)

**US-25: Verify idempotency**
- **As a** DevOps engineer
- **I want** the tool to be idempotent
- **So that** I can re-run it safely
- **Given:** Tool already configured
- **When:** Running `error_rate_analyzer` again
- **Then:**
  - No duplicate metrics created (INV-ERA-10)
  - No duplicate logs written (CC-18)
  - Tool reports "already configured" (CC-24)

---

## 10. Test Plan

### 10.1 Middleware Functionality

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Middleware handles 200 OK | `/orders` route returns 200 | GET /orders | `HTTP_ERRORS_TOTAL` unchanged, latency recorded |
| T-02 | Middleware handles 404 | `/unknown` route | GET /unknown | `HTTP_ERRORS_TOTAL` increments with `status_class="4xx"` |
| T-03 | Middleware handles 500 | `/orders` route raises Exception | GET /orders | `HTTP_ERRORS_TOTAL` increments with `status_class="5xx"` |
| T-04 | Middleware handles exception | Middleware raises RuntimeError | GET /orders | Request completes, error logged via fallback logger |
| T-05 | Middleware skips WebSocket | WebSocket upgrade request | Upgrade connection | No metrics recorded |
| T-06 | Middleware overhead < 100 µs | `/orders` route with 200ms response | GET /orders | Middleware timing < 100 µs |

### 10.2 Aggregation & Counting

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Count 4xx separately | `/orders` returns 400 | GET /orders | `HTTP_ERRORS_TOTAL` increments with `status_class="4xx"` |
| T-08 | Count 5xx separately | `/orders` returns 500 | GET /orders | `HTTP_ERRORS_TOTAL` increments with `status_class="5xx"` |
| T-09 | Aggregate by route | `/orders` and `/users` return 500 | GET /orders, GET /users | Separate counts for `/orders` and `/users` |
| T-10 | Aggregate by user tier | Request with `user_tier="premium"` | GET /orders | `HTTP_ERRORS_TOTAL` labels include `user_tier="premium"` |
| T-11 | Cardinality < 1000 | 1000 unique user IDs | GET /orders | Cardinality remains < 1000, metrics grouped by `user_tier` |
| T-12 | Prune old data | Data older than 24 hours | Query `/error-rates` | Old data removed, only recent data returned |

### 10.3 Alerting & Thresholds

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Alert on 5xx threshold | `/orders` with 5% 5xx rate | GET /orders | Prometheus alert fires |
| T-14 | Alert on 4xx threshold | `/users` with 10% 4xx rate | GET /users | Prometheus alert fires |
| T-15 | Console sink | `sink="console"` in config | GET /orders | Error logged to stdout |
| T-16 | Loki sink | `sink="loki"` in config | GET /orders | Structured log sent to Loki |
| T-17 | Alert latency < 1s | `/orders` with 5xx breach | GET /orders | Alert fires within 1s |
| T-18 | Reset thresholds | `/orders` 5xx rate drops below threshold | GET /orders | Alert resolves, no duplicates |

### 10.4 Classification & Logging

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Classify 4xx as expected | `/orders` returns 400 | GET /orders | Error classified as "expected" |
| T-20 | Classify 5xx as unexpected | `/orders` returns 500 | GET /orders | Error classified as "unexpected" |
| T-21 | Custom classifier | Custom classifier in `app/core/classification.py` | GET /orders | Error classified by custom rules |
| T-22 | Fallback on classifier error | Custom classifier raises Exception | GET /orders | Fallback to default classification |
| T-23 | Trace ID propagation | Request with trace ID | GET /orders | Log entry includes trace ID |
| T-24 | Missing trace ID | Request without trace ID | GET /orders | Log entry includes `trace_id="no-trace"` |

### 10.5 Edge Cases & Resilience

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Handle middleware exceptions | Middleware raises RuntimeError | GET /orders | Request completes, error logged |
| T-26 | Handle high cardinality | 1000 unique user IDs | GET /orders | Cardinality remains < 1000 |
| T-27 | Handle streaming responses | Streaming response from `/stream` | GET /stream | Error captured on abort |
| T-28 | Handle missing user context | Request without user context | GET /orders | Metrics labeled with `user_tier="anonymous"` |
| T-29 | Handle Prometheus scrape failure | Prometheus unreachable | GET /orders | Metrics buffered in memory |
| T-30 | Tool idempotency | Tool already configured | Run `error_rate_analyzer` again | No duplicate metrics or logs |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Error rate analyzer must run BEFORE soft delete to capture all errors, including those from soft-deleted records |
| add_cursor_pagination | No | ✅ Compatible | Pagination affects query results but not error rates, which are tracked per request |
| add_search | No | ✅ Compatible | Search errors are captured as 4xx/5xx responses and included in error rate metrics |
| add_audit_log | Yes | ⚠️ Caveat | Audit logs must run AFTER error rate analyzer to include error metadata in audit entries |
| add_data_export | No | ✅ Compatible | Export failures are captured as 5xx errors and included in error rate metrics |
| add_bulk_operations | No | ✅ Compatible | Bulk operation errors are captured as 4xx/5xx responses and aggregated |
| add_multi_tenancy | Yes | ✅ Compatible | Error rate analyzer must run AFTER tenant middleware to include tenant context in error metrics |
| add_feature_flags | No | ✅ Compatible | Feature flag evaluation errors are captured as 5xx responses and included in error rates |
| add_api_key_auth | Yes | ✅ Compatible | API key validation errors are captured as 4xx responses and must run BEFORE error rate analyzer |
| add_oauth2_provider | Yes | ✅ Compatible | OAuth2 token validation errors are captured as 4xx responses and must run BEFORE error rate analyzer |
| add_rbac | Yes | ✅ Compatible | RBAC permission errors are captured as 4xx responses and must run BEFORE error rate analyzer |
| add_mfa | Yes | ✅ Compatible | MFA verification errors are captured as 4xx responses and must run BEFORE error rate analyzer |
| add_cache_layer | No | ✅ Compatible | Cache misses and errors are captured as 5xx responses and included in error rates |
| add_outbox_pattern | No | ✅ Compatible | Outbox processing errors are captured as 5xx responses and included in error rates |
| add_sse | No | ✅ Compatible | SSE connection errors are captured as 5xx responses and included in error rates |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout main.py config.py pyproject.toml
rm -rf app/middleware/error_rate.py app/core/aggregator.py app/schemas/error_rate.py \
       app/api/endpoints/error_rate.py app/core/config.py app/core/logger.py \
       config/prometheus/alerts.yml config/grafana/dashboards/error_rates.json \
       docs/error_rate_analyzer.md Makefile tests/test_error_rate.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status  # Identify modified files
git checkout main.py config.py pyproject.toml  # Restore core files
rm -rf app/middleware/error_rate.py app/core/aggregator.py  # Remove new files
```

### Emergency: Prometheus label explosion
1. Scale down Prometheus deployment
2. Delete high-cardinality metrics: `curl -X POST http://localhost:9090/api/v1/admin/tsdb/delete_series?match[]={__name__=~"http_errors_total.*"}`
3. Restart Prometheus with reduced retention: `--storage.tsdb.retention.time=1h`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Route not in registry | Tool labels errors as `unknown_route` to prevent unbounded cardinality |
| EC-2 | 0 requests in window | Tool reports 0 error rate and suppresses alerts |
| EC-3 | 100% 5xx rate | Tool fires alert and logs each error with route and status |
| EC-4 | Middleware raises exception | Request completes successfully, error logged via fallback logger |
| EC-5 | Request without user context | Tool labels metrics with `user_tier=anonymous` |
| EC-6 | High cardinality user IDs | Tool groups metrics by user tier only, not individual IDs |
| EC-7 | Trace ID missing | Tool includes `trace_id="no-trace"` in log entries |
| EC-8 | Structured log sink down | Tool falls back to stdout logging with same format |
| EC-9 | Prometheus scrape fails | Metrics are buffered in memory until next successful scrape |
| EC-10 | Tool re-run | Tool detects existing setup and skips redundant changes |
| EC-11 | Alert window boundary | Tool uses atomic timestamps to prevent duplicate alerts |
| EC-12 | Custom classifier raises | Tool falls back to default 4xx/5xx classification |
| EC-13 | Streaming response aborts | Tool captures error on stream abort and logs exception |
| EC-14 | WebSocket upgrade | Tool skips WebSocket connections silently |
| EC-15 | 1000 rps load | Middleware maintains overhead < 100 µs per request |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified
✅ 2. Middleware overhead < 100 µs per request (T-30)
✅ 3. Memory usage < 10 MB for 24h window at 1k rps (T-29)
✅ 4. Prometheus metrics exported in < 50 ms (T-28)
✅ 5. Alert latency < 1s from threshold breach (T-27)
✅ 6. Cardinality < 1000 unique label combinations (T-26)
✅ 7. Existing test suite passes with 0 failures
✅ 8. New test file `tests/test_error_rate.py` created with 30 tests
✅ 9. Grafana dashboard JSON created at `config/grafana/dashboards/error_rates.json`
✅ 10. Developer runs `curl http://localhost:8000/error-rates` and verifies endpoint returns error rates grouped by route and status

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate FastAPI middleware registration point in `main.py`
- [ ] Validate Prometheus client installed
- [ ] Validate structlog configured
- [ ] Detect existing error rate middleware
- [ ] Parse target files with AST

### 15.2 Settings
- [ ] Add `ERROR_RATE_LOOKBACK_HOURS` to `app/core/config.py`
- [ ] Add `ERROR_RATE_THRESHOLD_5XX_PCT` to `app/core/config.py`
- [ ] Add `ERROR_RATE_THRESHOLD_4XX_PCT` to `app/core/config.py`
- [ ] Add `ERROR_RATE_SINK` to `app/core/config.py`
- [ ] Add `ERROR_RATE_GROUP_BY` to `app/core/config.py`
- [ ] Add Prometheus scrape endpoint to `config/prometheus/prometheus.yml`
- [ ] Add Loki push endpoint to `config/loki/loki.yml`

### 15.3 Middleware
- [ ] Create `app/middleware/error_rate.py`
- [ ] Implement `ErrorRateMiddleware` class
- [ ] Register middleware in `main.py` after auth middleware
- [ ] Add Prometheus counters for HTTP errors
- [ ] Add Prometheus histogram for request duration
- [ ] Implement exception handling with fallback logging
- [ ] Add WebSocket connection skipping

### 15.4 Aggregator
- [ ] Create `app/core/aggregator.py`
- [ ] Implement `ErrorAggregator` class
- [ ] Add thread-safe recording mechanism
- [ ] Implement sliding window retention
- [ ] Add pruning of old data
- [ ] Add cardinality limiting
- [ ] Add buffering for failed metric exports

### 15.5 Schemas
- [ ] Create `app/schemas/error_rate.py`
- [ ] Define `ErrorRateResponse` schema
- [ ] Define `ErrorTrendResponse` schema
- [ ] Define `ErrorSummary` schema
- [ ] Add validation for status classes
- [ ] Add validation for route patterns
- [ ] Add validation for user tiers

### 15.6 Routes
- [ ] Create `app/api/endpoints/error_rate.py`
- [ ] Add `/error-rates` endpoint
- [ ] Add `/error-trends` endpoint
- [ ] Inject `ErrorAggregator` dependency
- [ ] Add OpenAPI documentation
- [ ] Add rate limiting
- [ ] Add authentication requirements

### 15.7 Metrics
- [ ] Define `http_errors_total` counter
- [ ] Define `http_request_duration_seconds` histogram
- [ ] Add Prometheus registry setup
- [ ] Add metric export endpoint
- [ ] Add buffering for failed exports
- [ ] Add cardinality limiting
- [ ] Add label validation

### 15.8 Alerting
- [ ] Create `config/prometheus/alerts.yml`
- [ ] Add 5xx threshold alert rule
- [ ] Add 4xx threshold alert rule
- [ ] Add alertmanager configuration
- [ ] Add alert silencing rules
- [ ] Add alert grouping rules
- [ ] Add alert notification templates

### 15.9 Dashboard
- [ ] Create `config/grafana/dashboards/error_rates.json`
- [ ] Add HTTP errors panel
- [ ] Add request duration panel
- [ ] Add error trends panel
- [ ] Add alert status panel
- [ ] Add cardinality monitoring
- [ ] Add middleware overhead monitoring

### 15.10 Testing
- [ ] Create `tests/test_error_rate.py`
- [ ] Add middleware functionality tests
- [ ] Add aggregation tests
- [ ] Add alerting tests
- [ ] Add edge case tests
- [ ] Add performance tests
- [ ] Add integration tests
- [ ] Add idempotency tests

### 15.11 Documentation
- [ ] Create `docs/error_rate_analyzer.md`
- [ ] Add installation instructions
- [ ] Add configuration reference
- [ ] Add API documentation
- [ ] Add troubleshooting guide
- [ ] Add performance tuning tips
- [ ] Add upgrade instructions

### 15.12 Atomicity
- [ ] Use temp-file + rename pattern for all writes
- [ ] Track touched files for rollback
- [ ] Verify file writes succeeded
- [ ] Rollback on any failure
- [ ] Clean up partial state
- [ ] Return success/failure report
- [ ] Verify idempotency on re-run

### 15.13 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Run `pytest tests/` with 0 failures
- [ ] Measure middleware overhead
- [ ] Verify memory usage limits
- [ ] Test alert latency
- [ ] Verify cardinality limits
- [ ] Check Prometheus metric export

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/middleware/error_rate.py",
    "app/core/aggregator.py",
    "app/schemas/error_rate.py",
    "app/api/endpoints/error_rate.py",
    "app/core/config.py",
    "app/core/logger.py",
    "config/prometheus/alerts.yml",
    "config/grafana/dashboards/error_rates.json",
    "docs/error_rate_analyzer.md",
    "tests/test_error_rate.py"
  ],
  "files_modified": [
    "main.py",
    "config.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 5123,
    "files_changed": 13,
    "lines_added": 723,
    "lines_removed": 18,
    "middleware_overhead_us": 95,
    "memory_usage_mb": 8.2
  },
  "next_steps": [
    "Restart FastAPI application to activate middleware",
    "Verify Prometheus metrics at http://localhost:9090/metrics",
    "Check Grafana dashboard at http://localhost:3000/d/error_rates",
    "Test error rates endpoint: curl http://localhost:8000/error-rates",
    "Verify alerts in Alertmanager: http://localhost:9093"
  ],
  "warnings": [
    "Ensure Prometheus scrape interval matches your error rate window",
    "High cardinality labels may impact Prometheus performance"
  ],
  "notes": [
    "Middleware registered after auth middleware in main.py",
    "Default thresholds set to 1% for 5xx and 5% for 4xx errors",
    "Error rates retained for 24 hours in memory",
    "Metrics exported to Prometheus with < 50ms latency"
  ]
}
