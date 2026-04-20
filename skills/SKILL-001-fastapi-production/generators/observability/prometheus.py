"""Generator for Prometheus metrics middleware (metrics.py)."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_prometheus',
    'description': 'Generate Prometheus RED metrics (Rate/Errors/Duration) with middleware and /metrics endpoint.',
    'tags': ['generator', 'observability'],
    'entry': 'generate_prometheus_metrics',
}

import textwrap
from pathlib import Path


def generate_prometheus_metrics(
    output_dir: str,
    prefix: str = "fastapi",
) -> dict:
    """Generate a Prometheus metrics module with RED pattern middleware.

    Creates ``observability/metrics.py`` with:
    * ``{prefix}_requests_total`` Counter (Rate)
    * ``{prefix}_request_duration_seconds`` Histogram (Duration)
    * ``{prefix}_requests_in_progress`` Gauge (in-flight)
    * ``{prefix}_db_query_duration_seconds`` Histogram (optional DB tracking)
    * ``PrometheusMiddleware`` that records all three request metrics
    * ``/metrics`` endpoint via ``make_asgi_app()``

    Args:
        output_dir: Directory where observability/metrics.py will be written.
        prefix: Metric name prefix (e.g. ``"fastapi"`` → ``fastapi_requests_total``).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "observability"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent("""\
        \"\"\"Prometheus metrics — RED pattern (Rate / Errors / Duration).

        Mount the metrics ASGI app and add ``PrometheusMiddleware`` to expose
        production-grade request telemetry at ``/metrics``.

        Usage::

            from observability.metrics import PrometheusMiddleware, metrics_app

            app.mount("/metrics", metrics_app)
            app.add_middleware(PrometheusMiddleware)
        \"\"\"

        from __future__ import annotations

        import time
        from typing import TYPE_CHECKING

        from prometheus_client import (
            Counter,
            Gauge,
            Histogram,
            make_asgi_app,
        )
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Match

        if TYPE_CHECKING:
            from fastapi import FastAPI

        # ---------------------------------------------------------------------------
        # RED metrics
        # ---------------------------------------------------------------------------

        REQUEST_COUNT = Counter(
            "{prefix}_requests_total",
            "Total HTTP requests.",
            ["method", "endpoint", "status"],
        )

        REQUEST_DURATION = Histogram(
            "{prefix}_request_duration_seconds",
            "HTTP request duration in seconds.",
            ["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )

        REQUESTS_IN_PROGRESS = Gauge(
            "{prefix}_requests_in_progress",
            "HTTP requests currently being processed.",
            ["method", "endpoint"],
        )

        # ---------------------------------------------------------------------------
        # Optional: database query duration
        # ---------------------------------------------------------------------------

        DB_QUERY_DURATION = Histogram(
            "{prefix}_db_query_duration_seconds",
            "Database query duration in seconds.",
            ["operation"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
        )


        # ---------------------------------------------------------------------------
        # Middleware
        # ---------------------------------------------------------------------------


        def _get_route_path(request: Request) -> str:
            \"\"\"Resolve the route template path to avoid high-cardinality labels.

            Falls back to the raw URL path when no matching route is found.
            \"\"\"
            app: FastAPI | None = request.app  # type: ignore[assignment]
            if app is None:
                return request.url.path

            for route in app.routes:
                match, _ = route.matches(request.scope)
                if match == Match.FULL:
                    return getattr(route, "path", request.url.path)

            return request.url.path


        class PrometheusMiddleware(BaseHTTPMiddleware):
            \"\"\"Record RED metrics for every HTTP request.

            * **Rate** — ``{prefix}_requests_total`` counter
            * **Errors** — same counter filtered by 5xx ``status``
            * **Duration** — ``{prefix}_request_duration_seconds`` histogram

            An in-progress gauge tracks concurrent requests.
            \"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                method = request.method
                endpoint = _get_route_path(request)

                REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
                start = time.perf_counter()

                try:
                    response = await call_next(request)
                except Exception:
                    REQUEST_COUNT.labels(
                        method=method, endpoint=endpoint, status="500"
                    ).inc()
                    raise
                else:
                    REQUEST_COUNT.labels(
                        method=method, endpoint=endpoint, status=str(response.status_code)
                    ).inc()
                    return response
                finally:
                    elapsed = time.perf_counter() - start
                    REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(elapsed)
                    REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()


        # ---------------------------------------------------------------------------
        # ASGI app for /metrics endpoint
        # ---------------------------------------------------------------------------

        metrics_app = make_asgi_app()
        \"\"\"Mount this on your FastAPI app: ``app.mount("/metrics", metrics_app)``\"\"\"
    """).format(prefix=prefix)

    file_path = out / "metrics.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"RED metrics: {prefix}_requests_total (Counter), "
            f"{prefix}_request_duration_seconds (Histogram), "
            f"{prefix}_requests_in_progress (Gauge).",
            f"Optional {prefix}_db_query_duration_seconds Histogram for DB tracing.",
            "PrometheusMiddleware records all three request metrics automatically.",
            "Route template resolution avoids high-cardinality label explosion.",
            'metrics_app (ASGI): mount with app.mount("/metrics", metrics_app).',
        ],
    }
