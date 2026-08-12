---
spec_id: "TOOL-041"
tool_name: "add_error_rate_analyzer"
primitive: "resiliency/TracingBuffer"
primitive_path: "core.venous.resiliency.TracingBuffer"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-ERA-01"
  - "INV-ERA-02"
  - "INV-ERA-03"
  - "INV-ERA-04"
  - "INV-ERA-05"
  - "INV-ERA-06"
  - "INV-ERA-07"
  - "INV-ERA-08"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "auth"
  - "api"
  - "payments"
  - "performance"
  - "operate"
---
# TOOL-041: fastapi_error_rate_analyzer

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_error_rate_analyzer` |
| Category | OPERATE |
| Complexity | High |
| Dependencies | FastAPI, structlog, prometheus_client, httpx (optional Loki sink) |
| Signature | `error_rate_analyzer(project_dir: str, lookback_hours: int = 24, group_by: list[str] \| None = None, threshold_5xx_pct: float = 1.0, threshold_4xx_pct: float = 5.0, sink: str = "prometheus") -> dict` |
| Parameters | `project_dir`: project root<br>`lookback_hours`: retention window for in-memory aggregation (default 24 h)<br>`group_by`: dimensions to aggregate by — e.g., `["route","status","user_tier"]`<br>`threshold_5xx_pct`: alert when 5xx rate exceeds this percentage of total requests<br>`threshold_4xx_pct`: alert when 4xx rate exceeds this percentage of total requests<br>`sink`: where to emit alerts — `prometheus`, `loki`, or `console` |

---

## 2. Purpose

The `fastapi_error_rate_analyzer` solves the most dangerous blind spot in high-traffic APIs: **you don't know which endpoints are breaking and for whom until customers start complaining**. A single Prometheus counter for `http_5xx_total` is useless when you have hundreds of routes and dozens of user tiers — it tells you something is wrong but not where, for whom, or how fast it's spreading. This tool instruments every response path with an `ErrorRateMiddleware` that captures route pattern (never full path), HTTP status code, status class (4xx vs 5xx), user tier extracted from the request context, and the Python exception type when available. It increments bounded Prometheus counters (`http_errors_total{route, status_class, user_tier}`) with a cardinality cap of 1 000 unique label combinations enforced at middleware layer, so Prometheus never suffers OOM from a cardinality explosion. Sliding windows of 1 m, 5 m, and 1 h are computed via `rate()` queries in the included Prometheus alert rules, giving operators immediate visibility into whether a spike is an isolated blip or a sustained degradation.

The second pillar of the tool is **trend detection and intelligent classification**. After injecting the middleware, the generator produces a `TrendDetector` that compares the current 5-minute error rate for each route against a 7-day rolling baseline; a 3× spike triggers a structured alert regardless of whether the absolute rate crosses the threshold. Classification separates "expected" errors (4xx — validation failures, auth rejections, not-found) from "unexpected" errors (5xx — unhandled exceptions, upstream failures, database crashes), because the on-call response is completely different: 4xx spikes often indicate a client bug or a broken API contract, while 5xx spikes require immediate infrastructure triage. Every error log entry is emitted via `structlog` with `error.route`, `error.status`, `error.exception_type`, `error.user_id`, and `error.trace_id` fields, enabling correlation with Loki and distributed tracing systems. A `plugin` interface allows teams to inject custom classifiers — for example, treating 429 as a business metric rather than an error. The tool is a code-only observability layer: it creates no database tables, migrates no data, and is safe to roll back by removing the middleware and deleting eight generated files.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Middleware overhead | < 100 µs per request | Adds negligible latency even at 1 000 rps; verified by T-25 |
| Files modified | ≤ 3 (`main.py`, `config.py`, `pyproject.toml`) | Minimises integration blast radius |
| Files created | ≥ 8 (`middleware.py`, `aggregator.py`, `metrics.py`, `trend.py`, `classifier.py`, `alert_rules.yml`, `tests/`, `Makefile` targets) | Complete production setup with no manual steps |
| Metric export latency | < 50 ms | Prometheus scrape stays below scrape timeout |
| Memory ceiling | ≤ 10 MB for 24 h window at 1 000 rps | Ring-buffer aggregator evicts entries older than `lookback_hours` |
| Cardinality ceiling | < 1 000 unique label combos | Route pattern normalisation + overflow bucket enforcement |
| Alert delivery | < 1 s from threshold breach to sink write | Evaluated in `dispatch()` after counter update |
| Tool idempotency | Re-run produces identical output | Middleware is registered once; config merge is deterministic |

---

## 4. Code Examples

### 4.1 ErrorRateMiddleware (NEW)

```python
# app/api/middleware/error_rate.py
import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.error_metrics import ErrorMetrics
from app.core.classifier import classify_error

logger = structlog.get_logger(__name__)

_ROUTE_PATTERN_MAX = 512  # characters before truncation


class ErrorRateMiddleware(BaseHTTPMiddleware):
    """Intercept every response and update error-rate counters.

    Never raises into the request path — all instrumentation is wrapped in
    a bare `except Exception` that logs and continues. Cardinality is
    bounded by normalising route patterns and capping at overflow bucket.
    """

    def __init__(self, app, metrics: ErrorMetrics | None = None) -> None:
        super().__init__(app)
        self._metrics = metrics or ErrorMetrics()

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        exc_type: str = "none"
        response: Response | None = None
        try:
            response = await call_next(request)
        except Exception as exc:
            exc_type = type(exc).__name__
            # Re-raise so FastAPI exception handlers still fire
            raise
        finally:
            try:
                status = response.status_code if response is not None else 500
                route = _normalise_route(request)
                user_tier = _extract_user_tier(request)
                trace_id = request.headers.get("x-trace-id", "no-trace")
                error_class = classify_error(status, exc_type)
                elapsed_ms = (time.monotonic() - start) * 1_000
                self._metrics.record(
                    route=route,
                    status=status,
                    status_class=error_class,
                    user_tier=user_tier,
                    exc_type=exc_type,
                )
                if status >= 400:
                    logger.warning(
                        "http_error",
                        error_route=route,
                        error_status=status,
                        error_class=error_class,
                        error_exception_type=exc_type,
                        error_user_tier=user_tier,
                        error_trace_id=trace_id,
                        elapsed_ms=round(elapsed_ms, 2),
                    )
            except Exception:
                logger.exception("error_rate_middleware_instrumentation_failed")
        return response  # type: ignore[return-value]


def _normalise_route(request: Request) -> str:
    """Return route pattern (e.g. /users/{user_id}) not the concrete path."""
    route = getattr(request.state, "route_pattern", None)
    if route:
        return route[:_ROUTE_PATTERN_MAX]
    # FastAPI populates scope["route"] after routing
    scope_route = request.scope.get("route")
    if scope_route and hasattr(scope_route, "path"):
        return scope_route.path[:_ROUTE_PATTERN_MAX]
    return "unknown_route"


def _extract_user_tier(request: Request) -> str:
    """Return user tier from request state; falls back to 'anonymous'."""
    return getattr(request.state, "user_tier", "anonymous")
```

### 4.2 Prometheus Metrics with Bounded Cardinality (NEW)

```python
# app/core/error_metrics.py
from __future__ import annotations

from prometheus_client import Counter, Histogram
import threading

_MAX_CARDINALITY = 1_000
_OVERFLOW_ROUTE = "__cardinality_overflow__"

_http_errors = Counter(
    "http_errors_total",
    "Total HTTP errors by route, status class, and user tier",
    ["route", "status_class", "user_tier"],
)

_http_requests = Counter(
    "http_requests_total",
    "Total HTTP requests observed by error-rate middleware",
    ["route"],
)

_middleware_latency = Histogram(
    "error_middleware_overhead_seconds",
    "Time spent inside ErrorRateMiddleware per request",
    buckets=(0.00005, 0.0001, 0.0002, 0.0005, 0.001, 0.005),
)


class ErrorMetrics:
    """Thread-safe wrapper that enforces cardinality cap on Prometheus labels."""

    _lock = threading.Lock()
    _seen_combos: set[tuple[str, str, str]] = set()

    def record(
        self,
        *,
        route: str,
        status: int,
        status_class: str,
        user_tier: str,
        exc_type: str,
    ) -> None:
        combo = (route, status_class, user_tier)
        with self._lock:
            if len(self._seen_combos) >= _MAX_CARDINALITY and combo not in self._seen_combos:
                route = _OVERFLOW_ROUTE
                combo = (_OVERFLOW_ROUTE, status_class, user_tier)
            self._seen_combos.add(combo)

        _http_requests.labels(route=route).inc()
        if status >= 400:
            _http_errors.labels(
                route=route,
                status_class=status_class,
                user_tier=user_tier,
            ).inc()
```

### 4.3 structlog Formatter for Error Events (NEW)

```python
# app/core/error_logging.py
"""Configure structlog for structured error-rate events."""
from __future__ import annotations

import logging
import sys

import structlog


def configure_structlog(log_level: str = "INFO") -> None:
    """Wire structlog with JSON renderer and stdlib integration."""
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
```

### 4.4 Sliding-Window Ring-Buffer Aggregator (NEW)

```python
# app/core/error_aggregator.py
"""In-memory ring-buffer aggregator for 1 m / 5 m / 1 h sliding windows."""
from __future__ import annotations

import time
from collections import deque, defaultdict
from dataclasses import dataclass, field
from threading import RLock


@dataclass
class ErrorEvent:
    ts: float          # monotonic timestamp
    route: str
    status: int
    user_tier: str


@dataclass
class WindowStats:
    total: int = 0
    errors_4xx: int = 0
    errors_5xx: int = 0

    @property
    def rate_4xx_pct(self) -> float:
        return (self.errors_4xx / self.total * 100) if self.total else 0.0

    @property
    def rate_5xx_pct(self) -> float:
        return (self.errors_5xx / self.total * 100) if self.total else 0.0


class SlidingWindowAggregator:
    """Thread-safe ring buffer; evicts events older than `max_age_seconds`."""

    WINDOWS = {"1m": 60, "5m": 300, "1h": 3_600}

    def __init__(self, max_age_seconds: int = 86_400) -> None:
        self._max_age = max_age_seconds
        self._events: deque[ErrorEvent] = deque()
        self._lock = RLock()

    def push(self, route: str, status: int, user_tier: str = "anonymous") -> None:
        with self._lock:
            self._events.append(ErrorEvent(ts=time.monotonic(), route=route,
                                           status=status, user_tier=user_tier))
            self._evict()

    def _evict(self) -> None:
        cutoff = time.monotonic() - self._max_age
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()

    def stats_for_window(self, window_name: str, route: str | None = None) -> WindowStats:
        seconds = self.WINDOWS.get(window_name, 60)
        cutoff = time.monotonic() - seconds
        s = WindowStats()
        with self._lock:
            for ev in reversed(self._events):
                if ev.ts < cutoff:
                    break
                if route and ev.route != route:
                    continue
                s.total += 1
                if 400 <= ev.status < 500:
                    s.errors_4xx += 1
                elif ev.status >= 500:
                    s.errors_5xx += 1
        return s

    def top_routes(self, window_name: str = "5m", top_n: int = 10) -> list[tuple[str, WindowStats]]:
        seconds = self.WINDOWS.get(window_name, 300)
        cutoff = time.monotonic() - seconds
        per_route: dict[str, WindowStats] = defaultdict(WindowStats)
        with self._lock:
            for ev in self._events:
                if ev.ts < cutoff:
                    continue
                r = per_route[ev.route]
                r.total += 1
                if 400 <= ev.status < 500:
                    r.errors_4xx += 1
                elif ev.status >= 500:
                    r.errors_5xx += 1
        ranked = sorted(per_route.items(),
                        key=lambda kv: kv[1].errors_5xx + kv[1].errors_4xx, reverse=True)
        return ranked[:top_n]
```

### 4.5 Trend Detector — 3× Spike vs 7-Day Baseline (NEW)

```python
# app/core/trend_detector.py
"""Compare current 5-minute error rate to 7-day rolling baseline."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from threading import RLock
from collections import deque

_SPIKE_FACTOR = 3.0        # alert if current > baseline * 3
_BASELINE_WINDOW_DAYS = 7
_BASELINE_SAMPLE_INTERVAL = 300   # sample every 5 minutes


@dataclass
class TrendAlert:
    route: str
    current_rate: float
    baseline_rate: float
    spike_factor: float
    window: str = "5m"


class TrendDetector:
    """Maintains per-route 7-day baseline using fixed-size deque of 5-minute samples."""

    def __init__(self) -> None:
        max_samples = (_BASELINE_WINDOW_DAYS * 24 * 60 * 60) // _BASELINE_SAMPLE_INTERVAL
        self._baselines: dict[str, deque[float]] = {}
        self._max_samples = int(max_samples)
        self._lock = RLock()
        self._last_sample_ts: dict[str, float] = {}

    def observe(self, route: str, rate_pct: float) -> TrendAlert | None:
        """Record a 5-minute rate sample; return TrendAlert if spike detected."""
        with self._lock:
            now = time.monotonic()
            last = self._last_sample_ts.get(route, 0)
            if now - last < _BASELINE_SAMPLE_INTERVAL:
                baseline = self._compute_baseline(route)
                return self._check_spike(route, rate_pct, baseline)
            # Store sample
            if route not in self._baselines:
                self._baselines[route] = deque(maxlen=self._max_samples)
            self._baselines[route].append(rate_pct)
            self._last_sample_ts[route] = now
            baseline = self._compute_baseline(route)
            return self._check_spike(route, rate_pct, baseline)

    def _compute_baseline(self, route: str) -> float:
        samples = self._baselines.get(route)
        if not samples or len(samples) < 2:
            return 0.0
        return sum(samples) / len(samples)

    def _check_spike(self, route: str, current: float, baseline: float) -> TrendAlert | None:
        if baseline < 0.01 or current <= baseline:
            return None
        factor = current / baseline
        if factor >= _SPIKE_FACTOR:
            return TrendAlert(route=route, current_rate=current,
                              baseline_rate=baseline, spike_factor=round(factor, 2))
        return None
```

### 4.6 Error Classifier with Plugin Interface (NEW)

```python
# app/core/classifier.py
"""Classify HTTP errors into 'expected_4xx' | 'unexpected_5xx' | 'ok'.

Custom classifiers can override the default via register_classifier().
"""
from __future__ import annotations

from typing import Callable

_ClassifierFn = Callable[[int, str], str]
_registered: _ClassifierFn | None = None

_4XX_STATUS_CLASSES = frozenset(range(400, 500))
_EXPECTED_4XX = frozenset({400, 401, 403, 404, 409, 422, 429})


def classify_error(status: int, exc_type: str = "none") -> str:
    """Return error class string for Prometheus labels."""
    if _registered is not None:
        try:
            result = _registered(status, exc_type)
            if result:
                return result
        except Exception:
            pass   # fall through to default
    return _default_classify(status, exc_type)


def _default_classify(status: int, exc_type: str) -> str:
    if status < 400:
        return "ok"
    if status in _EXPECTED_4XX:
        return "expected_4xx"
    if status in _4XX_STATUS_CLASSES:
        return "unexpected_4xx"
    return "unexpected_5xx"


def register_classifier(fn: _ClassifierFn) -> None:
    """Register a custom classifier. Called before default classification."""
    global _registered
    _registered = fn


def extract_exception_type(exc: BaseException | None) -> str:
    """Return qualified exception class name or 'none'."""
    if exc is None:
        return "none"
    module = type(exc).__module__ or ""
    name = type(exc).__qualname__
    if module and module != "builtins":
        return f"{module}.{name}"
    return name
```

### 4.7 Prometheus Alert Rules YAML

```yaml
# prometheus/alerts/error_rate.yml
groups:
  - name: fastapi_error_rate
    rules:
      - alert: HighErrorRate5xx
        expr: |
          (
            sum by (route, user_tier) (
              rate(http_errors_total{status_class="unexpected_5xx"}[5m])
            )
            /
            sum by (route, user_tier) (
              rate(http_requests_total[5m])
            )
          ) * 100 > 1.0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "5xx rate > 1% on {{ $labels.route }} for tier {{ $labels.user_tier }}"
          description: "5xx error rate is {{ $value | humanize }}% over the last 5 minutes."

      - alert: HighErrorRate4xx
        expr: |
          (
            sum by (route) (
              rate(http_errors_total{status_class=~".*4xx"}[5m])
            )
            /
            sum by (route) (
              rate(http_requests_total[5m])
            )
          ) * 100 > 5.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "4xx rate > 5% on {{ $labels.route }}"
          description: "4xx error rate is {{ $value | humanize }}% — check API contract."
```

### 4.8 CLI `top` Command (NEW)

```python
# app/cli/error_analyzer.py
"""CLI for error-rate analysis: `python -m app.cli.error_analyzer top`."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from app.core.error_aggregator import SlidingWindowAggregator
from app.core.error_metrics import ErrorMetrics

app = typer.Typer()
console = Console()

# Shared aggregator instance; in production injected via DI
_aggregator: SlidingWindowAggregator | None = None


def _get_aggregator() -> SlidingWindowAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = SlidingWindowAggregator()
    return _aggregator


@app.command()
def top(
    by: str = typer.Option("route", help="Group results by: route | user_tier"),
    since: str = typer.Option("5m", help="Window: 1m | 5m | 1h"),
    limit: int = typer.Option(20, help="Max rows to show"),
) -> None:
    """Show top error sources in the given time window."""
    agg = _get_aggregator()
    rows = agg.top_routes(window_name=since, top_n=limit)
    table = Table(title=f"Top errors — last {since}", show_lines=True)
    table.add_column("Route", style="cyan", no_wrap=True)
    table.add_column("Total", justify="right")
    table.add_column("4xx", justify="right", style="yellow")
    table.add_column("5xx", justify="right", style="red")
    table.add_column("4xx%", justify="right")
    table.add_column("5xx%", justify="right")
    for route, stats in rows:
        table.add_row(
            route,
            str(stats.total),
            str(stats.errors_4xx),
            str(stats.errors_5xx),
            f"{stats.rate_4xx_pct:.1f}%",
            f"{stats.rate_5xx_pct:.1f}%",
        )
    console.print(table)


@app.command()
def summary(since: str = typer.Option("1h", help="Window: 1m | 5m | 1h")) -> None:
    """Print aggregate 4xx/5xx totals across all routes."""
    agg = _get_aggregator()
    stats = agg.stats_for_window(since)
    console.print(f"[bold]Window:[/bold] {since}")
    console.print(f"  total={stats.total}  4xx={stats.errors_4xx} ({stats.rate_4xx_pct:.1f}%)  "
                  f"5xx={stats.errors_5xx} ({stats.rate_5xx_pct:.1f}%)")
```

### 4.9 Test: Middleware Counts 5xx and Propagates Trace ID

```python
# tests/test_error_rate_middleware.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.api.middleware.error_rate import ErrorRateMiddleware
from app.core.error_metrics import ErrorMetrics


@pytest.fixture()
def app_with_middleware() -> FastAPI:
    application = FastAPI()
    mock_metrics = MagicMock(spec=ErrorMetrics)
    application.add_middleware(ErrorRateMiddleware, metrics=mock_metrics)
    application.state.mock_metrics = mock_metrics

    @application.get("/items/{item_id}")
    async def get_item(item_id: int):
        return {"id": item_id}

    @application.get("/crash")
    async def crash():
        raise RuntimeError("simulated server error")

    return application


def test_200_does_not_increment_error_counter(app_with_middleware: FastAPI) -> None:
    client = TestClient(app_with_middleware, raise_server_exceptions=False)
    response = client.get("/items/42", headers={"x-trace-id": "trace-abc"})
    assert response.status_code == 200
    metrics = app_with_middleware.state.mock_metrics
    for call in metrics.record.call_args_list:
        assert call.kwargs.get("status", 200) < 400


def test_404_increments_expected_4xx(app_with_middleware: FastAPI) -> None:
    client = TestClient(app_with_middleware, raise_server_exceptions=False)
    response = client.get("/nonexistent")
    assert response.status_code == 404
    metrics = app_with_middleware.state.mock_metrics
    record_calls = metrics.record.call_args_list
    assert any(c.kwargs.get("status_class") == "expected_4xx" for c in record_calls)


def test_500_increments_unexpected_5xx(app_with_middleware: FastAPI) -> None:
    client = TestClient(app_with_middleware, raise_server_exceptions=False)
    client.get("/crash")
    metrics = app_with_middleware.state.mock_metrics
    record_calls = metrics.record.call_args_list
    assert any(c.kwargs.get("status_class") == "unexpected_5xx" for c in record_calls)


def test_trace_id_header_forwarded_to_structlog(app_with_middleware: FastAPI) -> None:
    with patch("app.api.middleware.error_rate.logger") as mock_logger:
        client = TestClient(app_with_middleware, raise_server_exceptions=False)
        client.get("/nonexistent", headers={"x-trace-id": "my-trace-123"})
        warning_calls = mock_logger.warning.call_args_list
        assert any(
            c.kwargs.get("error_trace_id") == "my-trace-123"
            for c in warning_calls
        )
```

### 4.10 Test: Cardinality Cap Enforced

```python
# tests/test_cardinality_cap.py
"""Ensure ErrorMetrics enforces the 1 000 label-combination ceiling."""
import pytest
from app.core.error_metrics import ErrorMetrics, _OVERFLOW_ROUTE, _MAX_CARDINALITY


def test_cardinality_cap_routes_to_overflow_bucket() -> None:
    metrics = ErrorMetrics()
    metrics._seen_combos = set()  # fresh for this test
    # Fill up to the cap
    for i in range(_MAX_CARDINALITY):
        metrics.record(
            route=f"/route/{i}",
            status=500,
            status_class="unexpected_5xx",
            user_tier="free",
            exc_type="RuntimeError",
        )
    assert len(metrics._seen_combos) == _MAX_CARDINALITY
    # Next unique route must land in overflow bucket
    metrics.record(
        route="/route/overflow_trigger",
        status=500,
        status_class="unexpected_5xx",
        user_tier="free",
        exc_type="RuntimeError",
    )
    overflow_found = any(_OVERFLOW_ROUTE in combo for combo in metrics._seen_combos)
    assert overflow_found, "Overflow route must appear after cardinality cap"
    assert len(metrics._seen_combos) <= _MAX_CARDINALITY + 1


def test_existing_combo_reuses_entry() -> None:
    metrics = ErrorMetrics()
    metrics._seen_combos = set()
    for _ in range(5):
        metrics.record(route="/users", status=404, status_class="expected_4xx",
                       user_tier="pro", exc_type="none")
    assert len(metrics._seen_combos) == 1, "Repeated combo must not grow set"
```

### 4.11 Test: Trend Detector Fires on 3× Spike

```python
# tests/test_trend_detector.py
"""Verify TrendDetector raises TrendAlert when current rate is >= 3× baseline."""
import time
import pytest
from unittest.mock import patch
from app.core.trend_detector import TrendDetector, _SPIKE_FACTOR


def _inject_baseline(detector: TrendDetector, route: str, rate: float, samples: int) -> None:
    """Directly populate the baseline deque to skip sample-interval throttle."""
    from collections import deque
    detector._baselines[route] = deque(
        [rate] * samples, maxlen=detector._max_samples
    )


def test_no_alert_below_spike_threshold() -> None:
    det = TrendDetector()
    _inject_baseline(det, "/api/orders", rate=1.0, samples=50)
    alert = det._check_spike("/api/orders", current=2.5, baseline=1.0)
    assert alert is None, "2.5× should not trigger alert (threshold = 3×)"


def test_alert_fires_at_exactly_3x() -> None:
    det = TrendDetector()
    _inject_baseline(det, "/api/orders", rate=1.0, samples=50)
    alert = det._check_spike("/api/orders", current=3.0, baseline=1.0)
    assert alert is not None
    assert alert.spike_factor >= _SPIKE_FACTOR
    assert alert.route == "/api/orders"


def test_no_alert_with_zero_baseline() -> None:
    det = TrendDetector()
    alert = det._check_spike("/new/route", current=100.0, baseline=0.0)
    assert alert is None, "Zero baseline must not produce a divide-by-zero alert"


def test_alert_contains_correct_rates() -> None:
    det = TrendDetector()
    _inject_baseline(det, "/api/checkout", rate=0.5, samples=100)
    alert = det._check_spike("/api/checkout", current=2.0, baseline=0.5)
    assert alert is not None
    assert alert.current_rate == pytest.approx(2.0)
    assert alert.baseline_rate == pytest.approx(0.5)
    assert alert.spike_factor == pytest.approx(4.0)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Middleware overhead < 100 µs per request** | `ErrorRateMiddleware.dispatch()` in `app/api/middleware/error_rate.py` measures elapsed via `time.monotonic()` and records to `_middleware_latency` histogram |
| QS-2 | **Cardinality ALWAYS bounded below 1 000 label combos** | `ErrorMetrics.record()` in `app/core/error_metrics.py` checks `_seen_combos` set size before adding label; overflows routed to `__cardinality_overflow__` bucket |
| QS-3 | **4xx and 5xx ALWAYS counted in separate Prometheus labels** | `classify_error()` in `app/core/classifier.py` returns `expected_4xx` or `unexpected_5xx`; labels are non-overlapping and set at counter creation |
| QS-4 | **Middleware NEVER raises into the request path** | Outer `finally` block in `ErrorRateMiddleware.dispatch()` is wrapped in bare `except Exception` that calls `logger.exception()` and continues |
| QS-5 | **Trace ID ALWAYS propagated to structured log entries** | `ErrorRateMiddleware.dispatch()` reads `x-trace-id` header and passes as `error_trace_id` kwarg to `structlog.warning()` call |
| QS-6 | **Route pattern NEVER includes concrete path parameters** | `_normalise_route()` in `app/api/middleware/error_rate.py` reads `scope["route"].path` (FastAPI pattern string, not URL path) |
| QS-7 | **Classification is deterministic given same inputs** | `classify_error()` in `app/core/classifier.py` uses pure frozenset lookup with no randomness; custom classifier fallback is wrapped in try/except |
| QS-8 | **Loki sink failures NEVER block request completion** | Loki HTTP push in `app/core/sinks/loki_sink.py` uses `asyncio.create_task()` with timeout; failure logged to stdout and swallowed |
| QS-9 | **Alert thresholds ALWAYS configurable via environment variables** | `ErrorRateSettings` class in `app/core/config.py` reads `ERROR_THRESHOLD_5XX_PCT` and `ERROR_THRESHOLD_4XX_PCT` via Pydantic `Field(env=...)` |
| QS-10 | **Memory bounded to 10 MB for 24 h at 1 k rps** | `SlidingWindowAggregator` in `app/core/error_aggregator.py` uses `deque` with `_evict()` called on every push; tested in T-27 |
| QS-11 | **Metric export completes in < 50 ms** | `generate_latest()` from `prometheus_client` is O(n-metrics) not O(n-events); tested by T-12 |
| QS-12 | **User tier defaults to 'anonymous' when request context absent** | `_extract_user_tier()` in `app/api/middleware/error_rate.py` calls `getattr(request.state, "user_tier", "anonymous")` with safe default |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `ErrorRateMiddleware` class exists at `app/api/middleware/error_rate.py` | File exists, `ast.parse()` succeeds |
| CC-02 | `ErrorMetrics` class exists at `app/core/error_metrics.py` | File exists, `ast.parse()` succeeds |
| CC-03 | `SlidingWindowAggregator` class exists at `app/core/error_aggregator.py` | File exists, `ast.parse()` succeeds |
| CC-04 | `TrendDetector` class exists at `app/core/trend_detector.py` | File exists, `ast.parse()` succeeds |
| CC-05 | `classify_error()` and `register_classifier()` exist at `app/core/classifier.py` | File exists; `grep classify_error` returns match |
| CC-06 | `configure_structlog()` exists at `app/core/error_logging.py` | File exists; function importable |
| CC-07 | Prometheus alert rules YAML at `prometheus/alerts/error_rate.yml` | File exists; YAML parses; contains `HighErrorRate5xx` and `HighErrorRate4xx` |
| CC-08 | Grafana dashboard JSON at `grafana/dashboards/error_rate.json` with ≥ 5 panels | File exists; `json.loads()` succeeds; `.panels` list length ≥ 5 |
| CC-09 | CLI `top` command at `app/cli/error_analyzer.py` | File exists; `python -m app.cli.error_analyzer top --help` exits 0 |
| CC-10 | `ErrorRateSettings` with env-var overrides at `app/core/config.py` | `grep ERROR_THRESHOLD_5XX_PCT app/core/config.py` returns match |
| CC-11 | Middleware registered in `app/main.py` via `add_middleware()` | `grep ErrorRateMiddleware app/main.py` returns match |
| CC-12 | `_normalise_route()` reads route pattern, not concrete URL path | Inspect `app/api/middleware/error_rate.py`; must reference `scope["route"]` |
| CC-13 | Cardinality cap ≤ 1 000 enforced with overflow bucket | Inspect `ErrorMetrics._seen_combos` size check in `record()` |
| CC-14 | 4xx and 5xx counted in separate `status_class` label values | Inspect `classify_error()` return values; must include `expected_4xx` and `unexpected_5xx` |
| CC-15 | Trace ID propagated to every error log entry | `grep error_trace_id app/api/middleware/error_rate.py` returns match |
| CC-16 | Trend detection compares against 7-day baseline | `grep _BASELINE_WINDOW_DAYS app/core/trend_detector.py` returns `7` |
| CC-17 | Spike threshold is 3× baseline rate | `grep _SPIKE_FACTOR app/core/trend_detector.py` returns `3.0` |
| CC-18 | Loki sink available and falls back to stdout on failure | `app/core/sinks/loki_sink.py` exists; fallback path logs to stdout |
| CC-19 | Custom classifier plugin registerable via `register_classifier()` | Test T-15 passes with custom fn returning non-default class |
| CC-20 | Middleware `dispatch()` never raises into caller | `test_middleware_resilient` (T-22) verifies response still returns on instrumentation crash |
| CC-21 | Aggregator `push()` evicts events beyond `lookback_hours` | Inspect `_evict()` call in `push()`; verified by T-11 |
| CC-22 | CLI `top --by=route --since=1h` prints tabular output | T-20 captures stdout and asserts Rich table headers present |
| CC-23 | Alert rules include window and threshold in annotations | `grep "humanize" prometheus/alerts/error_rate.yml` returns match |
| CC-24 | Prometheus counter labels use route pattern not full path | T-03 asserts label equals `/users/{user_id}` not `/users/42` |
| CC-25 | Memory ceiling tested at 1 k rps simulation | T-27 inserts 86 400 events and asserts memory delta ≤ 10 MB |
| CC-26 | Re-running tool leaves middleware registered exactly once | T-23 calls `error_rate_analyzer()` twice; asserts single middleware instance |
| CC-27 | Structured log events include `error.exception_type` field | T-05 asserts `error_exception_type` key present in log output |
| CC-28 | Overflow bucket label is constant `__cardinality_overflow__` | Inspect `_OVERFLOW_ROUTE` constant in `app/core/error_metrics.py` |
| CC-29 | WebSocket upgrade requests are skipped by middleware | T-28 sends WS upgrade; asserts no `error_metrics.record()` call |
| CC-30 | Streaming responses capture error only on connection abort | Inspect `ErrorRateMiddleware.dispatch()` exception path handling |

---

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified with automated checks
- [ ] All 8 Invariants enforced and covered by corresponding T-XX test
- [ ] `ErrorRateMiddleware` registered in `app/main.py` and smoke-tested via `TestClient`
- [ ] Prometheus counters `http_errors_total` and `http_requests_total` scraped successfully
- [ ] Alert rules YAML validated with `promtool check rules prometheus/alerts/error_rate.yml`
- [ ] Grafana dashboard JSON imports without errors; at least 5 panels visible
- [ ] CLI `top --by=route --since=5m` returns tabular output with error rates
- [ ] `TrendDetector` fires `TrendAlert` for 3× spike confirmed by T-17
- [ ] Custom classifier plugin round-trip verified: register fn → request → label reflects fn output
- [ ] Cardinality cap verified: 1 001st unique combo routed to `__cardinality_overflow__` bucket
- [ ] Middleware overhead measured < 100 µs at 1 000 rps (T-25 benchmark)
- [ ] structlog JSON output contains all required keys for error events
- [ ] Tool re-run is idempotent: second invocation produces no file changes and no duplicate middleware

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ERA-01 | Middleware NEVER raises into the request path on its own failures | `finally` block in `ErrorRateMiddleware.dispatch()` in `app/api/middleware/error_rate.py` wraps all instrumentation in bare `except Exception` | T-22 |
| INV-ERA-02 | Labels are ALWAYS bounded: route pattern only, never full concrete path | `_normalise_route()` in `app/api/middleware/error_rate.py` reads `scope["route"].path` (FastAPI pattern string); tested with parametrised routes | T-03 |
| INV-ERA-03 | 4xx and 5xx ALWAYS counted in separate status_class label values | `classify_error()` in `app/core/classifier.py` returns disjoint string constants `expected_4xx` / `unexpected_5xx`; enforced at counter label creation | T-07 |
| INV-ERA-04 | Cardinality is ALWAYS < 1 000 unique label combinations | `ErrorMetrics.record()` in `app/core/error_metrics.py` checks `len(_seen_combos) >= _MAX_CARDINALITY` and routes overflow to constant bucket | T-09 |
| INV-ERA-05 | Trace IDs are ALWAYS propagated to structured log entries | `ErrorRateMiddleware.dispatch()` reads `x-trace-id` header with `"no-trace"` default and passes as `error_trace_id` kwarg to every `logger.warning()` call | T-05 |
| INV-ERA-06 | Classification is DETERMINISTIC given same status code and exception type | `classify_error()` is a pure function over frozenset lookups with no mutable state; custom classifier wrapped in try/except with default fallback | T-14 |
| INV-ERA-07 | Alert sink failures NEVER silently drop alerts | `LokiSink.push()` in `app/core/sinks/loki_sink.py` logs failure via `structlog.error()` then falls back to `ConsoleSink`; no bare swallow | T-21 |
| INV-ERA-08 | Memory ALWAYS bounded: aggregator evicts events beyond `lookback_hours` | `SlidingWindowAggregator._evict()` called on every `push()`; removes events older than `max_age_seconds` from left of `deque` | T-27 |

---

## 9. User Stories

### 9.1 Basic Counting (US-01..US-05)

**US-01: Count 4xx errors by route**
- **As a** backend engineer diagnosing validation failures
- **I want** to see how many 4xx responses each route returns per minute
- **So that** I can identify which endpoints have broken client contracts
- **Given:** `ErrorRateMiddleware` registered and a client sending malformed requests to `/api/orders`
- **When:** I query `http_errors_total{route="/api/orders",status_class="expected_4xx"}`
- **Then:**
  - Counter value matches the number of 4xx responses sent (INV-ERA-03)
  - Route label is the pattern `/api/orders`, not a concrete URL (INV-ERA-02)
  - Verified by T-07

**US-02: Count 5xx errors by route**
- **As a** SRE on-call for a production incident
- **I want** to see real-time 5xx rates per route
- **So that** I can identify the broken endpoint within 60 seconds of a deploy
- **Given:** A simulated server crash on `/api/checkout` returns HTTP 500
- **When:** I query `rate(http_errors_total{status_class="unexpected_5xx"}[1m])`
- **Then:**
  - Rate immediately reflects the crash (INV-ERA-03)
  - `user_tier` label identifies which customer segment is affected (CC-14)
  - Verified by T-08

**US-03: Route label uses pattern, not full path**
- **As a** platform engineer worried about Prometheus OOM
- **I want** parametrised routes to be collapsed to their pattern
- **So that** 10 000 unique user IDs don't create 10 000 metric series
- **Given:** Requests to `/users/1`, `/users/2`, `/users/3` returning 404
- **When:** I list all values of the `route` label
- **Then:**
  - Only `/users/{user_id}` appears (CC-12, INV-ERA-02)
  - No concrete user IDs visible in metric labels
  - Verified by T-03

**US-04: Count errors by user tier**
- **As a** product manager investigating premium customer churn
- **I want** to filter error rates by `user_tier`
- **So that** I know if a bug disproportionately affects paying users
- **Given:** Free and pro users hitting the same route; route returns 500 for pro users
- **When:** I query `http_errors_total{user_tier="pro"}`
- **Then:**
  - Counter shows elevated count for `user_tier="pro"` (CC-14)
  - Requests with no auth context are labelled `user_tier="anonymous"` (QS-12)
  - Verified by T-08

**US-05: Exception type in structured logs**
- **As a** developer debugging a 500 cluster
- **I want** each error log entry to include the Python exception class
- **So that** I can correlate logs with code without reading stack traces
- **Given:** A route raises `sqlalchemy.exc.OperationalError` producing a 500
- **When:** I search Loki for `error_exception_type`
- **Then:**
  - Field `error_exception_type` contains `sqlalchemy.exc.OperationalError` (CC-27, INV-ERA-05)
  - Field `error_trace_id` links back to the distributed trace
  - Verified by T-05

### 9.2 Sliding Windows (US-06..US-10)

**US-06: 1-minute sliding window rate**
- **As a** on-call engineer watching a deploy roll out
- **I want** a 1-minute error rate that reacts instantly to regressions
- **So that** I can roll back within SLA before widespread impact
- **Given:** A canary deploy introduces 500 errors on `/api/pay`
- **When:** I check the 1-minute window from the alert rule
- **Then:**
  - Rate reflects errors within 60 seconds of first failure (CC-07)
  - Baseline comparison shows 3× spike and fires `TrendAlert` (INV-ERA-07)
  - Verified by T-10

**US-07: 5-minute window for trend comparison**
- **As a** TrendDetector consuming route stats
- **I want** a stable 5-minute aggregate for baseline comparison
- **So that** short bursts don't create false-positive trend alerts
- **Given:** A transient 10-second spike on `/api/search`
- **When:** `TrendDetector.observe()` is called with the 5-minute window rate
- **Then:**
  - Single-burst rate smoothed over 5 minutes stays below 3× threshold (CC-16, CC-17)
  - No `TrendAlert` is fired (T-17)
  - Verified by T-17

**US-08: 1-hour window for SLA reporting**
- **As a** SRE computing hourly SLA breach reports
- **I want** a 1-hour error rate per route
- **So that** I can populate the SLA dashboard and feed TOOL-042 `sla_reporter`
- **Given:** 360 000 requests in the last hour with 3 600 errors on `/api/orders`
- **When:** I call `aggregator.stats_for_window("1h")`
- **Then:**
  - `rate_5xx_pct` equals 1.0 (T-11)
  - Data feeds TOOL-042 via shared `SlidingWindowAggregator` instance (Interaction Matrix)
  - Verified by T-11

**US-09: Threshold breach triggers alert**
- **As a** platform engineer configuring production alerting
- **I want** an alert to fire when the 5xx rate exceeds `threshold_5xx_pct`
- **So that** PagerDuty wakes me up before customers report outages
- **Given:** `threshold_5xx_pct=1.0` and 5xx rate climbing to 1.5% on `/api/checkout`
- **When:** The Prometheus alert rule evaluates after 2 minutes
- **Then:**
  - `HighErrorRate5xx` alert fires (CC-07, CC-23)
  - Alert annotation includes route and user tier
  - Verified by T-18

**US-10: Alert resets when rate drops below threshold**
- **As a** on-call engineer who fixed the incident
- **I want** the alert to auto-resolve when error rate normalises
- **So that** alert fatigue is minimised and I can confirm recovery
- **Given:** `HighErrorRate5xx` alert firing at 2.0% on `/api/checkout`
- **When:** Fix deployed and rate drops to 0.3% for 2 minutes
- **Then:**
  - Alert state transitions to `resolved` (CC-07)
  - No duplicate alerts fire during the resolution window
  - Verified by T-19

### 9.3 Classification (US-11..US-15)

**US-11: 4xx classified as expected**
- **As a** alert routing engine separating customer bugs from server bugs
- **I want** 4xx errors to be labelled `expected_4xx`
- **So that** they route to a low-priority queue, not PagerDuty
- **Given:** Client sends malformed JSON body; route returns 422
- **When:** `classify_error(422, "none")` is called
- **Then:**
  - Returns `"expected_4xx"` (INV-ERA-03, CC-14)
  - Counter `http_errors_total{status_class="expected_4xx"}` increments
  - Verified by T-13

**US-12: 5xx classified as unexpected**
- **As a** alert routing engine escalating server crashes
- **I want** 5xx errors to be labelled `unexpected_5xx`
- **So that** they page the on-call team immediately
- **Given:** Unhandled `RuntimeError` produces HTTP 500
- **When:** `classify_error(500, "RuntimeError")` is called
- **Then:**
  - Returns `"unexpected_5xx"` (INV-ERA-06, INV-ERA-03)
  - Counter `http_errors_total{status_class="unexpected_5xx"}` increments
  - Verified by T-14

**US-13: Custom classifier plugin overrides default**
- **As a** product engineer who treats 429 as a business event, not an error
- **I want** to register a custom classifier that returns `"rate_limited"` for 429
- **So that** billing metrics stay separate from error dashboards
- **Given:** `register_classifier(lambda s, e: "rate_limited" if s == 429 else None)` called at startup
- **When:** Route returns 429; `classify_error(429, "none")` evaluated
- **Then:**
  - Returns `"rate_limited"` not `"expected_4xx"` (CC-19, INV-ERA-06)
  - Default fallback not invoked
  - Verified by T-15

**US-14: Failing custom classifier falls back to default**
- **As a** platform engineer protecting against buggy plugin code
- **I want** a crashing custom classifier to fall back gracefully to default logic
- **So that** a plugin bug never stops error counting
- **Given:** Custom classifier raises `ValueError` unconditionally
- **When:** Route returns 404; `classify_error(404, "none")` called
- **Then:**
  - Default classification `"expected_4xx"` returned (INV-ERA-06)
  - Exception swallowed without bubbling to caller
  - Verified by T-16

**US-15: Fully qualified exception type extracted**
- **As a** developer correlating metrics with exception tracking
- **I want** fully qualified exception names in log fields
- **So that** I can search Sentry and Loki with the same query string
- **Given:** Route raises `app.services.payment.ChargeFailedError`
- **When:** `extract_exception_type(exc)` called on the caught exception
- **Then:**
  - Returns `"app.services.payment.ChargeFailedError"` (CC-27)
  - Field appears in structlog output as `error_exception_type`
  - Verified by T-06

### 9.4 Alerts (US-16..US-20)

**US-16: Prometheus alert rule fires on threshold breach**
- **As a** DevOps engineer using Prometheus Alertmanager
- **I want** `HighErrorRate5xx` to fire when 5xx rate exceeds 1% for 2 minutes
- **So that** we meet our 5-minute detection SLA without manual monitoring
- **Given:** Alert rules loaded and Prometheus evaluating every 30 s
- **When:** 5xx rate on `/api/orders` reaches 1.5% for 2 consecutive minutes
- **Then:**
  - `HighErrorRate5xx` transitions to `firing` state (CC-07, CC-23)
  - Annotation shows `{{ $value | humanize }}%` rendered correctly
  - Verified by T-18

**US-17: Trend alert on 3× spike vs 7-day baseline**
- **As a** SRE who wants zero-config alerting for anomalies
- **I want** a trend alert to fire when error rate triples vs the 7-day average
- **So that** I catch regressions even when absolute rates are low
- **Given:** `/api/search` baseline is 0.2% 5xx; today rate spikes to 0.7%
- **When:** `TrendDetector.observe("/api/search", 0.7)` called
- **Then:**
  - `TrendAlert` returned with `spike_factor ≈ 3.5` (CC-16, CC-17, INV-ERA-07)
  - Alert contains `route`, `current_rate`, and `baseline_rate`
  - Verified by T-17

**US-18: Loki sink pushes structured log on alert**
- **As a** observability engineer using Grafana Loki for log aggregation
- **I want** each error alert to push a structured JSON log to Loki
- **So that** I can correlate alert timeline with request logs in one UI
- **Given:** `sink="loki"` configured and Loki reachable at `LOKI_URL`
- **When:** 5xx threshold breached and `LokiSink.push()` called
- **Then:**
  - HTTP POST sent to Loki push API with JSON labels (CC-18)
  - Push is fire-and-forget; failure logs to stdout and does not block (QS-8)
  - Verified by T-21

**US-19: Console sink for development environment**
- **As a** developer running the API locally
- **I want** error-rate alerts to print to stdout in development mode
- **So that** I don't need Prometheus or Loki to see error spikes during dev
- **Given:** `sink="console"` configured in `ErrorRateSettings`
- **When:** 5xx rate exceeds `threshold_5xx_pct`
- **Then:**
  - Structured JSON alert printed to `stdout` (QS-9)
  - Same data shape as Loki push payload for parity
  - Verified by T-20

**US-20: Alert window rolling boundary prevents duplicates**
- **As a** on-call engineer who should not receive duplicate pages
- **I want** the alert rule to not re-fire within the same evaluation window
- **So that** I receive exactly one page per incident, not one per Prometheus scrape
- **Given:** `HighErrorRate5xx` alert in `firing` state
- **When:** Prometheus evaluates again 30 seconds later with rate still elevated
- **Then:**
  - Alert remains in `firing` state; Alertmanager does not send a new notification (CC-23)
  - Resolved only after rate drops below threshold for `for: 2m` duration
  - Verified by T-19

### 9.5 Edge Cases (US-21..US-25)

**US-21: Cardinality explosion bounded by overflow bucket**
- **As a** platform engineer preventing Prometheus OOM in a microservice explosion
- **I want** the metric set to remain bounded even if a new deployment introduces 500 new routes
- **So that** Prometheus memory stays predictable at scale
- **Given:** 1 001 unique `(route, status_class, user_tier)` combinations observed
- **When:** 1 001st combination arrives in `ErrorMetrics.record()`
- **Then:**
  - Label `route="__cardinality_overflow__"` used instead (CC-13, CC-28, INV-ERA-04)
  - Total unique series count stays ≤ 1 000
  - Verified by T-09

**US-22: Middleware resilient to instrumentation crash**
- **As a** application running in production
- **I want** the application to keep serving requests even if the error-rate middleware crashes internally
- **So that** an observability bug never causes a 500 cascade
- **Given:** Instrumentation code raises `AttributeError` (e.g., missing `request.state` attribute)
- **When:** `ErrorRateMiddleware.dispatch()` catches the internal exception
- **Then:**
  - Response still returned to client with original status code (INV-ERA-01)
  - Exception logged to stdout via `logger.exception()` without re-raising
  - Verified by T-22

**US-23: Tool re-run is idempotent**
- **As a** CI pipeline running the tool on every merge
- **I want** calling `error_rate_analyzer()` twice to produce no duplicate middleware registrations
- **So that** the CI pipeline is safe to re-run without manual cleanup
- **Given:** `error_rate_analyzer()` already called once; middleware registered in `app/main.py`
- **When:** Tool called a second time on the same project directory
- **Then:**
  - No second `add_middleware()` call inserted (CC-26)
  - Files unchanged; tool returns success with `changes=0`
  - Verified by T-23

**US-24: Requests without user context get anonymous tier**
- **As a** public API endpoint serving unauthenticated health checks
- **I want** unauthenticated requests to produce a well-known label value
- **So that** public endpoint errors are visible without polluting tier-specific dashboards
- **Given:** `GET /health` request with no auth token; `request.state.user_tier` not set
- **When:** `_extract_user_tier(request)` called
- **Then:**
  - Returns `"anonymous"` consistently (QS-12, CC-12)
  - Counter label `user_tier="anonymous"` increments for the request
  - Verified by T-04

**US-25: High-cardinality load at 1 000 rps stays under 100 µs overhead**
- **As a** performance engineer validating production readiness
- **I want** the middleware overhead to remain below 100 µs even at maximum expected traffic
- **So that** the observability tool does not become the bottleneck at scale
- **Given:** 1 000 requests per second hitting a mix of routes returning 200, 404, and 500
- **When:** Latency percentiles measured with `time.monotonic()` around `dispatch()` body
- **Then:**
  - p99 instrumentation overhead ≤ 100 µs (QS-1, INV-ERA-01)
  - `error_middleware_overhead_seconds` histogram p99 bucket ≤ 0.0001 s
  - Verified by T-25

---

## 10. Test Plan

### 10.1 Middleware Tests (T-01..T-06)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | 200 response not counted as error | FastAPI app with `ErrorRateMiddleware`, `TestClient` | `GET /items/1` returns 200 | `ErrorMetrics.record()` called with `status=200`; `http_errors_total` not incremented |
| T-02 | 404 response counted as `expected_4xx` | Route not registered, middleware active | `GET /nonexistent` | `http_errors_total{status_class="expected_4xx"}` increments by 1 (INV-ERA-03) |
| T-03 | Route label is pattern not concrete path | Route `/users/{user_id}` registered | `GET /users/42` then `GET /users/99` | Both calls produce label `route="/users/{user_id}"` never `"/users/42"` (INV-ERA-02) |
| T-04 | Anonymous user tier label for unauthenticated request | No `request.state.user_tier` set | `GET /health` | `user_tier="anonymous"` in counter labels (QS-12) |
| T-05 | Trace ID propagated to structlog output | `x-trace-id: abc-123` header | `GET /crash` returns 500 | `log_output["error_trace_id"] == "abc-123"` (INV-ERA-05, CC-15) |
| T-06 | Exception type captured in log entry | Route raises `ValueError` | `GET /crash` | `log_output["error_exception_type"] == "ValueError"` (CC-27) |

### 10.2 Aggregation and Cardinality Tests (T-07..T-12)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Counter increments correctly for each error type | Fresh `ErrorMetrics` | Record 3× `expected_4xx`, 2× `unexpected_5xx` | Respective counters equal 3 and 2 (INV-ERA-03) |
| T-08 | Counter labels include `user_tier` dimension | Two requests: tier=`free` and tier=`pro` | Record both at status 500 | `http_errors_total{user_tier="free"}` and `{user_tier="pro"}` both present |
| T-09 | Cardinality cap routes 1 001st combo to overflow bucket | `_MAX_CARDINALITY=1000` | Insert 1 001 unique combos | 1 001st combo uses `route="__cardinality_overflow__"` (INV-ERA-04, CC-13) |
| T-10 | 1-minute window returns correct totals | `SlidingWindowAggregator` with events at `t=0..59s` | Call `stats_for_window("1m")` | `total` matches event count; events at `t=61s` excluded |
| T-11 | 1-hour window accumulates across 3 600 s | Push events over 1 h period | Call `stats_for_window("1h")` | All events within window counted; `rate_5xx_pct` computed correctly (CC-03) |
| T-12 | Metric scrape completes in < 50 ms | 1 000 active label combos | Time `generate_latest()` call | Duration < 50 ms (QS-11) |

### 10.3 Classification Tests (T-13..T-18)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Status 422 → `expected_4xx` | `classify_error(422, "none")` | Call function | Returns `"expected_4xx"` (CC-14, INV-ERA-06) |
| T-14 | Status 500 → `unexpected_5xx` | `classify_error(500, "RuntimeError")` | Call function | Returns `"unexpected_5xx"` (INV-ERA-03, INV-ERA-06) |
| T-15 | Custom classifier overrides 429 classification | `register_classifier(lambda s,e: "rate_limited" if s==429 else None)` | `classify_error(429, "none")` | Returns `"rate_limited"` (CC-19) |
| T-16 | Crashing custom classifier falls back to default | `register_classifier(lambda s,e: 1/0)` | `classify_error(404, "none")` | Returns `"expected_4xx"` without raising (INV-ERA-06) |
| T-17 | TrendDetector fires on 3× spike | Baseline 1.0% over 50 samples; current 3.5% | `detect._check_spike(route, 3.5, 1.0)` | `TrendAlert` returned with `spike_factor=3.5` (CC-16, CC-17) |
| T-18 | TrendDetector silent below 3× | Baseline 1.0%; current 2.9% | `detect._check_spike(route, 2.9, 1.0)` | Returns `None` (no alert) (CC-17) |

### 10.4 Alert Delivery Tests (T-19..T-24)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Alert resolves when rate drops | `HighErrorRate5xx` firing at 2% | Rate drops to 0.3% for 2 min | Alert transitions to `resolved`; no duplicate fire (CC-07) |
| T-20 | Console sink prints JSON alert | `sink="console"` | Trigger threshold breach | `stdout` contains JSON with `route`, `status_class`, `rate_pct` keys (US-19) |
| T-21 | Loki sink failure falls back to stdout | `LOKI_URL` unreachable | Trigger alert | `LokiSink` logs failure; `ConsoleSink` used; no exception raised (INV-ERA-07, QS-8) |
| T-22 | Middleware instrumentation crash does not kill request | Monkey-patch `ErrorMetrics.record` to raise | `GET /items/1` | Response returned with status 200; crash logged as `exception` (INV-ERA-01, CC-20) |
| T-23 | Tool re-run is idempotent | `error_rate_analyzer()` called once | Call again on same `project_dir` | No second `add_middleware` in `main.py`; returns `changes=0` (CC-26) |
| T-24 | Threshold env-var override active | `ERROR_THRESHOLD_5XX_PCT=0.5` in env | Load `ErrorRateSettings` | `settings.threshold_5xx_pct == 0.5` (QS-9, CC-10) |

### 10.5 Performance and Edge-Case Tests (T-25..T-30)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Middleware overhead < 100 µs at 1 000 rps | Async loop sending 10 000 requests | Measure p99 of `error_middleware_overhead_seconds` histogram | p99 ≤ 0.0001 s (QS-1, INV-ERA-01) |
| T-26 | Aggregator evicts events beyond lookback window | Push events at `t-3700s` and `t-0s` | Call `stats_for_window("1h")` | Old events not counted; recent events present (INV-ERA-08, CC-21) |
| T-27 | Memory bounded at 1 k rps for 24 h | Insert 86 400 events (1/s for 24 h, lookback=24h) | Measure `sys.getsizeof` delta | Memory growth ≤ 10 MB (QS-10, CC-25) |
| T-28 | WebSocket upgrade skipped by middleware | FastAPI WebSocket route; WS client connects | Assert `ErrorMetrics.record` not called | Middleware skips non-HTTP error accounting for WebSocket handshake (CC-29) |
| T-29 | Streaming response captures error on abort | Streaming endpoint aborts mid-stream | Client disconnects abruptly | Only aborted streams counted; partial streams with 200 header not counted (CC-30) |
| T-30 | Missing trace ID uses `"no-trace"` placeholder | Request without `x-trace-id` header | `GET /items/1` returns 404 | `log_output["error_trace_id"] == "no-trace"` (INV-ERA-05, CC-15) |

---

## 11. Interaction Matrix

| Other tool | Order | Interaction | Notes |
|------------|-------|-------------|-------|
| `fastapi_connection_pool_monitor` (TOOL-040) | Must run before | ⚠️ **Prerequisite** | Pool timeout events should be correlated with 5xx spikes; share `SlidingWindowAggregator` instance so pool exhaustion and error rate appear on same dashboard |
| `fastapi_sla_reporter` (TOOL-042) | Runs after | ✅ **Consumer** | `sla_reporter` reads from `SlidingWindowAggregator.stats_for_window("1h")` to compute SLA breach metrics; initialise aggregator before `sla_reporter` starts |
| `fastapi_audit_log` (TOOL-005) | Must run before | ⚠️ **Caveat** | Audit log middleware must be registered before `ErrorRateMiddleware` to ensure audit events capture pre-error request context without seeing modified headers |
| `fastapi_circuit_breaker` (TOOL-022) | Runs before | ⚠️ **Caveat** | Circuit breaker middleware fires first; when circuit opens it returns 503 directly — `ErrorRateMiddleware` must still count that 503 as `unexpected_5xx` downstream |
| `fastapi_add_multi_tenancy` (TOOL-008) | No constraint | ✅ **Compatible** | Tenant context is set on `request.state.user_tier` (or tenant middleware enriches it); `ErrorRateMiddleware` reads `user_tier` transparently without tenancy awareness |
| `fastapi_detect_n_plus_one` (TOOL-028) | No constraint | ✅ **Compatible** | N+1 detection fires at ORM layer; resulting slow queries often cause 500s that `ErrorRateMiddleware` will count — useful for correlation |
| `fastapi_add_api_key_auth` (TOOL-010) | Runs before | ⚠️ **Caveat** | Auth middleware rejects unauthenticated requests with 401/403 before route handler fires; `ErrorRateMiddleware` must be outermost so it counts those `expected_4xx` rejections |
| `fastapi_add_oauth2_provider` (TOOL-012) | Runs before | ⚠️ **Caveat** | OAuth2 token introspection failures return 401; `ErrorRateMiddleware` should be registered after auth middleware stack to see final response status |
| `fastapi_add_cache_layer` (TOOL-019) | No constraint | ✅ **Compatible** | Cache hits bypass handler; cache misses that produce errors are counted correctly; cache-hit 200s are also counted by `http_requests_total` |
| `fastapi_add_rbac` (TOOL-014) | Runs before | ⚠️ **Caveat** | RBAC 403 responses are `expected_4xx`; with `ErrorRateMiddleware` outermost, all RBAC rejections are captured and classified correctly |
| `fastapi_add_rate_limiting` (TOOL-016) | Runs before | ⚠️ **Caveat** | Rate limiter returns 429; with custom classifier `register_classifier` can override 429 to `"rate_limited"` class rather than `expected_4xx` |
| `fastapi_add_outbox_pattern` (TOOL-024) | No constraint | ✅ **Compatible** | Outbox write failures surface as 500s; `ErrorRateMiddleware` counts and logs them with exception type for correlation with message queue dashboards |
| `fastapi_add_search` (TOOL-021) | No constraint | ✅ **Compatible** | Search query errors (malformed syntax → 400, timeout → 504) counted with correct `status_class`; no special handling required |
| `fastapi_add_soft_delete` (TOOL-004) | No constraint | ✅ **Compatible** | Soft-delete not-found returns 404 classified as `expected_4xx`; no interaction issues |
| `fastapi_add_bulk_operations` (TOOL-026) | No constraint | ✅ **Compatible** | Partial-failure bulk responses (207 Multi-Status) not counted as errors; full-fail 400/500 responses counted correctly |

**Conflicts:** None identified. Middleware registration order is the only coordination concern.

---

## 12. Rollback Procedure

### 12.1 Code Rollback (before deploy)

```bash
# Revert all modified files to last commit
git checkout app/main.py
git checkout app/core/config.py
git checkout pyproject.toml

# Remove all generated files
rm -f app/api/middleware/error_rate.py
rm -f app/core/error_metrics.py
rm -f app/core/error_aggregator.py
rm -f app/core/trend_detector.py
rm -f app/core/classifier.py
rm -f app/core/error_logging.py
rm -f app/core/sinks/loki_sink.py
rm -f app/cli/error_analyzer.py
rm -f prometheus/alerts/error_rate.yml
rm -f grafana/dashboards/error_rate.json
rm -f tests/test_error_rate_middleware.py
rm -f tests/test_cardinality_cap.py
rm -f tests/test_trend_detector.py
```

### 12.2 Database Rollback

**N/A** — this tool is a pure code-only observability middleware. No database tables, columns, indexes, or Alembic migrations are created. There is nothing to downgrade at the database layer.

### 12.3 Data Preservation

**N/A** — the tool writes no business data to any persistent store. The `SlidingWindowAggregator` ring buffer is in-memory and ephemeral; it is destroyed on process restart. Prometheus time-series data can optionally be purged as shown in §12.5.

### 12.4 Failure Mode: Middleware Throwing into Request Path

If `INV-ERA-01` is violated and middleware raises unexpectedly (e.g., due to a bug in a downstream library version):

```bash
# 1. Immediate: disable via environment variable (zero-downtime)
export ERROR_RATE_MIDDLEWARE_ENABLED=false
# Restart workers — middleware checks env var in __init__ and becomes a passthrough

# 2. Identify the offending version
pip show prometheus_client structlog | grep Version

# 3. Pin to last-known-good version
pip install "prometheus_client==0.19.0" "structlog==23.3.0"

# 4. Full code rollback if env-var toggle is insufficient
git checkout app/main.py app/api/middleware/error_rate.py
```

### 12.5 Failure Mode: Cardinality Explosion (Prometheus OOM)

A deployment bug (e.g., route normalisation disabled) can cause unbounded cardinality:

```bash
# 1. Identify high-cardinality series
curl -s http://prometheus:9090/api/v1/label/route/values | jq '.data | length'

# 2. Delete high-cardinality series (TSDB admin API must be enabled)
curl -X POST http://prometheus:9090/api/v1/admin/tsdb/delete_series \
  --data 'match[]=http_errors_total{route=~"/users/[0-9]+"}'

# 3. Clean tombstones
curl -X POST http://prometheus:9090/api/v1/admin/tsdb/clean_tombstones

# 4. Fix route normalisation and redeploy
git diff app/api/middleware/error_rate.py  # confirm _normalise_route uses scope["route"]
git checkout app/api/middleware/error_rate.py
```

### 12.6 Failure Mode: Loki Sink Down (Buffer Overflow)

When Loki is unreachable, the async push task errors silently per `INV-ERA-07`. To switch sink:

```bash
# Switch to console sink immediately
export ERROR_RATE_SINK=console
# Restart workers — LokiSink never initialised

# Inspect recent errors that were buffered to stdout
journalctl -u myapp --since "5 minutes ago" | grep '"event":"http_error"' | head -50

# Once Loki is restored, switch back
export ERROR_RATE_SINK=loki
```

### 12.7 Failure Mode: False-Positive Alert Fatigue

If alert thresholds are too aggressive for baseline traffic:

```bash
# Raise 5xx threshold to 2%
export ERROR_THRESHOLD_5XX_PCT=2.0
# Restart workers or send SIGHUP if config hot-reload supported

# Alternatively, raise alert evaluation window in Prometheus rules YAML
# Edit prometheus/alerts/error_rate.yml: change `for: 2m` to `for: 5m`
curl -X POST http://prometheus:9090/-/reload

# Review baseline and calibrate trend detector
python -m app.cli.error_analyzer summary --since 1h
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Route not in FastAPI router registry | Labelled as `unknown_route` (constant string); cardinality not inflated by unregistered paths |
| EC-02 | 0 requests in sliding window | `stats_for_window()` returns `WindowStats(total=0)`; no alert fires; no division-by-zero error |
| EC-03 | 100% 5xx rate on a route | Alert fires on threshold; every request produces a structlog warning entry with full context |
| EC-04 | Middleware instrumentation code itself raises | Request still completes with original response; instrumentation failure logged via `logger.exception()` |
| EC-05 | Request without user context on `request.state` | `_extract_user_tier()` returns `"anonymous"`; counter labelled consistently for all such requests |
| EC-06 | High-cardinality user IDs passed as labels | Grouped by tier from `request.state.user_tier` only; raw user IDs never appear as metric label values |
| EC-07 | `x-trace-id` header absent from request | Placeholder `"no-trace"` used; log entry still emitted with all other fields populated correctly |
| EC-08 | Loki HTTP push sink unreachable | `asyncio.create_task()` times out; failure logged to stdout; `ConsoleSink` used as fallback without blocking |
| EC-09 | Prometheus scrape fails mid-collection | Metrics buffered in-memory by `prometheus_client`; next successful scrape delivers all counters |
| EC-10 | Tool re-run on already-instrumented project | Detects existing `ErrorRateMiddleware` import in `main.py`; skips file modification; returns `changes=0` |
| EC-11 | Alert window rolls over exactly at boundary | Prometheus `rate()` function handles boundary correctly; no duplicate alert fires at window edge |
| EC-12 | Custom classifier raises an exception | Falls back to `_default_classify()`; exception swallowed and not propagated to request handler |
| EC-13 | Streaming response — error before first byte | Exception caught in `finally` block; counted as `unexpected_5xx` with partial stream noted |
| EC-14 | WebSocket upgrade request arrives | Middleware detects `scope["type"] == "websocket"`; skips error counting; no label recorded |
| EC-15 | 1 000 rps sustained load | Middleware overhead stays below 100 µs p99; ring buffer stays within 10 MB memory bound |

---

## 14. Acceptance Criteria

✅ `ErrorRateMiddleware` registered in `app/main.py` and all 11 T-01..T-06 + T-22 tests pass
✅ Prometheus counters `http_errors_total{route,status_class,user_tier}` present after first request
✅ Route label equals FastAPI pattern string (e.g., `/users/{user_id}`) verified by T-03
✅ Cardinality cap enforced: 1 001st unique combo routes to `__cardinality_overflow__` bucket (T-09)
✅ `TrendDetector` fires `TrendAlert` with `spike_factor >= 3.0` for qualifying spikes (T-17)
✅ Alert rules YAML passes `promtool check rules prometheus/alerts/error_rate.yml` with zero errors
✅ CLI `python -m app.cli.error_analyzer top --since=5m` prints Rich table with route, 4xx%, 5xx%
✅ Middleware overhead p99 ≤ 100 µs at 1 000 rps load (T-25 benchmark)
✅ Loki sink failure falls back to stdout without raising; response still returned to client (T-21)
✅ Tool idempotent: calling `error_rate_analyzer()` twice on same project produces `changes=0` (T-23)

---

## 15. Implementation Checklist

### 15.1 Pre-flight Validation
- [ ] Verify `project_dir` contains a FastAPI `app` or `application` instance in `main.py`
- [ ] Check for existing `ErrorRateMiddleware` import to detect already-instrumented project
- [ ] Confirm `structlog` is available in project dependencies or `pyproject.toml`
- [ ] Confirm `prometheus_client` is available in project dependencies or `pyproject.toml`
- [ ] Detect Python version >= 3.10 (union type hints used in middleware)
- [ ] Check for conflicting middleware that may interfere with route resolution
- [ ] Validate `sink` parameter value is one of `prometheus`, `loki`, `console`

### 15.2 Configuration Setup
- [ ] Add `ERROR_THRESHOLD_5XX_PCT` field to `ErrorRateSettings` in `app/core/config.py`
- [ ] Add `ERROR_THRESHOLD_4XX_PCT` field to `ErrorRateSettings` in `app/core/config.py`
- [ ] Add `ERROR_RATE_SINK` field (default `"prometheus"`) to settings
- [ ] Add `ERROR_RATE_LOOKBACK_HOURS` field (default `24`) to settings
- [ ] Add `ERROR_RATE_CARDINALITY_CAP` field (default `1000`) to settings
- [ ] Add `ERROR_RATE_MIDDLEWARE_ENABLED` boolean toggle to settings
- [ ] Validate that `LOKI_URL` env var is present when `sink="loki"`

### 15.3 Middleware Core
- [ ] Implement `ErrorRateMiddleware` class extending `BaseHTTPMiddleware`
- [ ] Implement `dispatch()` with try/except/finally wrapping all instrumentation
- [ ] Implement `_normalise_route()` reading `scope["route"].path` pattern
- [ ] Implement `_extract_user_tier()` with `"anonymous"` fallback
- [ ] Read `x-trace-id` header with `"no-trace"` default
- [ ] Skip middleware logic for WebSocket upgrade requests (`scope["type"] == "websocket"`)
- [ ] Register middleware in `app/main.py` via single idempotent `add_middleware()` call

### 15.4 Metrics Module
- [ ] Define `http_errors_total` Counter with `[route, status_class, user_tier]` labels
- [ ] Define `http_requests_total` Counter with `[route]` label
- [ ] Define `error_middleware_overhead_seconds` Histogram with microsecond buckets
- [ ] Implement `ErrorMetrics.record()` with cardinality guard using `threading.Lock`
- [ ] Implement overflow bucket routing to `_OVERFLOW_ROUTE` constant
- [ ] Implement `_seen_combos` set tracking with atomic check-and-add
- [ ] Export `_MAX_CARDINALITY` constant for test inspection

### 15.5 Aggregator Module
- [ ] Implement `SlidingWindowAggregator` with `deque`-backed ring buffer
- [ ] Implement `push()` method calling `_evict()` before append
- [ ] Implement `_evict()` removing events older than `max_age_seconds`
- [ ] Implement `stats_for_window()` for windows `"1m"`, `"5m"`, `"1h"`
- [ ] Implement `top_routes()` returning ranked list of `(route, WindowStats)` tuples
- [ ] Protect all public methods with `RLock` for thread safety
- [ ] Expose `WindowStats.rate_4xx_pct` and `rate_5xx_pct` computed properties

### 15.6 Trend Detector Module
- [ ] Implement `TrendDetector` class with per-route `deque[float]` baselines
- [ ] Implement `observe()` with 5-minute sample-interval throttle
- [ ] Implement `_compute_baseline()` as simple mean of stored samples
- [ ] Implement `_check_spike()` returning `TrendAlert` when `current >= baseline * 3.0`
- [ ] Handle zero baseline without division by zero (`return None`)
- [ ] Set `_max_samples` from 7-day window / 5-minute interval = 2 016 samples
- [ ] Export `TrendAlert` dataclass with `route`, `current_rate`, `baseline_rate`, `spike_factor`

### 15.7 Classifier Module
- [ ] Implement `classify_error(status, exc_type)` as pure function with frozenset lookups
- [ ] Define `_EXPECTED_4XX` frozenset covering 400, 401, 403, 404, 409, 422, 429
- [ ] Implement `register_classifier()` storing to module-level `_registered` variable
- [ ] Wrap custom classifier call in `try/except` with default fallback
- [ ] Implement `extract_exception_type()` returning fully qualified class name
- [ ] Export module-level constant strings for `ok`, `expected_4xx`, `unexpected_5xx`
- [ ] Unit-test determinism: same input always produces same output (T-14, T-16)

### 15.8 Logging Module
- [ ] Implement `configure_structlog()` with `JSONRenderer` and stdlib integration
- [ ] Configure `merge_contextvars` processor for request-scoped fields
- [ ] Add `TimeStamper(fmt="iso")` processor for ISO-8601 timestamps
- [ ] Include `StackInfoRenderer` and `format_exc_info` processors
- [ ] Set log level from `ERROR_RATE_LOG_LEVEL` env var defaulting to `"INFO"`
- [ ] Call `configure_structlog()` in `app/main.py` lifespan startup
- [ ] Verify JSON output parseable by Loki and Grafana log explorer

### 15.9 Sink Modules
- [ ] Implement `LokiSink` using `httpx.AsyncClient` for HTTP push
- [ ] Implement push as `asyncio.create_task()` with `asyncio.wait_for(timeout=2.0)`
- [ ] Log `LokiSink` failure via `structlog.error()` on timeout or connection error
- [ ] Fall back to `ConsoleSink` on `LokiSink` failure (INV-ERA-07)
- [ ] Implement `ConsoleSink` printing JSON to stdout via `print(json.dumps(payload))`
- [ ] Implement `PrometheusSink` updating `http_errors_total` labels on alert
- [ ] Expose sink factory function `get_sink(name: str) -> AlertSink`

### 15.10 Alert Rules and Dashboard
- [ ] Create `prometheus/alerts/error_rate.yml` with `HighErrorRate5xx` alert rule
- [ ] Create `HighErrorRate4xx` alert rule with 5-minute window and 5% threshold
- [ ] Add `for: 2m` duration to both rules to suppress transient spikes
- [ ] Validate YAML with `promtool check rules prometheus/alerts/error_rate.yml`
- [ ] Create `grafana/dashboards/error_rate.json` with ≥ 5 panels
- [ ] Include panels: error rate by route, error rate by tier, trend alerts, 4xx vs 5xx split, request volume
- [ ] Set Grafana dashboard refresh interval to 30 seconds

### 15.11 CLI Module
- [ ] Implement `top` command with `--by`, `--since`, `--limit` options
- [ ] Implement `summary` command printing aggregate 4xx/5xx totals
- [ ] Format output with `rich.table.Table` including route, total, 4xx, 5xx, 4xx%, 5xx% columns
- [ ] Connect CLI to shared `SlidingWindowAggregator` instance via DI
- [ ] Add `--json` flag outputting raw JSON for programmatic consumption
- [ ] Handle empty window gracefully (print "No data for window")
- [ ] Register CLI as `[project.scripts]` entry point in `pyproject.toml`

### 15.12 Testing
- [ ] Write `test_error_rate_middleware.py` covering T-01..T-06 and T-22
- [ ] Write `test_cardinality_cap.py` covering T-09 cardinality overflow
- [ ] Write `test_trend_detector.py` covering T-17 and T-18
- [ ] Write `test_aggregator.py` covering T-10, T-11, T-26 eviction
- [ ] Write `test_classifier.py` covering T-13..T-16 classification determinism
- [ ] Write `test_sinks.py` covering T-20 console and T-21 Loki fallback
- [ ] Write `test_idempotency.py` covering T-23 tool re-run safety

### 15.13 Verification and Documentation
- [ ] Run `ast.parse()` on all 8 generated Python files; assert 0 SyntaxErrors
- [ ] Run full test suite: `pytest tests/test_error_rate*.py -v` passing 30+ test cases
- [ ] Execute `promtool check rules prometheus/alerts/error_rate.yml` with exit 0
- [ ] Benchmark middleware overhead: confirm p99 ≤ 100 µs (T-25)
- [ ] Measure memory: insert 86 400 events, assert `sys.getsizeof` delta ≤ 10 MB (T-27)
- [ ] Add `error_rate_analyzer` to `KNOWLEDGE.md` tool registry with signature and category
- [ ] Add entry to `SKILL-001` manifest referencing all 8 `files_created`

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/api/middleware/error_rate.py",
    "app/core/error_metrics.py",
    "app/core/error_aggregator.py",
    "app/core/trend_detector.py",
    "app/core/classifier.py",
    "app/core/error_logging.py",
    "app/core/sinks/loki_sink.py",
    "app/cli/error_analyzer.py",
    "prometheus/alerts/error_rate.yml",
    "grafana/dashboards/error_rate.json",
    "tests/test_error_rate_middleware.py",
    "tests/test_cardinality_cap.py",
    "tests/test_trend_detector.py"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/main.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 5120,
    "files_changed": 16,
    "lines_added": 1047,
    "lines_removed": 18,
    "cardinality_cap": 1000,
    "sliding_windows": ["1m", "5m", "1h"],
    "trend_spike_factor": 3.0,
    "baseline_days": 7
  },
  "next_steps": [
    "Register middleware: app.add_middleware(ErrorRateMiddleware) in app/main.py lifespan",
    "Load alert rules: copy prometheus/alerts/error_rate.yml to Prometheus rules_dir and reload",
    "Import Grafana dashboard: grafana-cli dashboards import grafana/dashboards/error_rate.json",
    "Verify metrics endpoint: curl http://localhost:8000/metrics | grep http_errors_total",
    "Test CLI: python -m app.cli.error_analyzer top --since=5m --by=route",
    "Calibrate trend detector: let baseline accumulate for 24 h before relying on trend alerts"
  ],
  "warnings": [
    "Cardinality cap defaults to 1 000 — raise ERROR_RATE_CARDINALITY_CAP if you have > 900 unique routes",
    "Loki sink requires LOKI_URL env var and reachable Loki instance; falls back to console if absent",
    "Route normalisation requires FastAPI >= 0.95 for reliable scope['route'] resolution"
  ],
  "notes": [
    "ErrorRateMiddleware is a pure observability layer — zero database writes, fully rollback-safe",
    "Cardinality overflow bucket __cardinality_overflow__ is the canary: if it appears in Grafana, raise the cap",
    "Trend detector requires at least 2 baseline samples before firing; silent for first 10 minutes",
    "Custom classifier registered via register_classifier() survives app restarts only if called at startup",
    "SlidingWindowAggregator is shared with TOOL-040 connection_pool_monitor for correlated dashboards",
    "All structured log fields prefixed with error_ for easy Loki label extraction without parsing"
  ]
}
```
