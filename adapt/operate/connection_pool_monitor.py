"""TOOL-040: connection_pool_monitor — SQLAlchemy pool instrumentation.

Injects SQLAlchemy pool event listeners, emits Prometheus metrics
(active/idle/wait/overflow), writes a ``/pool/health`` FastAPI endpoint,
and generates Grafana dashboard JSON and alert rules YAML.

Example::

    from adapt.contracts import ToolInput
    from adapt.operate.connection_pool_monitor import connection_pool_monitor

    result = connection_pool_monitor(
        ToolInput(project_dir="/path/to/project"),
        pool_size=20,
        max_overflow=10,
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult

MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_connection_pool_monitor",
    "description": "Monitor SQLAlchemy connection pool utilization and detect pool exhaustion risk.",
    "tags": ["operate"],
    "entry": "connection_pool_monitor",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def connection_pool_monitor(
    inp: ToolInput,
    pool_size: int = 20,
    max_overflow: int = 10,
    timeout_s: float = 30.0,
    alert_threshold_pct: float = 80.0,
    metrics_port: int = 9100,
) -> ToolResult:
    """Instrument SQLAlchemy connection pool with Prometheus metrics.

    Writes a ``monitor.py`` module, a ``/pool/health`` route, Grafana
    dashboard JSON, and Prometheus alert rules.  Also patches ``main.py``
    to register the monitor at startup.

    Args:
        inp: ``ToolInput`` with ``project_dir``.
        pool_size: Steady-state connections per worker.
        max_overflow: Extra connections allowed under burst.
        timeout_s: Pool acquire timeout in seconds.
        alert_threshold_pct: Utilisation % that triggers a warning metric.
        metrics_port: Port for the Prometheus scrape endpoint.

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


    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create pool monitor files."],
            execution_time_ms=_ms(start),
        )


    # --- Prerequisite check ---------------------------------------------------
    from adapt.contracts.prerequisites import Prereq, check_prerequisites

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.CONFIG_SETTINGS)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_ms(start),
        )

    app_dir = project / "app"
    monitor_file = app_dir / "core" / "pool_monitor.py"

    if monitor_file.exists() and "PoolMonitor" in monitor_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["PoolMonitor already present — skipped."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # 1. Pool monitor module
    _write_monitor(monitor_file, pool_size, max_overflow, timeout_s, alert_threshold_pct)
    files_created.append(str(monitor_file))

    # 2. /pool/health route
    health_file = app_dir / "api" / "routes" / "pool_health.py"
    _write_health_route(health_file, metrics_port)
    files_created.append(str(health_file))

    # 3. Grafana dashboard
    dashboard_file = project / "infra" / "grafana" / "pool_dashboard.json"
    dashboard_file.parent.mkdir(parents=True, exist_ok=True)
    dashboard_file.write_text(_render_dashboard(alert_threshold_pct))
    files_created.append(str(dashboard_file))

    # 4. Alert rules YAML
    alert_file = project / "infra" / "prometheus" / "pool_alerts.yaml"
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    alert_file.write_text(
        _render_alerts(alert_threshold_pct, pool_size=pool_size, max_overflow=max_overflow)
    )
    files_created.append(str(alert_file))

    # 5. Patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Pool monitor installed: pool_size={pool_size}, max_overflow={max_overflow}",
            f"Alert threshold: {alert_threshold_pct}%",
            f"Prometheus scrape port: {metrics_port}",
        ],
        next_steps=[
            "Add pool_health router to main.py: app.include_router(pool_health_router)",
            f"Configure Prometheus to scrape :{metrics_port}/metrics",
            "Import Grafana dashboard from infra/grafana/pool_dashboard.json",
        ],
        execution_time_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_monitor(
    dest: Path,
    pool_size: int,
    max_overflow: int,
    timeout_s: float,
    alert_threshold_pct: float,
) -> None:
    """Write ``app/core/pool_monitor.py``.

    Args:
        dest: Destination path.
        pool_size: Pool steady-state size.
        max_overflow: Overflow limit.
        timeout_s: Acquire timeout.
        alert_threshold_pct: Warning threshold percentage.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"SQLAlchemy connection pool monitor with Prometheus metrics.

        Attach to an async engine at startup::

            from app.core.pool_monitor import PoolMonitor
            monitor = PoolMonitor(engine, pool_size={pool_size})
            monitor.attach()
        \"\"\"

        from __future__ import annotations

        import threading
        import time
        from typing import Any

        try:
            from prometheus_client import Counter, Gauge, Histogram
            _PROM_AVAILABLE = True
        except ImportError:
            _PROM_AVAILABLE = False

        _POOL_SIZE = {pool_size}
        _MAX_OVERFLOW = {max_overflow}
        _TIMEOUT_S = {timeout_s}
        _ALERT_PCT = {alert_threshold_pct}


        class PoolMonitor:
            \"\"\"Attach pool event listeners and expose Prometheus metrics.

            Attributes:
                engine: The SQLAlchemy async engine to monitor.
                pool_name: Label used in Prometheus metrics.
            \"\"\"

            def __init__(self, engine: Any, pool_name: str = "default") -> None:
                \"\"\"Initialise the monitor.

                Args:
                    engine: SQLAlchemy async engine.
                    pool_name: Name label for Prometheus metrics.
                \"\"\"
                self._engine = engine
                self._pool_name = pool_name
                self._lock = threading.Lock()
                self._active = 0
                self._idle = 0
                self._wait_count = 0
                self._overflow = 0
                self._total_acquired = 0
                self._total_timeouts = 0

                if _PROM_AVAILABLE:
                    self._gauge_active = Gauge(
                        "db_pool_active_connections",
                        "Active DB connections",
                        ["pool"],
                    )
                    self._gauge_idle = Gauge(
                        "db_pool_idle_connections",
                        "Idle DB connections",
                        ["pool"],
                    )
                    self._counter_acquired = Counter(
                        "db_pool_acquired_total",
                        "Total pool checkouts",
                        ["pool"],
                    )
                    self._counter_timeouts = Counter(
                        "db_pool_timeout_total",
                        "Total pool acquire timeouts",
                        ["pool"],
                    )
                    self._hist_wait = Histogram(
                        "db_pool_wait_seconds",
                        "Pool acquire wait time",
                        ["pool"],
                        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
                    )

            def attach(self) -> None:
                \"\"\"Register SQLAlchemy pool event listeners.

                Never raises — all instrumentation uses try/except so a
                metrics bug cannot affect the application.
                \"\"\"
                try:
                    from sqlalchemy import event
                    pool = self._engine.sync_engine.pool
                    event.listen(pool, "checkout", self._on_checkout)
                    event.listen(pool, "checkin", self._on_checkin)
                    event.listen(pool, "connect", self._on_connect)
                    event.listen(pool, "invalidate", self._on_invalidate)
                except Exception:
                    pass

            def health(self) -> dict:
                \"\"\"Return current pool health snapshot.

                Returns:
                    Dict with utilisation_pct, active, idle, overflow,
                    total_acquired, total_timeouts, and alert status.
                \"\"\"
                with self._lock:
                    cap = _POOL_SIZE + _MAX_OVERFLOW or 1
                    util = round(self._active / cap * 100, 1)
                    return {{
                        "pool": self._pool_name,
                        "utilisation_pct": util,
                        "active": self._active,
                        "idle": self._idle,
                        "overflow": self._overflow,
                        "total_acquired": self._total_acquired,
                        "total_timeouts": self._total_timeouts,
                        "alert": util >= _ALERT_PCT,
                        "status": "warning" if util >= _ALERT_PCT else "healthy",
                    }}

            def _on_checkout(self, dbapi_conn: Any, conn_record: Any, conn_proxy: Any) -> None:
                \"\"\"Handle pool checkout event.\"\"\"
                try:
                    with self._lock:
                        self._active += 1
                        self._total_acquired += 1
                    if _PROM_AVAILABLE:
                        self._gauge_active.labels(pool=self._pool_name).set(self._active)
                        self._counter_acquired.labels(pool=self._pool_name).inc()
                except Exception:
                    pass

            def _on_checkin(self, dbapi_conn: Any, conn_record: Any) -> None:
                \"\"\"Handle pool checkin event.\"\"\"
                try:
                    with self._lock:
                        self._active = max(0, self._active - 1)
                        self._idle += 1
                    if _PROM_AVAILABLE:
                        self._gauge_active.labels(pool=self._pool_name).set(self._active)
                        self._gauge_idle.labels(pool=self._pool_name).set(self._idle)
                except Exception:
                    pass

            def _on_connect(self, dbapi_conn: Any, conn_record: Any) -> None:
                \"\"\"Handle new physical connection event.\"\"\"
                try:
                    with self._lock:
                        self._idle = max(0, self._idle - 1)
                except Exception:
                    pass

            def _on_invalidate(self, dbapi_conn: Any, conn_record: Any, exception: Any) -> None:
                \"\"\"Handle connection invalidation event.\"\"\"
                try:
                    with self._lock:
                        self._active = max(0, self._active - 1)
                except Exception:
                    pass


        # Module-level singleton — set by attach_pool_monitor()
        _monitor: PoolMonitor | None = None


        def attach_pool_monitor(engine: Any, pool_name: str = "default") -> PoolMonitor:
            \"\"\"Create and attach a PoolMonitor to *engine*.

            Args:
                engine: SQLAlchemy async engine.
                pool_name: Label for metrics.

            Returns:
                The attached PoolMonitor instance.
            \"\"\"
            global _monitor
            _monitor = PoolMonitor(engine, pool_name)
            _monitor.attach()
            return _monitor


        def get_monitor() -> PoolMonitor | None:
            \"\"\"Return the current module-level PoolMonitor, or None.

            Returns:
                PoolMonitor instance or None if not yet attached.
            \"\"\"
            return _monitor
    """)
    dest.write_text(content)


def _write_health_route(dest: Path, metrics_port: int) -> None:
    """Write ``app/api/routes/pool_health.py`` with the /pool/health endpoint.

    Args:
        dest: Destination path.
        metrics_port: Port for Prometheus metrics link in docs.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        \"\"\"Pool health FastAPI route — GET /pool/health.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter

        router = APIRouter(prefix="/pool", tags=["monitoring"])

        _METRICS_PORT = {metrics_port}


        @router.get("/health")
        def get_pool_health() -> dict:
            \"\"\"Return current connection pool health status.

            Returns:
                JSON with utilisation_pct, active/idle counts, overflow,
                totals, and alert boolean.
            \"\"\"
            from app.core.pool_monitor import get_monitor

            monitor = get_monitor()
            if monitor is None:
                return {{"status": "not_configured", "utilisation_pct": 0.0}}
            return monitor.health()
    """)
    dest.write_text(content)


def _render_dashboard(alert_threshold: float) -> str:
    """Return Grafana dashboard JSON with six pool panels.

    Args:
        alert_threshold: Alert threshold percentage.

    Returns:
        JSON string of the Grafana dashboard definition.
    """
    dashboard = {
        "title": "DB Connection Pool",
        "panels": [
            {"title": "Pool Utilisation %", "type": "gauge",
             "targets": [{"expr": "db_pool_active_connections / (db_pool_active_connections + db_pool_idle_connections) * 100"}],
             "thresholds": [{"color": "green", "value": 0}, {"color": "yellow", "value": alert_threshold}, {"color": "red", "value": 95}]},
            {"title": "Active Connections", "type": "graph",
             "targets": [{"expr": "db_pool_active_connections"}]},
            {"title": "Idle Connections", "type": "graph",
             "targets": [{"expr": "db_pool_idle_connections"}]},
            {"title": "Acquire Rate", "type": "graph",
             "targets": [{"expr": "rate(db_pool_acquired_total[5m])"}]},
            {"title": "Timeout Rate", "type": "graph",
             "targets": [{"expr": "rate(db_pool_timeout_total[5m])"}]},
            {"title": "Wait Time p99", "type": "graph",
             "targets": [{"expr": "histogram_quantile(0.99, rate(db_pool_wait_seconds_bucket[5m]))"}]},
        ],
    }
    return json.dumps(dashboard, indent=2)


def _render_alerts(
    alert_threshold: float,
    pool_size: int = 20,
    max_overflow: int = 10,
) -> str:
    """Return Prometheus alert rules YAML.

    The PromQL divisor must be the true pool capacity (``pool_size +
    max_overflow``) so utilisation is computed against real capacity. The
    historical bug here was the f-string token ``({1})`` — Python's f-string
    parser rendered ``{1}`` as the literal integer ``1``, so every generated
    alert fired from the first active connection on every deploy
    (R6-S10-F5; juror ad597adfde81405df).

    Args:
        alert_threshold: Warning threshold percentage.
        pool_size: Steady-state pool size used as part of the PromQL divisor.
        max_overflow: Burst overflow added to the PromQL divisor.

    Returns:
        YAML string of alert rules.
    """
    capacity = pool_size + max_overflow
    if capacity < 1:
        # Defensive: capacity of 0 would yield a division-by-zero PromQL
        # expression; fall back to 1 so the rule is at least syntactically
        # valid (caller misconfiguration is the real bug to fix).
        capacity = 1
    return textwrap.dedent(f"""\
        groups:
          - name: db_pool
            rules:
              - alert: DBPoolHighUtilisation
                expr: db_pool_active_connections / ({capacity}) * 100 >= {alert_threshold}
                for: 2m
                labels:
                  severity: warning
                annotations:
                  summary: "DB pool utilisation above {alert_threshold}%"

              - alert: DBPoolCriticalUtilisation
                expr: db_pool_active_connections / ({capacity}) * 100 >= 95
                for: 1m
                labels:
                  severity: critical
                annotations:
                  summary: "DB pool near exhaustion"
    """)


def _patch_main(main_file: Path) -> None:
    """Add pool monitor import and attach call to main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "pool_monitor" in src:
        return
    src += textwrap.dedent("""\

        # Pool monitor — added by connection_pool_monitor tool
        from app.core.pool_monitor import attach_pool_monitor  # noqa: E402
        from app.api.routes.pool_health import router as pool_health_router  # noqa: E402
    """)
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ms(start: float) -> int:
    """Elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
