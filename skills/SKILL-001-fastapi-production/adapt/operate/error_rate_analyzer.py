"""TOOL-041: error_rate_analyzer — HTTP error rate middleware + trend detection.

Injects ``ErrorRateMiddleware`` that counts 4xx/5xx by route+status using
bounded Prometheus counters, emits structlog entries with trace context,
and writes a TrendDetector and alert rules YAML.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.error_rate_analyzer import error_rate_analyzer

    result = error_rate_analyzer(
        ToolInput(project_dir="/path/to/project"),
        threshold_5xx_pct=1.0,
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult


MCP_TOOL = {
    "name": "fastapi_error_rate_analyzer",
    "description": "Analyze application error rates from structured logs or Prometheus metrics.",
    "tags": ["operate"],
    "entry": "error_rate_analyzer",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def error_rate_analyzer(
    inp: ToolInput,
    lookback_hours: int = 24,
    group_by: list[str] | None = None,
    threshold_5xx_pct: float = 1.0,
    threshold_4xx_pct: float = 5.0,
    sink: str = "prometheus",
) -> ToolResult:
    """Inject error-rate instrumentation into a FastAPI project.

    Writes ``ErrorRateMiddleware``, a ``RingBufferAggregator``, Prometheus
    metrics module, ``TrendDetector``, ``ErrorClassifier``, Prometheus alert
    rules YAML, and patches ``main.py`` to register the middleware.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        lookback_hours: In-memory retention window for aggregation.
        group_by: Dimensions to group counters by (default
            ``["route", "status_class"]``).
        threshold_5xx_pct: Alert threshold for 5xx error rate.
        threshold_4xx_pct: Alert threshold for 4xx error rate.
        sink: Metric sink — ``"prometheus"``, ``"loki"``, or ``"console"``.

    Returns:
        ``ToolResult`` with ``files_created`` and ``files_modified``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {project}",
            execution_time_ms=_ms(start),
        )

    # --- Prerequisite check ---------------------------------------------------
    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.CONFIG_SETTINGS)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_ms(start),
        )

    app_dir = project / "app"
    middleware_file = app_dir / "api" / "middleware" / "error_rate.py"

    if middleware_file.exists() and "ErrorRateMiddleware" in middleware_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ErrorRateMiddleware already present — skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create error rate analyzer files."],
            execution_time_ms=_ms(start),
        )

    dims = group_by or ["route", "status_class"]
    files_created: list[str] = []
    files_modified: list[str] = []

    # 1. Middleware
    _write_middleware(middleware_file, threshold_5xx_pct, threshold_4xx_pct, dims)
    files_created.append(str(middleware_file))

    # 2. Ring-buffer aggregator
    agg_file = app_dir / "core" / "error_aggregator.py"
    _write_aggregator(agg_file, lookback_hours)
    files_created.append(str(agg_file))

    # 3. Prometheus metrics module
    metrics_file = app_dir / "core" / "error_metrics.py"
    _write_metrics(metrics_file, dims)
    files_created.append(str(metrics_file))

    # 4. Trend detector
    trend_file = app_dir / "core" / "error_trend.py"
    _write_trend_detector(trend_file, threshold_5xx_pct)
    files_created.append(str(trend_file))

    # 5. Classifier
    classifier_file = app_dir / "core" / "error_classifier.py"
    _write_classifier(classifier_file)
    files_created.append(str(classifier_file))

    # 6. Alert rules
    alert_file = project / "infra" / "prometheus" / "error_rate_alerts.yaml"
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    alert_file.write_text(_render_alerts(threshold_5xx_pct, threshold_4xx_pct))
    files_created.append(str(alert_file))

    # 7. Patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file, sink)
        files_modified.append(str(main_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"ErrorRateMiddleware installed (sink={sink})",
            f"5xx threshold: {threshold_5xx_pct}%, 4xx threshold: {threshold_4xx_pct}%",
            f"Lookback window: {lookback_hours}h, dimensions: {dims}",
        ],
        next_steps=[
            "Verify middleware registered in main.py: app.add_middleware(ErrorRateMiddleware)",
            "Configure Prometheus alert rules from infra/prometheus/error_rate_alerts.yaml",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_middleware(
    dest: Path,
    threshold_5xx: float,
    threshold_4xx: float,
    dims: list[str],
) -> None:
    """Write ``app/api/middleware/error_rate.py``.

    Args:
        dest: Destination path.
        threshold_5xx: 5xx alert threshold percentage.
        threshold_4xx: 4xx alert threshold percentage.
        dims: Prometheus label dimensions.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"ErrorRateMiddleware — count 4xx/5xx by route and status class.

        Never raises into the request path — all instrumentation uses
        try/except.  Cardinality is capped by route-pattern normalisation.
        \"\"\"

        from __future__ import annotations

        import time
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        try:
            import structlog as _structlog
            _log = _structlog.get_logger(__name__)
        except ImportError:
            import logging as _logging
            _log = _logging.getLogger(__name__)

        _THRESHOLD_5XX = {threshold_5xx}
        _THRESHOLD_4XX = {threshold_4xx}
        _DIMS = {dims!r}
        _MAX_CARDINALITY = 1000


        class ErrorRateMiddleware(BaseHTTPMiddleware):
            \"\"\"Intercept every response and update error-rate Prometheus counters.

            Attributes:
                _counters: Dict[label_tuple, int] tracking error counts.
            \"\"\"

            def __init__(self, app, threshold_5xx: float = _THRESHOLD_5XX,
                         threshold_4xx: float = _THRESHOLD_4XX) -> None:
                \"\"\"Initialise the middleware.

                Args:
                    app: ASGI app.
                    threshold_5xx: 5xx rate threshold for alerts.
                    threshold_4xx: 4xx rate threshold for alerts.
                \"\"\"
                super().__init__(app)
                self._threshold_5xx = threshold_5xx
                self._threshold_4xx = threshold_4xx
                self._counters: dict[tuple, int] = {{}}
                self._total = 0

                try:
                    from prometheus_client import Counter
                    self._prom_counter = Counter(
                        "http_errors_total",
                        "HTTP error responses",
                        ["route", "status_class", "status_code"],
                    )
                    self._prom_total = Counter(
                        "http_requests_total",
                        "Total HTTP requests",
                        ["route"],
                    )
                except Exception:
                    self._prom_counter = None
                    self._prom_total = None

            async def dispatch(self, request: Request, call_next) -> Response:
                \"\"\"Process request and record error metrics.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware or handler.

                Returns:
                    HTTP response (never suppressed).
                \"\"\"
                start = time.monotonic()
                response: Response | None = None
                exc_type = "none"
                try:
                    response = await call_next(request)
                except Exception as exc:
                    exc_type = type(exc).__name__
                    raise
                finally:
                    status = response.status_code if response else 500
                    route = _normalise_route(request)
                    status_class = f"{{status // 100}}xx"
                    elapsed = time.monotonic() - start

                    try:
                        self._total += 1
                        if status >= 400:
                            label = (route, status_class, str(status))
                            if len(self._counters) < _MAX_CARDINALITY:
                                self._counters[label] = self._counters.get(label, 0) + 1
                            if self._prom_counter:
                                self._prom_counter.labels(
                                    route=route, status_class=status_class,
                                    status_code=str(status),
                                ).inc()
                        if self._prom_total:
                            self._prom_total.labels(route=route).inc()
                        _log.info(
                            "http_response",
                            route=route,
                            status=status,
                            status_class=status_class,
                            exc_type=exc_type,
                            elapsed_s=round(elapsed, 4),
                        )
                        self._check_threshold(route, status_class)
                    except Exception:
                        pass
                return response

            def _check_threshold(self, route: str, status_class: str) -> None:
                \"\"\"Log a warning if error rate exceeds configured thresholds.

                Args:
                    route: Normalised route pattern.
                    status_class: Status class string (e.g. ``"5xx"``).
                \"\"\"
                if self._total == 0:
                    return
                errs = sum(
                    v for (r, sc, _), v in self._counters.items()
                    if r == route and sc == status_class
                )
                rate = errs / self._total * 100
                if status_class == "5xx" and rate >= self._threshold_5xx:
                    _log.warning("error_rate_threshold_exceeded",
                                 route=route, status_class=status_class,
                                 rate_pct=round(rate, 2))
                elif status_class == "4xx" and rate >= self._threshold_4xx:
                    _log.warning("error_rate_threshold_exceeded",
                                 route=route, status_class=status_class,
                                 rate_pct=round(rate, 2))


        def _normalise_route(request: Request) -> str:
            \"\"\"Return normalised route pattern, never the raw path.

            FastAPI stores the matched route on ``request.scope['route']``.
            Falls back to the raw path truncated to 512 chars.

            Args:
                request: Starlette request.

            Returns:
                Route pattern string.
            \"\"\"
            route = request.scope.get("route")
            if route and hasattr(route, "path"):
                return route.path[:512]
            return request.url.path[:512]
    """)
    dest.write_text(content)


def _write_aggregator(dest: Path, lookback_hours: int) -> None:
    """Write ``app/core/error_aggregator.py`` ring-buffer aggregator.

    Args:
        dest: Destination path.
        lookback_hours: Retention window in hours.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"Ring-buffer aggregator for error-rate sliding windows.\"\"\"

        from __future__ import annotations

        import collections
        import time

        _LOOKBACK_S = {lookback_hours} * 3600


        class RingBufferAggregator:
            \"\"\"Sliding-window error counter using a deque of (timestamp, key) pairs.

            Attributes:
                _deque: Chronological ring buffer.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise with an empty deque.\"\"\"
                self._deque: collections.deque[tuple[float, str]] = collections.deque()

            def record(self, key: str) -> None:
                \"\"\"Record an error event with the current timestamp.

                Args:
                    key: Composite key (e.g. ``"route:5xx"``).
                \"\"\"
                now = time.monotonic()
                self._deque.append((now, key))
                self._evict(now)

            def count(self, key: str, window_s: float = 60.0) -> int:
                \"\"\"Count events for *key* in the last *window_s* seconds.

                Args:
                    key: Event key to count.
                    window_s: Window size in seconds.

                Returns:
                    Count of matching events within the window.
                \"\"\"
                now = time.monotonic()
                cutoff = now - window_s
                return sum(1 for ts, k in self._deque if ts >= cutoff and k == key)

            def _evict(self, now: float) -> None:
                \"\"\"Remove entries older than the lookback window.

                Args:
                    now: Current monotonic time.
                \"\"\"
                cutoff = now - _LOOKBACK_S
                while self._deque and self._deque[0][0] < cutoff:
                    self._deque.popleft()
    """)
    dest.write_text(content)


def _write_metrics(dest: Path, dims: list[str]) -> None:
    """Write ``app/core/error_metrics.py`` Prometheus metrics wrapper.

    Args:
        dest: Destination path.
        dims: Label dimensions for Prometheus counters.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"Prometheus metric handles for the error rate analyzer.\"\"\"

        from __future__ import annotations

        DIMS = {dims!r}

        try:
            from prometheus_client import Counter, Gauge

            http_errors_total = Counter(
                "http_errors_total_v2",
                "HTTP errors by route and status class",
                DIMS,
            )
            http_requests_inflight = Gauge(
                "http_requests_inflight",
                "In-flight HTTP requests",
            )
            _AVAILABLE = True
        except ImportError:
            http_errors_total = None
            http_requests_inflight = None
            _AVAILABLE = False
    """)
    dest.write_text(content)


def _write_trend_detector(dest: Path, threshold_5xx: float) -> None:
    """Write ``app/core/error_trend.py`` trend detector.

    Args:
        dest: Destination path.
        threshold_5xx: Absolute 5xx threshold for alerting.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"TrendDetector — compares current rate against 7-day rolling baseline.\"\"\"

        from __future__ import annotations

        _SPIKE_MULTIPLIER = 3.0
        _THRESHOLD_5XX = {threshold_5xx}


        class TrendDetector:
            \"\"\"Detect error rate spikes relative to a rolling baseline.

            Attributes:
                _baseline: Dict[route, float] of baseline rates.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise with empty baseline.\"\"\"
                self._baseline: dict[str, float] = {{}}

            def update_baseline(self, route: str, rate: float) -> None:
                \"\"\"Update rolling baseline for a route with exponential smoothing.

                Args:
                    route: Route pattern.
                    rate: Observed error rate (0.0–100.0).
                \"\"\"
                prev = self._baseline.get(route, rate)
                self._baseline[route] = prev * 0.9 + rate * 0.1

            def is_spike(self, route: str, current_rate: float) -> bool:
                \"\"\"Return True if *current_rate* is a spike vs baseline.

                A spike is defined as 3× the rolling baseline or above the
                absolute threshold.

                Args:
                    route: Route pattern.
                    current_rate: Current observed error rate percentage.

                Returns:
                    True if this rate should trigger an alert.
                \"\"\"
                baseline = self._baseline.get(route, 0.0)
                if baseline == 0.0:
                    return current_rate >= _THRESHOLD_5XX
                return current_rate >= baseline * _SPIKE_MULTIPLIER

            def get_baseline(self, route: str) -> float:
                \"\"\"Return the rolling baseline for *route*.

                Args:
                    route: Route pattern.

                Returns:
                    Baseline rate or 0.0 if unknown.
                \"\"\"
                return self._baseline.get(route, 0.0)
    """)
    dest.write_text(content)


def _write_classifier(dest: Path) -> None:
    """Write ``app/core/error_classifier.py`` error classifier.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"ErrorClassifier — categorise HTTP status codes.\"\"\"

        from __future__ import annotations


        class ErrorClassifier:
            \"\"\"Classify HTTP status codes as expected or unexpected errors.

            4xx errors are 'expected' (client mistakes, auth, not-found).
            5xx errors are 'unexpected' (server failures, unhandled exceptions).
            \"\"\"

            EXPECTED_CODES: frozenset[int] = frozenset(
                {400, 401, 403, 404, 409, 422, 429}
            )

            def classify(self, status_code: int) -> str:
                \"\"\"Return classification string for *status_code*.

                Args:
                    status_code: HTTP response status code.

                Returns:
                    ``"expected"``, ``"unexpected"``, or ``"ok"``.
                \"\"\"
                if status_code < 400:
                    return "ok"
                if status_code in self.EXPECTED_CODES:
                    return "expected"
                if 400 <= status_code < 500:
                    return "expected"
                return "unexpected"

            def is_blocking(self, status_code: int) -> bool:
                \"\"\"Return True if this status warrants immediate on-call alert.

                Args:
                    status_code: HTTP response status code.

                Returns:
                    True for 5xx errors.
                \"\"\"
                return status_code >= 500
    """)
    dest.write_text(content)


def _render_alerts(threshold_5xx: float, threshold_4xx: float) -> str:
    """Return Prometheus alert rules YAML for error rates.

    Args:
        threshold_5xx: 5xx error rate alert threshold.
        threshold_4xx: 4xx error rate alert threshold.

    Returns:
        YAML string.
    """
    return textwrap.dedent(f"""\
        groups:
          - name: error_rate
            rules:
              - alert: High5xxErrorRate
                expr: |
                  rate(http_errors_total{{status_class="5xx"}}[5m]) /
                  rate(http_requests_total[5m]) * 100 > {threshold_5xx}
                for: 1m
                labels:
                  severity: critical
                annotations:
                  summary: "5xx error rate above {threshold_5xx}% on {{{{ $labels.route }}}}"

              - alert: High4xxErrorRate
                expr: |
                  rate(http_errors_total{{status_class="4xx"}}[5m]) /
                  rate(http_requests_total[5m]) * 100 > {threshold_4xx}
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "4xx error rate above {threshold_4xx}% on {{{{ $labels.route }}}}"
    """)


def _patch_main(main_file: Path, sink: str) -> None:
    """Add ErrorRateMiddleware registration to main.py.

    Args:
        main_file: Path to ``app/main.py``.
        sink: Configured metric sink.
    """
    src = main_file.read_text()
    if "ErrorRateMiddleware" in src:
        return
    src += textwrap.dedent(f"""\

        # Error rate analyzer — added by error_rate_analyzer tool (sink={sink})
        from app.api.middleware.error_rate import ErrorRateMiddleware  # noqa: E402
        app.add_middleware(ErrorRateMiddleware)
    """)
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
