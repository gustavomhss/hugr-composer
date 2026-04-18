"""TOOL-086: add_prometheus_metrics — add Prometheus RED metrics to a FastAPI project.

Generates a ``RequestMetrics`` class with request_total, request_duration_seconds,
and request_errors_total counters/histograms via lazy ``prometheus_client`` import,
a ``PrometheusMiddleware`` that instruments every request, and a ``GET /metrics``
endpoint that returns text/plain in Prometheus exposition format.

The tool is idempotent: a second run detects ``app/metrics/collectors.py`` and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_prometheus_metrics import add_prometheus_metrics

    result = add_prometheus_metrics(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/metrics/collectors.py, ...]
    print(result.next_steps)    # ["pip install prometheus-client", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_prometheus_metrics",
    "description": (
        "Add Prometheus RED metrics (request_total, request_duration_seconds, "
        "request_errors_total) with lazy prometheus_client, middleware, "
        "and /metrics endpoint."
    ),
    "tags": ["extend", "infrastructure", "observability"],
    "entry": "add_prometheus_metrics",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_prometheus_metrics(inp: ToolInput) -> ToolResult:
    """Add Prometheus metrics layer to a FastAPI project.

    Writes ``app/metrics/`` package (collectors, middleware), patches
    ``app/core/config.py`` with ``PROMETHEUS_*`` fields, and adds a
    ``GET /metrics`` endpoint. All ``prometheus_client`` imports are lazy.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

    # --- Prerequisite check --------------------------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    collectors_file = app_dir / "metrics" / "collectors.py"
    if collectors_file.exists() and "RequestMetrics" in collectors_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RequestMetrics already present — Prometheus metrics already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/metrics/ package (collectors, middleware), "
                "app/api/routes/metrics.py, and patch config + main."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: metrics package ---------------------------------------------
    metrics_dir = app_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    init_file = metrics_dir / "__init__.py"
    _write_metrics_init(init_file)
    files_created.append(str(init_file))

    _write_metrics_collectors(collectors_file)
    files_created.append(str(collectors_file))

    middleware_file = metrics_dir / "middleware.py"
    _write_metrics_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 2: /metrics route ----------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        metrics_route = routes_dir / "metrics.py"
        _write_metrics_route(metrics_route)
        files_created.append(str(metrics_route))

    # --- Step 3: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 4: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 5: Patch requirements.txt --------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        if "prometheus-client" not in req_src:
            req_file.write_text(
                req_src.rstrip("\n") + "\nprometheus-client>=0.20.0\n"
            )
            files_modified.append(str(req_file))

    # --- Step 6: ast.parse validation ----------------------------------------
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
            "Prometheus RED metrics installed: request_total, request_duration_seconds, request_errors_total.",
            "All prometheus_client imports are lazy (inside function bodies) — boot safe.",
            "Histograms use latency buckets: .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10.",
            "PROMETHEUS_PREFIX env var controls metric name prefix (default: 'http').",
        ],
        next_steps=[
            "pip install 'prometheus-client>=0.20.0'",
            "Set PROMETHEUS_ENABLED=true and PROMETHEUS_PREFIX=http in .env.",
            "Scrape GET /metrics from your Prometheus server.",
            "Wire in Grafana dashboard ID 12708 for FastAPI RED metrics.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each <= 50 LOC
# ---------------------------------------------------------------------------

def _write_metrics_init(dest: Path) -> None:
    """Write ``app/metrics/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Prometheus metrics layer — public API.\"\"\"

        from app.metrics.collectors import RequestMetrics, get_metrics
        from app.metrics.middleware import PrometheusMiddleware

        __all__ = [
            "RequestMetrics",
            "get_metrics",
            "PrometheusMiddleware",
        ]
        """))


def _write_metrics_collectors(dest: Path) -> None:
    """Write ``app/metrics/collectors.py`` with RequestMetrics (lazy prometheus_client).

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"RED metrics collectors with lazy prometheus_client import.

        prometheus_client is imported inside function bodies so the app boots
        without the SDK installed (INV-04 / QS-04).
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        logger = logging.getLogger(__name__)

        _metrics: "RequestMetrics | None" = None


        class RequestMetrics:
            \"\"\"Prometheus RED metrics: request_total, duration_seconds, errors_total.

            All prometheus_client objects are created lazily on first use.

            Args:
                prefix: Metric name prefix (e.g. ``"http"``).
            \"\"\"

            def __init__(self, prefix: str = "http") -> None:
                \"\"\"Initialise metric names; prometheus_client objects built lazily.\"\"\"
                self._prefix = prefix
                self._counter: Any = None
                self._histogram: Any = None
                self._errors: Any = None

            def _ensure_initialized(self) -> None:
                \"\"\"Create prometheus_client objects on first call (lazy import).\"\"\"
                if self._counter is not None:
                    return
                import prometheus_client as prom  # noqa: PLC0415 — lazy
                p = self._prefix
                buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
                self._counter = prom.Counter(
                    f"{p}_requests_total",
                    "Total HTTP requests",
                    ["method", "path", "status"],
                )
                self._histogram = prom.Histogram(
                    f"{p}_request_duration_seconds",
                    "HTTP request latency",
                    ["method", "path"],
                    buckets=buckets,
                )
                self._errors = prom.Counter(
                    f"{p}_request_errors_total",
                    "Total HTTP errors (4xx + 5xx)",
                    ["method", "path", "status"],
                )

            def record_request(
                self,
                method: str,
                path: str,
                status: int,
                duration: float,
            ) -> None:
                \"\"\"Record one HTTP request.

                Args:
                    method: HTTP method (GET, POST, …).
                    path: URL path (normalised, no query string).
                    status: HTTP response status code.
                    duration: Request duration in seconds.
                \"\"\"
                try:
                    self._ensure_initialized()
                    labels = [method, path, str(status)]
                    self._counter.labels(*labels).inc()
                    self._histogram.labels(method, path).observe(duration)
                    if status >= 400:
                        self._errors.labels(*labels).inc()
                except Exception:
                    logger.warning("Failed to record Prometheus metric", exc_info=True)


        def get_metrics() -> "RequestMetrics | None":
            \"\"\"Return the process-wide RequestMetrics instance (None if not init).\"\"\"
            return _metrics


        def init_metrics(prefix: str = "http") -> RequestMetrics:
            \"\"\"Initialise the global RequestMetrics singleton.

            Args:
                prefix: Metric name prefix.

            Returns:
                The initialised RequestMetrics instance.
            \"\"\"
            global _metrics
            _metrics = RequestMetrics(prefix=prefix)
            return _metrics
        """))


def _write_metrics_middleware(dest: Path) -> None:
    """Write ``app/metrics/middleware.py`` with PrometheusMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"PrometheusMiddleware — instruments every request with RED metrics.\"\"\"

        from __future__ import annotations

        import logging
        import time

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.metrics.collectors import get_metrics

        logger = logging.getLogger(__name__)


        class PrometheusMiddleware(BaseHTTPMiddleware):
            \"\"\"Starlette middleware that records RED metrics for each request.

            Skips the ``/metrics`` endpoint itself to avoid self-instrumentation.
            \"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Record timing and status for every request.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware or route handler.

                Returns:
                    HTTP response, after recording metrics.
                \"\"\"
                if request.url.path == "/metrics":
                    return await call_next(request)

                start = time.monotonic()
                response = await call_next(request)
                duration = time.monotonic() - start

                metrics = get_metrics()
                if metrics is not None:
                    metrics.record_request(
                        method=request.method,
                        path=request.url.path,
                        status=response.status_code,
                        duration=duration,
                    )
                return response
        """))


def _write_metrics_route(dest: Path) -> None:
    """Write ``app/api/routes/metrics.py`` with GET /metrics endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"GET /metrics — Prometheus text format exposition endpoint.\"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, HTTPException
        from starlette.responses import Response

        logger = logging.getLogger(__name__)

        router = APIRouter(tags=["metrics"])

        _CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


        @router.get("/metrics", include_in_schema=False)
        async def prometheus_metrics() -> Response:
            \"\"\"Return all Prometheus metrics in text exposition format.

            Returns:
                ``text/plain; version=0.0.4`` response with all registered metrics.

            Raises:
                HTTPException: 503 when prometheus_client SDK is not installed.
            \"\"\"
            try:
                import prometheus_client  # noqa: PLC0415 — lazy
                data = prometheus_client.generate_latest()
                ct = getattr(prometheus_client, "CONTENT_TYPE_LATEST", _CONTENT_TYPE)
                return Response(content=data, media_type=ct)
            except ImportError:
                logger.warning("prometheus_client not installed — /metrics unavailable")
                raise HTTPException(
                    status_code=503,
                    detail="prometheus_client not installed. Run: pip install prometheus-client",
                )
        """))


def _patch_config(config_file: Path) -> None:
    """Inject PROMETHEUS_* fields into ``class Settings`` in config.py.

    Inserts fields inside the class body using the REDIS_URL field as an
    anchor (or falls back to the last field-like line inside the class).

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "PROMETHEUS_ENABLED" in src:
        return

    new_fields = (
        "\n"
        "    # Prometheus metrics — added by add_prometheus_metrics tool\n"
        "    PROMETHEUS_ENABLED: bool = True\n"
        '    PROMETHEUS_PREFIX: str = "http"\n'
    )
    # Prefer to anchor after REDIS_URL field (last plain field before methods)
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    if anchor in src:
        src = src.replace(anchor, anchor + new_fields)
    else:
        # Fallback: insert before the @model_validator or @computed_field
        # decorator that closes the plain-fields section
        for decorator in ("    @computed_field", "    @model_validator", "    @property"):
            if decorator in src:
                first_pos = src.index(decorator)
                src = src[:first_pos] + new_fields + "\n" + src[first_pos:]
                break
        else:
            # Last resort: append before settings = Settings()
            marker = "settings = Settings()"
            if marker in src:
                src = src.replace(marker, new_fields + "\n" + marker)
            else:
                src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject PrometheusMiddleware and /metrics router into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "PrometheusMiddleware" in src:
        return

    metrics_import = (
        "\nfrom app.metrics.middleware import PrometheusMiddleware"
        "  # noqa: F401 — metrics layer\n"
        "from app.metrics.collectors import init_metrics as _init_metrics\n"
        "from app.api.routes.metrics import router as _metrics_router\n"
        "import os as _prom_os\n"
    )
    add_middleware_snippet = textwrap.dedent("""\

        # Prometheus middleware + /metrics endpoint — added by add_prometheus_metrics tool
        if _prom_os.getenv("PROMETHEUS_ENABLED", "true").lower() != "false":
            _prom_prefix = _prom_os.getenv("PROMETHEUS_PREFIX", "http")
            _init_metrics(prefix=_prom_prefix)
            app.add_middleware(PrometheusMiddleware)
        app.include_router(_metrics_router)
    """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + metrics_import,
        )
    else:
        src = metrics_import + src

    src = src.rstrip("\n") + "\n" + add_middleware_snippet
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
