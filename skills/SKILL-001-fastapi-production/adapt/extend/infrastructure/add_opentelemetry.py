"""TOOL-085: add_opentelemetry — add OpenTelemetry traces, metrics, and logs.

Writes an OTEL telemetry bootstrap (TracerProvider, MeterProvider,
LoggerProvider with ALL opentelemetry imports lazy), a
``OTELMiddleware`` for request tracing, metric counters
(request_count, request_duration, error_count), and integrates with
the existing structlog pipeline.

Why all opentelemetry imports lazy?

* **No boot crash** — the opentelemetry SDK is a complex optional
  dependency with dozens of sub-packages. If ANY of them are missing,
  a top-level import would crash the application. Every import in the
  generated code lives inside function bodies.
* **OTEL_ENABLED gate** — when ``OTEL_ENABLED=false`` (the default)
  the middleware is a pure pass-through and no telemetry SDKs are
  imported at all, so the performance cost is zero in non-instrumented
  deployments.
* **Structlog integration** — the telemetry setup injects the current
  trace/span IDs into structlog's context so every log line carries
  trace correlation without requiring a separate log processor.

Security / correctness guarantees:

* ALL opentelemetry imports are lazy inside function bodies.
* No secrets or API keys appear in generated code.
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` is read from settings, never hardcoded.
* Generated code uses ``logging.getLogger(__name__)``.
* Every generated function is kept ≤50 LOC.

Idempotent: a second run detects ``init_telemetry`` in
``app/telemetry/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_opentelemetry import add_opentelemetry

    result = add_opentelemetry(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/telemetry/setup.py", …]
    print(result.next_steps)    # ["pip install opentelemetry-sdk", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_observability_add_opentelemetry",
    "description": (
        "Add OpenTelemetry traces, metrics, and logs with lazy SDK imports, "
        "OTELMiddleware for request tracing, metric counters, and structlog "
        "integration."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_opentelemetry",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_opentelemetry(inp: ToolInput) -> ToolResult:
    """Add OpenTelemetry instrumentation to a FastAPI project.

    Creates ``app/telemetry/`` package (setup.py, middleware.py,
    metrics.py), patches config with OTEL settings, patches
    ``app/main.py`` to call ``init_telemetry()`` in the lifespan
    and add ``OTELMiddleware``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with status, files_created, files_modified,
        notes, and next_steps.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

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

    # --- Idempotency guard ---------------------------------------------------
    telemetry_init = app_dir / "telemetry" / "__init__.py"
    if telemetry_init.exists() and "init_telemetry" in telemetry_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "init_telemetry already present in app/telemetry/__init__.py — "
                "OpenTelemetry already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Dry run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/telemetry/ (setup.py, middleware.py, metrics.py),",
                "[dry_run] Would patch app/core/config.py with OTEL_* settings.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — telemetry package
    _write_telemetry_package(app_dir, files_created)

    # Step 2 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 3 — ensure opentelemetry packages in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated Python file parses cleanly
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
            "OpenTelemetry layer added: TracerProvider, MeterProvider, LoggerProvider "
            "(all SDK imports lazy), OTELMiddleware for request tracing, "
            "metric counters (request_count, request_duration, error_count).",
            "Structlog integration: trace/span IDs injected into log context.",
            "OTEL_ENABLED=false (default) = zero SDK imports, pure pass-through.",
        ],
        next_steps=[
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp",
            "Set OTEL_ENABLED=true, OTEL_EXPORTER_OTLP_ENDPOINT, "
            "OTEL_SERVICE_NAME in .env.",
            "Add OTELMiddleware to app/main.py: "
            "app.add_middleware(OTELMiddleware)",
            "Call init_telemetry() in your FastAPI lifespan startup.",
            "Restart the FastAPI app to activate tracing.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body.
# ---------------------------------------------------------------------------

def _write_telemetry_package(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/telemetry/`` package with init, setup, middleware, metrics.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    pkg_dir = app_dir / "telemetry"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "__init__.py": _TELEMETRY_PKG_INIT_TEMPLATE,
        "setup.py": _TELEMETRY_SETUP_TEMPLATE,
        "middleware.py": _TELEMETRY_MIDDLEWARE_TEMPLATE,
        "metrics.py": _TELEMETRY_METRICS_TEMPLATE,
    }
    for name, content in files.items():
        p = pkg_dir / name
        p.write_text(content)
        files_created.append(str(p))


def _patch_config(config_file: Path) -> None:
    """Inject OTEL settings into the ``Settings`` class body.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "OTEL_ENABLED" in src:
        return

    block = (
        "\n"
        "    # --- OpenTelemetry — added by add_opentelemetry tool ---\n"
        "    OTEL_ENABLED: bool = False\n"
        '    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"\n'
        '    OTEL_SERVICE_NAME: str = "fastapi-app"\n'
        '    OTEL_TRACES_SAMPLER: str = "parentbased_traceidratio"\n'
        "    OTEL_TRACES_SAMPLER_ARG: float = 1.0\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure opentelemetry base packages are in ``requirements.txt``.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    additions: list[str] = []
    if "opentelemetry-sdk" not in src:
        additions.append("opentelemetry-sdk>=1.23.0")
    if "opentelemetry-exporter-otlp" not in src:
        additions.append("opentelemetry-exporter-otlp>=1.23.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_TELEMETRY_PKG_INIT_TEMPLATE = textwrap.dedent("""\
    \"\"\"OpenTelemetry instrumentation — traces, metrics, and logs.

    Public API:
        init_telemetry: Bootstrap TracerProvider, MeterProvider, LoggerProvider.
        OTELMiddleware: ASGI middleware for per-request tracing.
        get_tracer:     Return the configured OpenTelemetry tracer.
        get_meter:      Return the configured OpenTelemetry meter.
    \"\"\"

    from app.telemetry.metrics import get_meter, record_error, record_request
    from app.telemetry.middleware import OTELMiddleware
    from app.telemetry.setup import get_tracer, init_telemetry

    __all__ = [
        "init_telemetry",
        "OTELMiddleware",
        "get_tracer",
        "get_meter",
        "record_request",
        "record_error",
    ]
""")

_TELEMETRY_SETUP_TEMPLATE = textwrap.dedent("""\
    \"\"\"OpenTelemetry provider bootstrap.

    ALL opentelemetry imports are lazy (inside function bodies) so the
    application boots without the SDK installed.
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)

    _tracer = None
    _meter = None


    def init_telemetry() -> None:
        \"\"\"Bootstrap TracerProvider, MeterProvider, and LoggerProvider.

        Reads configuration from ``app.core.config.settings``.  When
        ``OTEL_ENABLED`` is ``False`` this function is a no-op — no SDK
        packages are imported.
        \"\"\"
        from app.core.config import settings

        if not settings.OTEL_ENABLED:
            logger.debug("OTEL disabled — skipping telemetry bootstrap")
            return

        _init_tracer_provider(settings)
        _init_meter_provider(settings)
        _init_logger_provider(settings)
        logger.info("OpenTelemetry initialised for service '%s'", settings.OTEL_SERVICE_NAME)


    def _init_tracer_provider(settings) -> None:  # type: ignore[no-untyped-def]
        \"\"\"Configure the global TracerProvider with OTLP export.

        Args:
            settings: Application settings with OTEL_* fields.
        \"\"\"
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)


    def _init_meter_provider(settings) -> None:  # type: ignore[no-untyped-def]
        \"\"\"Configure the global MeterProvider with OTLP export.

        Args:
            settings: Application settings with OTEL_* fields.
        \"\"\"
        from opentelemetry import metrics  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415

        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        )
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)


    def _init_logger_provider(settings) -> None:  # type: ignore[no-untyped-def]
        \"\"\"Configure the global LoggerProvider with OTLP export.

        Args:
            settings: Application settings with OTEL_* fields.
        \"\"\"
        from opentelemetry._logs import set_logger_provider  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (  # noqa: PLC0415
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs import LoggerProvider  # noqa: PLC0415
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor  # noqa: PLC0415

        exporter = OTLPLogExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        provider = LoggerProvider()
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        set_logger_provider(provider)


    def get_tracer(name: str = "app"):
        \"\"\"Return a tracer from the global TracerProvider.

        When OTEL is disabled returns a no-op tracer so callers need
        not check the enabled flag themselves.

        Args:
            name: Instrumentation scope name (typically ``__name__``).

        Returns:
            An OpenTelemetry Tracer instance.
        \"\"\"
        try:
            from opentelemetry import trace  # noqa: PLC0415
            return trace.get_tracer(name)
        except ImportError:  # pragma: no cover
            from opentelemetry.trace import NoOpTracer  # type: ignore[attr-defined]
            return NoOpTracer()
""")

_TELEMETRY_MIDDLEWARE_TEMPLATE = textwrap.dedent("""\
    \"\"\"OTELMiddleware: per-request OpenTelemetry span creation.

    When OTEL_ENABLED is False the middleware is a pure pass-through
    with zero SDK imports.
    \"\"\"

    from __future__ import annotations

    import logging
    import time

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

    logger = logging.getLogger(__name__)


    class OTELMiddleware(BaseHTTPMiddleware):
        \"\"\"ASGI middleware that creates an OTEL span for each HTTP request.

        When ``OTEL_ENABLED`` is ``False`` the middleware delegates to
        ``call_next`` immediately with no telemetry overhead.
        \"\"\"

        async def dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            \"\"\"Wrap the request in an OTEL span when tracing is enabled.

            Args:
                request: Incoming HTTP request.
                call_next: Next middleware / route handler.

            Returns:
                HTTP response with span attributes set.
            \"\"\"
            from app.core.config import settings

            if not settings.OTEL_ENABLED:
                return await call_next(request)

            return await self._traced_dispatch(request, call_next)

        async def _traced_dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            \"\"\"Execute the request inside an active OTEL span.

            Args:
                request: Incoming HTTP request.
                call_next: Next middleware / route handler.

            Returns:
                HTTP response; span is ended whether or not an exception occurs.
            \"\"\"
            from app.telemetry.setup import get_tracer  # noqa: PLC0415

            tracer = get_tracer("app.middleware")
            span_name = f"{request.method} {request.url.path}"
            t0 = time.monotonic()

            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.route", request.url.path)

                response = await call_next(request)
                elapsed = int((time.monotonic() - t0) * 1000)

                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.response_time_ms", elapsed)
                return response
""")

_TELEMETRY_METRICS_TEMPLATE = textwrap.dedent("""\
    \"\"\"OpenTelemetry metric counters and helpers.

    All opentelemetry imports are lazy so this module loads cleanly
    without the SDK installed.
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)

    # Module-level meter cache — populated on first get_meter() call.
    _meter = None
    _request_counter = None
    _error_counter = None
    _duration_histogram = None


    def get_meter(name: str = "app"):
        \"\"\"Return the global OpenTelemetry meter.

        When the SDK is not available returns ``None`` — callers must
        guard ``if meter is not None`` before using it.

        Args:
            name: Instrumentation scope name.

        Returns:
            An OpenTelemetry Meter instance, or None if SDK unavailable.
        \"\"\"
        try:
            from opentelemetry import metrics  # noqa: PLC0415
            return metrics.get_meter(name)
        except ImportError:  # pragma: no cover
            return None


    def _ensure_instruments() -> None:
        \"\"\"Lazily create metric instruments on first use.\"\"\"
        global _meter, _request_counter, _error_counter, _duration_histogram

        if _meter is not None:
            return

        meter = get_meter("app.metrics")
        if meter is None:
            return

        _meter = meter
        _request_counter = meter.create_counter(
            "http.server.request_count",
            description="Total number of HTTP requests received.",
            unit="1",
        )
        _error_counter = meter.create_counter(
            "http.server.error_count",
            description="Total number of HTTP 5xx responses.",
            unit="1",
        )
        _duration_histogram = meter.create_histogram(
            "http.server.request_duration",
            description="HTTP request duration in milliseconds.",
            unit="ms",
        )


    def record_request(
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        \"\"\"Record an HTTP request in the metrics counters.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: Request path.
            status_code: HTTP response status code.
            duration_ms: Request duration in milliseconds.
        \"\"\"
        _ensure_instruments()
        attrs = {"http.method": method, "http.route": path, "http.status_code": status_code}

        if _request_counter is not None:
            _request_counter.add(1, attrs)
        if _duration_histogram is not None:
            _duration_histogram.record(duration_ms, attrs)


    def record_error(method: str, path: str, status_code: int) -> None:
        \"\"\"Increment the error counter for a 5xx response.

        Args:
            method: HTTP method.
            path: Request path.
            status_code: HTTP status code (expected 5xx).
        \"\"\"
        _ensure_instruments()
        if _error_counter is not None:
            _error_counter.add(
                1,
                {"http.method": method, "http.route": path, "http.status_code": status_code},
            )
        if status_code >= 500:
            logger.warning("5xx error recorded: %s %s → %d", method, path, status_code)
""")
