"""
SKILL-001 Observability Tool: Generate production OpenTelemetry setup for FastAPI.

Creates a complete observability module with OTel tracing (TracerProvider,
BatchSpanProcessor, OTLP exporter), Prometheus RED metrics (Counter, Histogram,
Gauge), and structlog configuration with OTel trace context injection.

Generated files:
    observability/telemetry.py      -- OTel TracerProvider + auto-instrumentation
    observability/metrics.py        -- Prometheus RED metrics + middleware
    observability/logging_config.py -- structlog + OTel trace_id/span_id injection
    observability/__init__.py       -- Public API re-exports
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_observability_generate_otel_stack',
    'description': 'Generate production OpenTelemetry setup for FastAPI: TracerProvider, OTLP exporter, Prometheus RED metrics, structlog.',
    'tags': ['observability', 'generator'],
    'entry': 'generate_otel_setup',
    'annotations': {'readOnlyHint': False, 'destructiveHint': False},
}

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _telemetry_py(service_name: str, exporter: str, with_sqlalchemy: bool, with_httpx: bool) -> str:
    """Template for observability/telemetry.py -- OTel setup + auto-instrumentation."""

    exporter_import = ""
    exporter_create = ""
    if exporter == "otlp":
        exporter_import = textwrap.dedent("""\
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        """)
        exporter_create = textwrap.dedent("""\
                exporter = OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    insecure=otlp_insecure,
                )
        """)
    elif exporter == "otlp-http":
        exporter_import = textwrap.dedent("""\
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        """)
        exporter_create = textwrap.dedent("""\
                exporter = OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                )
        """)
    elif exporter == "console":
        exporter_import = textwrap.dedent("""\
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        """)
        exporter_create = textwrap.dedent("""\
                exporter = ConsoleSpanExporter()
        """)

    sqlalchemy_import = ""
    sqlalchemy_instrument = ""
    if with_sqlalchemy:
        sqlalchemy_import = textwrap.dedent("""\
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        """)
        sqlalchemy_instrument = textwrap.dedent("""\

            def instrument_sqlalchemy(engine) -> None:
                \"\"\"Instrument a SQLAlchemy engine for distributed tracing.

                Call after setup_telemetry() and after creating your engine.
                enable_commenter appends traceparent as a SQL comment for DB-side
                correlation with slow query logs.
                \"\"\"
                SQLAlchemyInstrumentor().instrument(
                    engine=engine,
                    enable_commenter=True,
                )
        """)

    httpx_import = ""
    httpx_instrument = ""
    if with_httpx:
        httpx_import = textwrap.dedent("""\
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        """)
        httpx_instrument = textwrap.dedent("""\

            def instrument_httpx() -> None:
                \"\"\"Instrument all httpx clients for outbound HTTP tracing.

                Call after setup_telemetry(). Automatically creates child spans
                for every httpx.AsyncClient/Client request and propagates
                W3C traceparent headers to downstream services.
                \"\"\"
                HTTPXClientInstrumentor().instrument()
        """)

    return textwrap.dedent(f"""\
        \"\"\"OpenTelemetry setup — TracerProvider, auto-instrumentation, and sampling.

        Call setup_telemetry() ONCE at application startup, BEFORE creating the
        FastAPI app or calling any auto-instrumentors. The recommended place is
        inside the lifespan context manager, before the yield statement.

        Environment variables (override code defaults):
            OTEL_SERVICE_NAME          — Service name for resource
            OTEL_EXPORTER_OTLP_ENDPOINT — OTLP collector endpoint
            OTEL_TRACES_SAMPLER        — Sampler (e.g., parentbased_traceidratio)
            OTEL_TRACES_SAMPLER_ARG    — Sampler argument (e.g., 0.1 for 10%)
        \"\"\"

        from __future__ import annotations

        import os

        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
        {exporter_import}{sqlalchemy_import}{httpx_import}

        # ---------------------------------------------------------------------------
        # Module-level tracer (usable after setup_telemetry is called)
        # ---------------------------------------------------------------------------

        tracer = trace.get_tracer(__name__)

        _TELEMETRY_INITIALIZED = False


        def setup_telemetry(
            service_name: str = "{service_name}",
            otlp_endpoint: str | None = None,
            otlp_insecure: bool = True,
            sample_rate: float = 1.0,
        ) -> None:
            \"\"\"Initialize OpenTelemetry with OTLP exporter and BatchSpanProcessor.

            Must be called ONCE before any auto-instrumentation or manual span
            creation. Safe to call multiple times (subsequent calls are no-ops).

            Args:
                service_name: Identifies this service in traces. Override via
                    OTEL_SERVICE_NAME env var.
                otlp_endpoint: Collector endpoint. Override via
                    OTEL_EXPORTER_OTLP_ENDPOINT env var.
                otlp_insecure: Use insecure (non-TLS) connection. Set to False
                    in production with TLS-enabled collector.
                sample_rate: Fraction of traces to sample (0.0-1.0). 1.0 = 100%.
                    Override via OTEL_TRACES_SAMPLER_ARG env var.
            \"\"\"
            global _TELEMETRY_INITIALIZED
            if _TELEMETRY_INITIALIZED:
                return
            _TELEMETRY_INITIALIZED = True

            # Allow env var overrides (OTel convention)
            service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
            otlp_endpoint = otlp_endpoint or os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
            )
            sample_rate_str = os.getenv("OTEL_TRACES_SAMPLER_ARG")
            if sample_rate_str is not None:
                sample_rate = float(sample_rate_str)

            # Resource: metadata attached to every span
            resource = Resource.create({{
                SERVICE_NAME: service_name,
                "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
                "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            }})

            # Sampler: ParentBased respects upstream sampling decisions.
            # If parent was sampled, child is always sampled regardless of rate.
            sampler = ParentBasedTraceIdRatio(sample_rate)

            provider = TracerProvider(resource=resource, sampler=sampler)

            # Exporter + BatchSpanProcessor: buffer and export asynchronously
        {exporter_create}    provider.add_span_processor(BatchSpanProcessor(exporter))

            trace.set_tracer_provider(provider)


        def instrument_fastapi(app, excluded_urls: str | None = None) -> None:
            \"\"\"Auto-instrument a FastAPI app for HTTP request tracing.

            Creates spans for every HTTP request with method, route, status code,
            and latency. Propagates W3C traceparent headers.

            Args:
                app: The FastAPI application instance.
                excluded_urls: Comma-separated URL paths to exclude from tracing
                    (e.g., health checks, metrics endpoint).
            \"\"\"
            excluded = excluded_urls or "healthz,readyz,startupz,metrics"
            FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)
        {sqlalchemy_instrument}{httpx_instrument}""")


def _metrics_py(with_prometheus: bool) -> str:
    """Template for observability/metrics.py -- Prometheus RED metrics + middleware."""

    if not with_prometheus:
        return textwrap.dedent("""\
            \"\"\"Metrics placeholder — Prometheus not enabled.

            To enable Prometheus metrics, regenerate with with_prometheus=True.
            \"\"\"

            # No-op middleware for compatibility
            class MetricsMiddleware:
                \"\"\"No-op metrics middleware.\"\"\"
                def __init__(self, app):
                    self.app = app
                async def __call__(self, scope, receive, send):
                    await self.app(scope, receive, send)
        """)

    return textwrap.dedent("""\
        \"\"\"Prometheus RED metrics for FastAPI — Rate, Errors, Duration.

        Implements the RED method with three core metrics:
        - http_requests_total (Counter): request rate by method/endpoint/status
        - http_request_duration_seconds (Histogram): latency distribution
        - http_requests_in_progress (Gauge): concurrent request saturation

        Health check endpoints (/healthz, /readyz, /startupz, /metrics) are
        excluded from business metrics to prevent probe traffic from skewing SLIs.

        Usage:
            from observability.metrics import PrometheusMiddleware, metrics_endpoint
            app.add_middleware(PrometheusMiddleware)
            app.add_route("/metrics", metrics_endpoint)
        \"\"\"

        from __future__ import annotations

        import time

        from prometheus_client import (
            CONTENT_TYPE_LATEST,
            REGISTRY,
            Counter,
            Gauge,
            Histogram,
            Info,
            generate_latest,
        )
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Match

        # ---------------------------------------------------------------------------
        # Metric definitions (RED method)
        # ---------------------------------------------------------------------------

        # Rate: total requests, partitioned by method, endpoint template, and status.
        # Use rate(http_requests_total[5m]) in PromQL for requests/second.
        REQUEST_COUNT = Counter(
            "http_requests_total",
            "Total HTTP requests",
            labelnames=["method", "endpoint", "status"],
        )

        # Duration: request latency distribution.
        # Buckets cover typical API response times from 5ms to 10s.
        # Use histogram_quantile(0.99, ...) for p99 latency.
        REQUEST_DURATION = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds",
            labelnames=["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )

        # Saturation: number of requests currently being processed.
        # High values indicate the service is overloaded.
        REQUESTS_IN_PROGRESS = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests currently being processed",
            labelnames=["method"],
        )

        # Service metadata (static, set once at startup)
        SERVICE_INFO = Info("service", "Service metadata")

        # Health check metrics (separate from business traffic)
        HEALTH_CHECK_DURATION = Histogram(
            "health_check_duration_seconds",
            "Health check response time",
            labelnames=["probe"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
        )

        HEALTH_CHECK_UP = Gauge(
            "health_check_up",
            "Health check status (1=healthy, 0=unhealthy)",
            labelnames=["probe"],
        )

        # ---------------------------------------------------------------------------
        # Paths excluded from business metrics
        # ---------------------------------------------------------------------------

        # These endpoints are NOT counted in http_requests_total.
        # They have their own dedicated metrics above.
        EXCLUDED_PATHS: frozenset[str] = frozenset({
            "/healthz", "/readyz", "/startupz", "/metrics",
        })

        # ---------------------------------------------------------------------------
        # Middleware
        # ---------------------------------------------------------------------------


        class PrometheusMiddleware(BaseHTTPMiddleware):
            \"\"\"Record RED metrics for all non-probe HTTP requests.

            Uses route templates (/users/{id}) as endpoint labels, NOT actual
            paths (/users/12345), to prevent cardinality explosion.
            \"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                path = request.url.path

                # Skip probes and metrics endpoint
                if path in EXCLUDED_PATHS:
                    return await call_next(request)

                method = request.method

                # Resolve to route template to keep label cardinality bounded
                route = self._get_route_template(request) or path

                REQUESTS_IN_PROGRESS.labels(method=method).inc()
                start = time.perf_counter()

                status = "500"
                try:
                    response = await call_next(request)
                    status = str(response.status_code)
                    return response
                except Exception:
                    status = "500"
                    raise
                finally:
                    duration = time.perf_counter() - start
                    REQUEST_COUNT.labels(
                        method=method, endpoint=route, status=status,
                    ).inc()
                    REQUEST_DURATION.labels(
                        method=method, endpoint=route,
                    ).observe(duration)
                    REQUESTS_IN_PROGRESS.labels(method=method).dec()

            @staticmethod
            def _get_route_template(request: Request) -> str | None:
                \"\"\"Extract the route template string, e.g., '/users/{id}'.

                Returns None if no matching route is found (404 paths).
                \"\"\"
                for route in getattr(request.app, "routes", []):
                    match, _ = route.matches(request.scope)
                    if match == Match.FULL:
                        return getattr(route, "path", None)
                return None


        # ---------------------------------------------------------------------------
        # Metrics endpoint
        # ---------------------------------------------------------------------------


        async def metrics_endpoint(request: Request) -> Response:
            \"\"\"Prometheus scrape endpoint. Mount at /metrics.

            Example:
                app.add_route("/metrics", metrics_endpoint)
            \"\"\"
            return Response(
                content=generate_latest(REGISTRY),
                media_type=CONTENT_TYPE_LATEST,
            )


        def set_service_info(version: str, environment: str, **extra: str) -> None:
            \"\"\"Set static service metadata. Call once at startup.\"\"\"
            info = {"version": version, "environment": environment}
            info.update(extra)
            SERVICE_INFO.info(info)
    """)


def _logging_config_py(service_name: str) -> str:
    """Template for observability/logging_config.py -- structlog + OTel integration."""

    return textwrap.dedent("""\
        \"\"\"Structured logging with OpenTelemetry trace context injection.

        Configures structlog to produce JSON logs in production with trace_id
        and span_id injected into every log line. This enables bidirectional
        navigation between traces and logs in Grafana/Datadog/Jaeger.

        Usage:
            from observability.logging_config import setup_logging
            setup_logging()  # Call once at startup

            import structlog
            logger = structlog.get_logger()
            logger.info("payment_processed", order_id="ORD-123", amount=99.99)

        Output (production JSON):
            {"event": "payment_processed", "trace_id": "4bf92f...", "span_id": "00f067...",
             "order_id": "ORD-123", "amount": 99.99, "level": "info", "timestamp": "..."}
        \"\"\"

        from __future__ import annotations

        import logging
        import os

        import structlog
        from opentelemetry import trace


        def _add_otel_context(
            logger: object, method_name: str, event_dict: dict,
        ) -> dict:
            \"\"\"structlog processor: inject OTel trace_id and span_id into every log.

            Uses W3C-standard hex formatting for trace_id (32 chars) and span_id
            (16 chars) so they match exactly what appears in Jaeger/Tempo/Datadog.

            If no active span exists (e.g., background task, startup code), the
            fields are omitted rather than logging invalid zeros.
            \"\"\"
            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                # 032x = 32-char hex (W3C standard for trace_id)
                event_dict["trace_id"] = format(ctx.trace_id, "032x")
                # 016x = 16-char hex (W3C standard for span_id)
                event_dict["span_id"] = format(ctx.span_id, "016x")
                event_dict["trace_flags"] = ctx.trace_flags
            return event_dict


        def setup_logging(
            log_level: str | None = None,
            json_output: bool | None = None,
        ) -> None:
            \"\"\"Configure structlog with OTel trace context injection.

            Args:
                log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                    Defaults to LOG_LEVEL env var or INFO.
                json_output: If True, output JSON. If False, pretty console output.
                    Defaults to True when ENVIRONMENT != 'development'.
            \"\"\"
            level_name = log_level or os.getenv("LOG_LEVEL", "INFO")
            level = getattr(logging, level_name.upper(), logging.INFO)

            if json_output is None:
                json_output = os.getenv("ENVIRONMENT", "development") != "development"

            # Choose renderer based on environment
            if json_output:
                renderer = structlog.processors.JSONRenderer()
            else:
                renderer = structlog.dev.ConsoleRenderer()

            structlog.configure(
                processors=[
                    # Merge context variables (correlation_id, etc.)
                    structlog.contextvars.merge_contextvars,
                    # Inject OpenTelemetry trace context
                    _add_otel_context,
                    # Standard processors
                    structlog.processors.add_log_level,
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.format_exc_info,
                    # Renderer (JSON in production, pretty in dev)
                    renderer,
                ],
                wrapper_class=structlog.make_filtering_bound_logger(level),
                context_class=dict,
                logger_factory=structlog.PrintLoggerFactory(),
                cache_logger_on_first_use=True,
            )
    """)


def _init_py() -> str:
    """Template for observability/__init__.py -- public API re-exports."""
    return textwrap.dedent("""\
        \"\"\"Observability module — OTel tracing, Prometheus metrics, structured logging.

        Quick start:
            from observability import setup_telemetry, setup_logging, instrument_fastapi
            from observability.metrics import PrometheusMiddleware, metrics_endpoint

            setup_telemetry()
            setup_logging()
            app = FastAPI(...)
            instrument_fastapi(app)
            app.add_middleware(PrometheusMiddleware)
            app.add_route("/metrics", metrics_endpoint)
        \"\"\"

        from .logging_config import setup_logging
        from .telemetry import instrument_fastapi, setup_telemetry

        __all__ = [
            "setup_telemetry",
            "setup_logging",
            "instrument_fastapi",
        ]
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_otel_setup(
    output_dir: str,
    service_name: str = "my-service",
    exporter: str = "otlp",
    with_prometheus: bool = True,
    with_sqlalchemy: bool = True,
    with_httpx: bool = True,
) -> dict:
    """
    Generate a production-ready observability module for a FastAPI project.

    Creates an ``observability/`` package inside *output_dir* with OTel tracing,
    Prometheus RED metrics, and structlog configuration with trace correlation.
    All generated code follows the patterns from KNOWLEDGE.md.

    Args:
        output_dir: Parent directory where the ``observability/`` package will
            be created.
        service_name: Name that identifies this service in traces and metrics.
            Can be overridden at runtime via OTEL_SERVICE_NAME env var.
        exporter: OTel trace exporter type. One of:
            - "otlp" (default): gRPC OTLP exporter — best for production.
            - "otlp-http": HTTP/protobuf OTLP exporter — when gRPC is blocked.
            - "console": Print spans to stdout — for development/debugging.
        with_prometheus: Generate Prometheus metrics middleware and /metrics
            endpoint. If False, generates a no-op placeholder.
        with_sqlalchemy: Include SQLAlchemy auto-instrumentation helper.
        with_httpx: Include HTTPX auto-instrumentation helper.

    Returns:
        Dict with:
            - ``created_files``: List of relative paths created.
            - ``observability_path``: Absolute path to the observability package.
            - ``requirements``: List of pip packages to install.

    Example::

        result = generate_otel_setup("/tmp/myproject", service_name="order-api")
        print(result["created_files"])
        # ['observability/__init__.py', 'observability/telemetry.py',
        #  'observability/metrics.py', 'observability/logging_config.py']
        print(result["requirements"])
        # ['opentelemetry-api>=1.25', 'opentelemetry-sdk>=1.25', ...]
    """
    if exporter not in ("otlp", "otlp-http", "console"):
        raise ValueError(
            f"Invalid exporter: {exporter!r}. "
            f"Must be 'otlp', 'otlp-http', or 'console'."
        )

    obs_dir = Path(output_dir) / "observability"
    obs_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "telemetry.py": _telemetry_py(service_name, exporter, with_sqlalchemy, with_httpx),
        "metrics.py": _metrics_py(with_prometheus),
        "logging_config.py": _logging_config_py(service_name),
    }

    created: list[str] = []
    for filename, content in files.items():
        filepath = obs_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"observability/{filename}")

    # Build requirements list
    requirements: list[str] = [
        "opentelemetry-api>=1.25",
        "opentelemetry-sdk>=1.25",
        "opentelemetry-instrumentation-fastapi>=0.46b0",
        "structlog>=24.1",
    ]

    if exporter == "otlp":
        requirements.append("opentelemetry-exporter-otlp-proto-grpc>=1.25")
    elif exporter == "otlp-http":
        requirements.append("opentelemetry-exporter-otlp-proto-http>=1.25")

    if with_prometheus:
        requirements.append("prometheus-client>=0.20")

    if with_sqlalchemy:
        requirements.append("opentelemetry-instrumentation-sqlalchemy>=0.46b0")

    if with_httpx:
        requirements.append("opentelemetry-instrumentation-httpx>=0.46b0")

    return {
        "created_files": created,
        "observability_path": str(obs_dir),
        "requirements": requirements,
        "exporter": exporter,
        "with_prometheus": with_prometheus,
        "with_sqlalchemy": with_sqlalchemy,
        "with_httpx": with_httpx,
    }
