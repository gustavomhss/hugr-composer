"""Generator for a production-grade OpenTelemetry observability package.

Creates an ``observability/`` package with four files:

    observability/__init__.py        — Public API re-exports
    observability/telemetry.py       — TracerProvider + auto-instrumentation
    observability/trace_middleware.py — Cardinality-safe trace context middleware
    observability/structlog_processor.py — structlog + OTel trace_id injection

Architecture decisions
----------------------
**Cardinality safety** is the single most important concern for Prometheus
label design.  Using the raw request path (``/users/42``) as a metric label
creates one time-series per user ID — an unbounded cardinality explosion that
will OOM your Prometheus server.  The solution is ``route.matches(request.scope)``
from Starlette's routing API: it walks the registered route table and returns
the *template* string (``/users/{id}``), giving a small, fixed set of label
values regardless of how many distinct entity IDs exist in production.

**Three exporter variants** cover all deployment scenarios:
* ``otlp_grpc``  — gRPC OTLP (default, best throughput, requires port 4317)
* ``otlp_http``  — HTTP/proto OTLP (firewall-friendly, port 4318)
* ``console``    — stdout (development / CI debugging)

**W3C trace_id formatting** uses ``format(ctx.trace_id, "032x")`` to produce
the 32-character hex string required by the W3C Trace Context spec.  This
ensures trace IDs in logs match exactly what Jaeger/Tempo/Datadog display,
enabling bidirectional log-trace correlation.

**structlog integration** injects ``trace_id`` and ``span_id`` into every log
event via a processor, so production JSON logs carry trace context without
manual threading.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_observability_generate_otel',
    'description': 'Generate OpenTelemetry setup: TracerProvider, BatchSpanProcessor, auto-instrumentation.',
    'tags': ['generator', 'observability'],
    'entry': 'generate_otel_setup',
}

import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Exporter constants
# ---------------------------------------------------------------------------

#: gRPC OTLP exporter — highest throughput, default for Kubernetes deployments.
EXPORTER_OTLP_GRPC = "otlp_grpc"

#: HTTP/protobuf OTLP exporter — works through firewalls that block gRPC.
EXPORTER_OTLP_HTTP = "otlp_http"

#: Console exporter — prints spans to stdout; use in development and CI.
EXPORTER_CONSOLE = "console"

#: All supported exporter names.
SUPPORTED_EXPORTERS: frozenset[str] = frozenset(
    {EXPORTER_OTLP_GRPC, EXPORTER_OTLP_HTTP, EXPORTER_CONSOLE}
)


# ---------------------------------------------------------------------------
# Template builders (one function per generated file)
# ---------------------------------------------------------------------------


def _build_telemetry_py(service_name: str, exporter: str) -> str:
    """Return the content for ``observability/telemetry.py``.

    Args:
        service_name: Default service name baked into the generated file.
        exporter: One of the EXPORTER_* constants.

    Returns:
        Complete Python source as a string.
    """
    exporter_import, exporter_create = _exporter_fragments(exporter)

    template = textwrap.dedent("""\
        \"\"\"OpenTelemetry setup — TracerProvider, BatchSpanProcessor, auto-instrumentation.

        Call ``setup_telemetry()`` ONCE at application startup, BEFORE creating the
        FastAPI app or calling any auto-instrumentors.  The recommended place is
        inside the lifespan context manager, before the ``yield`` statement.

        Environment variable overrides (standard OTel convention):
            OTEL_SERVICE_NAME             — service name for the resource attribute
            OTEL_EXPORTER_OTLP_ENDPOINT   — OTLP collector endpoint
            OTEL_TRACES_SAMPLER_ARG       — sampling rate (0.0 – 1.0, default 1.0)
            SERVICE_VERSION               — service.version resource attribute
            ENVIRONMENT                   — deployment.environment resource attribute
        \"\"\"

        from __future__ import annotations

        import os

        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
        __EXPORTER_IMPORT__

        # Module-level tracer — usable after setup_telemetry() is called.
        tracer = trace.get_tracer(__name__)

        _TELEMETRY_INITIALIZED = False


        def setup_telemetry(
            service_name: str = "__SERVICE_NAME__",
            otlp_endpoint: str | None = None,
            otlp_insecure: bool = True,
            sample_rate: float = 1.0,
        ) -> None:
            \"\"\"Initialize OpenTelemetry with BatchSpanProcessor.

            Safe to call multiple times — subsequent calls are silent no-ops.

            Args:
                service_name: Identifies this service in traces.
                    Override via OTEL_SERVICE_NAME env var.
                otlp_endpoint: Collector endpoint.
                    Override via OTEL_EXPORTER_OTLP_ENDPOINT env var.
                otlp_insecure: Use insecure (non-TLS) connection.  Set False in
                    production when the collector has TLS enabled.
                sample_rate: Fraction of traces to sample (0.0 – 1.0).
                    Override via OTEL_TRACES_SAMPLER_ARG env var.
            \"\"\"
            global _TELEMETRY_INITIALIZED
            if _TELEMETRY_INITIALIZED:
                return
            _TELEMETRY_INITIALIZED = True

            service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
            otlp_endpoint = otlp_endpoint or os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
            )
            sample_rate_str = os.getenv("OTEL_TRACES_SAMPLER_ARG")
            if sample_rate_str is not None:
                sample_rate = float(sample_rate_str)

            resource = Resource.create({
                SERVICE_NAME: service_name,
                "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
                "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            })

            # ParentBased: respect upstream sampling decisions; if parent was
            # sampled the child is always sampled regardless of local rate.
            sampler = ParentBasedTraceIdRatio(sample_rate)
            provider = TracerProvider(resource=resource, sampler=sampler)

        __EXPORTER_CREATE__
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)


        def instrument_fastapi(
            app,
            excluded_urls: str | None = None,
        ) -> None:
            \"\"\"Auto-instrument a FastAPI app for HTTP request tracing.

            Creates a span per request including method, route template, and
            status code.  Propagates W3C ``traceparent`` headers automatically.

            Args:
                app: The FastAPI application instance.
                excluded_urls: Comma-separated URL paths to exclude from tracing
                    (health probes and /metrics are excluded by default).
            \"\"\"
            excluded = excluded_urls or "healthz,readyz,startupz,metrics"
            FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)


        def instrument_sqlalchemy(engine) -> None:
            \"\"\"Instrument a SQLAlchemy engine for distributed tracing.

            Appends a ``traceparent`` SQL comment to every query
            (``enable_commenter=True``) enabling DB-side correlation with
            slow-query logs.  Call after ``setup_telemetry()`` and after
            creating the engine.

            Args:
                engine: A SQLAlchemy ``Engine`` or ``AsyncEngine`` instance.
            \"\"\"
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=True)


        def instrument_httpx() -> None:
            \"\"\"Instrument all httpx clients for outbound HTTP tracing.

            Automatically creates child spans for every ``httpx.AsyncClient``
            and ``httpx.Client`` request and propagates W3C ``traceparent``
            headers to downstream services.  Call after ``setup_telemetry()``.
            \"\"\"
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
    """)

    return (
        template
        .replace("__EXPORTER_IMPORT__", exporter_import)
        .replace("__EXPORTER_CREATE__\n", exporter_create)
        .replace("__SERVICE_NAME__", service_name)
    )


def _build_trace_middleware_py() -> str:
    """Return the content for ``observability/trace_middleware.py``.

    The middleware solves the cardinality problem by resolving every request
    path to its route *template* before recording it as a Prometheus label.

    Returns:
        Complete Python source as a string.
    """
    return textwrap.dedent("""\
        \"\"\"Cardinality-safe trace context middleware for Starlette/FastAPI.

        The cardinality problem
        -----------------------
        Naive Prometheus middleware uses ``request.url.path`` as a label value.
        For a route like ``GET /users/{id}``, this produces one time-series per
        user ID — millions of series in production, enough to OOM Prometheus.

        The solution: ``route.matches(request.scope)``
        -----------------------------------------------
        Starlette's routing API exposes a ``matches(scope)`` method on every
        registered Route object.  When it returns ``Match.FULL``, the route's
        ``path`` attribute holds the *template* string (``/users/{id}``), not
        the instantiated value.  Walking all routes and stopping at the first
        full match gives a label with bounded cardinality — at most one value
        per registered endpoint.

        Usage::

            from observability.trace_middleware import TraceContextMiddleware
            app.add_middleware(TraceContextMiddleware)
        \"\"\"

        from __future__ import annotations

        import time

        from opentelemetry import trace
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Match

        # Paths excluded from span annotation (health probes + metrics scrape).
        _EXCLUDED_PATHS: frozenset[str] = frozenset(
            {"/healthz", "/readyz", "/startupz", "/metrics"}
        )


        def _get_route_template(request: Request) -> str | None:
            \"\"\"Resolve the request to its registered route template string.

            Walks ``request.app.routes`` and calls ``route.matches(request.scope)``
            on each entry.  Returns the *template* path (e.g. ``/users/{id}``)
            when a full match is found, or ``None`` for unmatched paths (404s).

            This is the canonical cardinality-safe approach: label values are
            always template strings, never raw user-supplied path segments.

            Args:
                request: The current Starlette request.

            Returns:
                Route template string, or None if no route matched.
            \"\"\"
            for route in getattr(request.app, "routes", []):
                match, _ = route.matches(request.scope)
                if match == Match.FULL:
                    return getattr(route, "path", None)
            return None


        class TraceContextMiddleware(BaseHTTPMiddleware):
            \"\"\"Annotate the active OTel span with HTTP semantic conventions.

            Adds ``http.method``, ``http.route`` (template, not raw path),
            ``http.status_code``, and ``http.request_duration_ms`` to every
            non-probe request span.

            Health probes and ``/metrics`` are skipped to avoid polluting traces
            with synthetic traffic from orchestrators and Prometheus scrapers.
            \"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                \"\"\"Process the request and annotate the active OTel span.

                Args:
                    request: The incoming HTTP request.
                    call_next: The next middleware or route handler.

                Returns:
                    The HTTP response.
                \"\"\"
                if request.url.path in _EXCLUDED_PATHS:
                    return await call_next(request)

                span = trace.get_current_span()
                route_template = _get_route_template(request) or request.url.path

                span.set_attribute("http.method", request.method)
                span.set_attribute("http.route", route_template)

                start = time.perf_counter()
                status_code = 500
                try:
                    response = await call_next(request)
                    status_code = response.status_code
                    return response
                except Exception:
                    span.record_exception(Exception)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    span.set_attribute("http.status_code", status_code)
                    span.set_attribute("http.request_duration_ms", round(duration_ms, 2))
    """)


def _build_structlog_processor_py(service_name: str) -> str:
    """Return the content for ``observability/structlog_processor.py``.

    Args:
        service_name: Default service name baked into the generated file.

    Returns:
        Complete Python source as a string.
    """
    return textwrap.dedent(f"""\
        \"\"\"structlog configuration with OpenTelemetry trace context injection.

        Configures structlog to produce JSON logs in production with ``trace_id``
        and ``span_id`` injected into every log line.  This enables bidirectional
        navigation between traces and logs in Grafana / Datadog / Jaeger.

        W3C trace_id format
        -------------------
        ``format(ctx.trace_id, "032x")`` produces a 32-character lowercase hex
        string — the W3C Trace Context standard format.  This must match what
        Jaeger / Tempo / Datadog display; otherwise the log–trace correlation
        link will silently break.  ``016x`` is the analogous format for span_id.

        Usage::

            from observability.structlog_processor import setup_logging
            setup_logging()  # Call once at startup, before the first log call.

            import structlog
            logger = structlog.get_logger()
            logger.info("order_placed", order_id="ORD-123", total=49.99)

        Output (production JSON)::

            {{"event": "order_placed", "trace_id": "4bf92f3577b34da6...",
             "span_id": "00f067aa0ba902b7", "order_id": "ORD-123",
             "total": 49.99, "level": "info", "timestamp": "2026-01-01T00:00:00Z"}}
        \"\"\"

        from __future__ import annotations

        import logging
        import os

        import structlog
        from opentelemetry import trace


        # ---------------------------------------------------------------------------
        # OTel structlog processor
        # ---------------------------------------------------------------------------


        def _inject_otel_context(
            logger: object,
            method_name: str,
            event_dict: dict,
        ) -> dict:
            \"\"\"structlog processor: inject W3C-formatted trace_id and span_id.

            Reads the active OpenTelemetry span context and injects ``trace_id``
            (32-char hex, W3C format) and ``span_id`` (16-char hex) into every
            log event dictionary.

            Fields are omitted — not zeroed — when no active span exists (e.g.
            background tasks, startup code) to avoid logging invalid zero IDs.

            Args:
                logger: The bound logger (unused, required by structlog protocol).
                method_name: The logging method name (unused).
                event_dict: The mutable event dictionary to enrich.

            Returns:
                The enriched event dictionary.
            \"\"\"
            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                # 032x = 32-char hex (W3C Trace Context standard for trace_id)
                event_dict["trace_id"] = format(ctx.trace_id, "032x")
                # 016x = 16-char hex (W3C Trace Context standard for span_id)
                event_dict["span_id"] = format(ctx.span_id, "016x")
                event_dict["trace_flags"] = ctx.trace_flags
            return event_dict


        # ---------------------------------------------------------------------------
        # Public setup function
        # ---------------------------------------------------------------------------


        def setup_logging(
            log_level: str | None = None,
            json_output: bool | None = None,
        ) -> None:
            \"\"\"Configure structlog with OTel trace context injection.

            Call once at application startup before any log statements.  Safe
            to call multiple times (structlog.configure is idempotent).

            Args:
                log_level: Minimum logging level (DEBUG, INFO, WARNING, ERROR).
                    Defaults to LOG_LEVEL env var, then INFO.
                json_output: True for JSON (production), False for pretty console.
                    Defaults to True when ENVIRONMENT != 'development'.
            \"\"\"
            level_name = log_level or os.getenv("LOG_LEVEL", "INFO")
            level = getattr(logging, level_name.upper(), logging.INFO)

            if json_output is None:
                json_output = os.getenv("ENVIRONMENT", "development") != "development"

            renderer = (
                structlog.processors.JSONRenderer()
                if json_output
                else structlog.dev.ConsoleRenderer()
            )

            structlog.configure(
                processors=[
                    # Merge context variables (e.g. correlation_id from middleware)
                    structlog.contextvars.merge_contextvars,
                    # Inject OTel trace_id / span_id using W3C hex format
                    _inject_otel_context,
                    # Standard structlog processors
                    structlog.processors.add_log_level,
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.format_exc_info,
                    # Renderer: JSON in production, pretty-print in development
                    renderer,
                ],
                wrapper_class=structlog.make_filtering_bound_logger(level),
                context_class=dict,
                logger_factory=structlog.PrintLoggerFactory(),
                cache_logger_on_first_use=True,
            )
    """)


def _build_init_py() -> str:
    """Return the content for ``observability/__init__.py``.

    Returns:
        Complete Python source as a string.
    """
    return textwrap.dedent("""\
        \"\"\"Observability package — OTel tracing, trace middleware, structured logging.

        Quick start::

            from observability import setup_telemetry, setup_logging, instrument_fastapi
            from observability.trace_middleware import TraceContextMiddleware

            setup_telemetry()
            setup_logging()
            app = FastAPI(...)
            instrument_fastapi(app)
            app.add_middleware(TraceContextMiddleware)
        \"\"\"

        from .structlog_processor import setup_logging
        from .telemetry import instrument_fastapi, instrument_httpx, instrument_sqlalchemy, setup_telemetry

        __all__ = [
            "setup_telemetry",
            "setup_logging",
            "instrument_fastapi",
            "instrument_sqlalchemy",
            "instrument_httpx",
        ]
    """)


# ---------------------------------------------------------------------------
# Exporter fragment helpers
# ---------------------------------------------------------------------------


def _exporter_fragments(exporter: str) -> tuple[str, str]:
    """Return (import_snippet, create_snippet) for the requested exporter.

    Each snippet is indented to fit inside the generated ``telemetry.py``
    at the module level and inside ``setup_telemetry()`` respectively.

    Args:
        exporter: One of EXPORTER_OTLP_GRPC, EXPORTER_OTLP_HTTP, or
            EXPORTER_CONSOLE.

    Returns:
        Tuple of (import_fragment, create_fragment) strings.

    Raises:
        ValueError: If *exporter* is not one of the supported values.
    """
    if exporter == EXPORTER_OTLP_GRPC:
        imp = (
            "from opentelemetry.exporter.otlp.proto.grpc.trace_exporter "
            "import OTLPSpanExporter"
        )
        create = (
            "    exporter = OTLPSpanExporter(\n"
            "        endpoint=otlp_endpoint,\n"
            "        insecure=otlp_insecure,\n"
            "    )\n"
        )
        return imp, create

    if exporter == EXPORTER_OTLP_HTTP:
        imp = (
            "from opentelemetry.exporter.otlp.proto.http.trace_exporter "
            "import OTLPSpanExporter"
        )
        create = "    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)\n"
        return imp, create

    if exporter == EXPORTER_CONSOLE:
        imp = "from opentelemetry.sdk.trace.export import ConsoleSpanExporter"
        create = "    exporter = ConsoleSpanExporter()\n"
        return imp, create

    raise ValueError(
        f"Unsupported exporter {exporter!r}. "
        f"Choose one of: {sorted(SUPPORTED_EXPORTERS)}"
    )


# ---------------------------------------------------------------------------
# Requirements helper
# ---------------------------------------------------------------------------


def _build_requirements(exporter: str, with_structlog: bool) -> list[str]:
    """Return the pip package list required by the generated observability code.

    Args:
        exporter: The exporter variant (affects which OTel package is needed).
        with_structlog: Whether structlog integration is included.

    Returns:
        Sorted list of pip requirement strings.
    """
    reqs = [
        "opentelemetry-api>=1.25",
        "opentelemetry-sdk>=1.25",
        "opentelemetry-instrumentation-fastapi>=0.46b0",
        "opentelemetry-instrumentation-sqlalchemy>=0.46b0",
        "opentelemetry-instrumentation-httpx>=0.46b0",
    ]

    if exporter == EXPORTER_OTLP_GRPC:
        reqs.append("opentelemetry-exporter-otlp-proto-grpc>=1.25")
    elif exporter == EXPORTER_OTLP_HTTP:
        reqs.append("opentelemetry-exporter-otlp-proto-http>=1.25")

    if with_structlog:
        reqs.append("structlog>=24.1")

    return sorted(reqs)


# ---------------------------------------------------------------------------
# Public generator entry point
# ---------------------------------------------------------------------------


def generate_otel_setup(
    output_dir: str,
    service_name: str = "app",
    exporter: str = EXPORTER_OTLP_GRPC,
    with_structlog: bool = True,
) -> dict:
    """Generate a production-grade ``observability/`` package for a FastAPI project.

    Creates four files inside ``{output_dir}/observability/``:

    * ``__init__.py``              — public API re-exports
    * ``telemetry.py``             — TracerProvider + auto-instrumentation helpers
    * ``trace_middleware.py``      — cardinality-safe OTel span annotation middleware
    * ``structlog_processor.py``   — structlog setup with W3C trace_id injection

    **Cardinality safety** is achieved via ``route.matches(request.scope)``
    in ``trace_middleware.py``, which resolves every request to its route
    *template* (``/users/{id}``) instead of the raw path (``/users/42``).

    **W3C trace_id formatting** uses ``format(ctx.trace_id, "032x")`` to produce
    the 32-character hex string required by the W3C Trace Context spec, ensuring
    log–trace correlation works in Jaeger, Grafana Tempo, and Datadog.

    Args:
        output_dir: Parent directory where ``observability/`` will be created.
        service_name: Service identifier baked into the generated ``telemetry.py``
            as the default for the OTel ``service.name`` resource attribute.
            Can be overridden at runtime via the ``OTEL_SERVICE_NAME`` env var.
        exporter: OTel trace exporter variant.  One of:

            * ``"otlp_grpc"`` (default) — gRPC OTLP, best throughput, port 4317.
            * ``"otlp_http"`` — HTTP/proto OTLP, firewall-friendly, port 4318.
            * ``"console"``   — stdout, for development and CI debugging.

        with_structlog: When True (default), generates ``structlog_processor.py``
            with W3C trace_id/span_id injection and wires it into ``__init__.py``.

    Returns:
        Dict with:

        * ``files_created`` — list of relative paths created under *output_dir*.
        * ``observability_path`` — absolute path to the ``observability/`` package.
        * ``requirements`` — pip packages the generated code depends on.
        * ``exporter`` — the exporter variant used.
        * ``with_structlog`` — whether structlog integration was generated.

    Raises:
        ValueError: If *exporter* is not one of the three supported values.

    Example::

        result = generate_otel_setup("/tmp/myproject", service_name="order-api")
        print(result["files_created"])
        # ['observability/__init__.py', 'observability/telemetry.py',
        #  'observability/trace_middleware.py',
        #  'observability/structlog_processor.py']
    """
    if exporter not in SUPPORTED_EXPORTERS:
        raise ValueError(
            f"Unsupported exporter {exporter!r}. "
            f"Choose one of: {sorted(SUPPORTED_EXPORTERS)}"
        )

    obs_dir = Path(output_dir) / "observability"
    obs_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _build_init_py(),
        "telemetry.py": _build_telemetry_py(service_name, exporter),
        "trace_middleware.py": _build_trace_middleware_py(),
    }

    if with_structlog:
        files["structlog_processor.py"] = _build_structlog_processor_py(service_name)

    created: list[str] = []
    for filename, content in files.items():
        filepath = obs_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"observability/{filename}")

    return {
        "files_created": created,
        "observability_path": str(obs_dir),
        "requirements": _build_requirements(exporter, with_structlog),
        "exporter": exporter,
        "with_structlog": with_structlog,
    }
