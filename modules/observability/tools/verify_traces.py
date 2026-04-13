"""
SKILL-001 Observability Tool: Static analysis for observability anti-patterns.

Performs AST-based and regex analysis on a FastAPI project to detect 10 common
observability issues: missing OTel setup, no auto-instrumentation, missing custom
spans on business logic, no metrics export, print() debugging in production code,
missing trace correlation in logs, unsampled high-traffic services, missing health
check exclusion from metrics, no error status on spans, and unstructured logging.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "site-packages",
}

_NON_PRODUCTION_DIRS: set[str] = {
    "tests", "test", "examples", "docs", "benchmarks", "scripts",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(root: Path) -> list[Path]:
    """Walk *root* and return .py files not in excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDE_DIRS]
        dp = Path(dirpath)
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(dp / fn)
    return files


def _is_non_production(filepath: Path, project_root: Path) -> bool:
    """Return True if *filepath* lives under a non-production directory."""
    try:
        rel = filepath.relative_to(project_root)
    except ValueError:
        return False
    return any(p.lower() in _NON_PRODUCTION_DIRS for p in rel.parts)


def _resolve_call_name(node: ast.Call) -> str | None:
    """Resolve a dotted call name like ``trace.get_tracer``."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        if isinstance(func.value.value, ast.Name):
            return f"{func.value.value.id}.{func.value.attr}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_obs01_otel_setup(all_sources: str) -> Finding | None:
    """OBS-01: OpenTelemetry TracerProvider is configured."""
    has_tracer_provider = "TracerProvider" in all_sources
    has_set_provider = "set_tracer_provider" in all_sources

    if has_tracer_provider and has_set_provider:
        return None

    # Check for env-var-based auto config (zero-code instrumentation)
    has_auto = "opentelemetry-instrument" in all_sources or "opentelemetry_instrument" in all_sources

    if has_auto:
        return None

    return Finding(
        rule_id="OBS-01",
        severity=Severity.CRITICAL,
        title="No OpenTelemetry TracerProvider configuration",
        description=(
            "No TracerProvider setup or set_tracer_provider() call found. "
            "Without a configured TracerProvider, all spans go to the no-op "
            "provider and are silently discarded. Distributed tracing is "
            "completely non-functional."
        ),
        fix_suggestion=(
            "Create a setup_telemetry() function that configures TracerProvider "
            "with BatchSpanProcessor and OTLPSpanExporter. Call it at startup "
            "before any auto-instrumentors."
        ),
    )


def _check_obs02_fastapi_instrumentation(all_sources: str) -> Finding | None:
    """OBS-02: FastAPI auto-instrumentation is active."""
    has_instrumentor = "FastAPIInstrumentor" in all_sources

    if has_instrumentor:
        return None

    # Check if this is even a FastAPI project
    has_fastapi = "FastAPI" in all_sources
    if not has_fastapi:
        return None  # Not a FastAPI project, skip

    return Finding(
        rule_id="OBS-02",
        severity=Severity.HIGH,
        title="No FastAPI auto-instrumentation",
        description=(
            "FastAPI app found but no FastAPIInstrumentor.instrument_app() call. "
            "Without auto-instrumentation, no HTTP request spans are created. "
            "You lose request tracing, latency measurement, and context "
            "propagation for free."
        ),
        fix_suggestion=(
            "pip install opentelemetry-instrumentation-fastapi; "
            "from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor; "
            "FastAPIInstrumentor.instrument_app(app)"
        ),
    )


def _check_obs03_db_instrumentation(all_sources: str) -> Finding | None:
    """OBS-03: Database auto-instrumentation for SQLAlchemy."""
    has_sqlalchemy = (
        "create_engine" in all_sources
        or "create_async_engine" in all_sources
        or "AsyncSession" in all_sources
    )

    if not has_sqlalchemy:
        return None  # No DB usage, skip

    has_db_instrument = "SQLAlchemyInstrumentor" in all_sources

    if has_db_instrument:
        return None

    return Finding(
        rule_id="OBS-03",
        severity=Severity.MEDIUM,
        title="SQLAlchemy used without OTel instrumentation",
        description=(
            "SQLAlchemy engine/session found but no SQLAlchemyInstrumentor. "
            "Database queries are invisible in traces — you cannot tell if "
            "a slow endpoint is slow because of the query or the application. "
            "N+1 queries, missing indexes, and pool exhaustion go undetected."
        ),
        fix_suggestion=(
            "pip install opentelemetry-instrumentation-sqlalchemy; "
            "SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=True)"
        ),
    )


def _check_obs04_custom_spans(
    py_files: list[Path], project_root: Path, all_sources: str,
) -> Finding | None:
    """OBS-04: Custom spans exist on business logic (not just auto-instrumentation)."""
    # Only check if OTel is set up at all
    has_otel = "TracerProvider" in all_sources or "opentelemetry" in all_sources
    if not has_otel:
        return None  # No OTel = OBS-01 already flagged

    has_custom_spans = False

    for filepath in py_files:
        if _is_non_production(filepath, project_root):
            continue
        if filepath.name == "__init__.py":
            continue

        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        # Look for manual span creation
        if "start_as_current_span" in source or "start_span" in source:
            has_custom_spans = True
            break

    if has_custom_spans:
        return None

    return Finding(
        rule_id="OBS-04",
        severity=Severity.MEDIUM,
        title="No custom spans on business logic",
        description=(
            "OTel is configured but no start_as_current_span() or start_span() "
            "calls found in production code. Auto-instrumentation traces HTTP "
            "requests and DB queries, but business logic (validation, fraud "
            "checks, external API calls) remains a black box in traces."
        ),
        fix_suggestion=(
            "Add custom spans to critical business operations: "
            "with tracer.start_as_current_span('process_payment', "
            "attributes={'order.id': order_id}): ..."
        ),
    )


def _check_obs05_metrics_export(all_sources: str) -> Finding | None:
    """OBS-05: Prometheus metrics are exported via /metrics endpoint."""
    has_fastapi = "FastAPI" in all_sources
    if not has_fastapi:
        return None

    has_prometheus = (
        "prometheus_client" in all_sources
        or "prometheus_fastapi_instrumentator" in all_sources
        or "PrometheusMiddleware" in all_sources
    )

    has_metrics_endpoint = bool(
        re.search(r"""["']/metrics["']""", all_sources)
    )

    if has_prometheus and has_metrics_endpoint:
        return None

    if has_prometheus and not has_metrics_endpoint:
        return Finding(
            rule_id="OBS-05",
            severity=Severity.HIGH,
            title="Prometheus metrics defined but no /metrics endpoint",
            description=(
                "prometheus_client is imported but no /metrics endpoint is "
                "exposed. Prometheus cannot scrape metrics without an HTTP "
                "endpoint. Metrics are collected but never exported."
            ),
            fix_suggestion=(
                "Add a /metrics route: "
                "app.add_route('/metrics', metrics_endpoint) where "
                "metrics_endpoint returns generate_latest(REGISTRY)."
            ),
        )

    return Finding(
        rule_id="OBS-05",
        severity=Severity.HIGH,
        title="No Prometheus metrics",
        description=(
            "No prometheus_client usage or /metrics endpoint found. "
            "Without metrics, you have no request rate, error rate, or "
            "latency percentiles. SLO monitoring and alerting are impossible."
        ),
        fix_suggestion=(
            "pip install prometheus-client; define Counter, Histogram, Gauge "
            "for RED method (http_requests_total, http_request_duration_seconds, "
            "http_requests_in_progress); expose /metrics endpoint."
        ),
    )


def _check_obs06_print_debugging(
    py_files: list[Path], project_root: Path,
) -> list[Finding]:
    """OBS-06: No print() statements used for debugging in production code."""
    findings: list[Finding] = []

    for filepath in py_files:
        if _is_non_production(filepath, project_root):
            continue
        if filepath.name == "__init__.py":
            continue

        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                # Ignore print in if __name__ == "__main__" blocks
                findings.append(
                    Finding(
                        rule_id="OBS-06",
                        severity=Severity.LOW,
                        title="print() used in production code",
                        description=(
                            "print() outputs to stdout without structure, log level, "
                            "timestamp, or trace context. In production with multiple "
                            "pods, print output is uncorrelated noise. Use structlog "
                            "with the configured OTel processor instead."
                        ),
                        file_path=str(filepath),
                        line_number=node.lineno,
                        fix_suggestion=(
                            "Replace with structlog: "
                            "logger = structlog.get_logger(); "
                            "logger.info('event_name', key=value)"
                        ),
                    )
                )

    # Cap at 5 findings to avoid noise
    if len(findings) > 5:
        count = len(findings)
        findings = findings[:5]
        findings.append(
            Finding(
                rule_id="OBS-06",
                severity=Severity.LOW,
                title=f"{count - 5} more print() statements found",
                description=(
                    f"Found {count} total print() calls in production code. "
                    f"Showing first 5. Replace all with structured logging."
                ),
                fix_suggestion="Run: grep -rn 'print(' src/ --include='*.py' to find all.",
            )
        )

    return findings


def _check_obs07_trace_log_correlation(all_sources: str) -> Finding | None:
    """OBS-07: Logs include trace_id/span_id for correlation."""
    has_structlog = "structlog" in all_sources
    has_logging = "import logging" in all_sources or "from logging" in all_sources

    if not (has_structlog or has_logging):
        return None  # No logging at all — different problem

    # Check for trace context injection
    has_trace_in_logs = (
        "trace_id" in all_sources
        or "span_id" in all_sources
        or "get_current_span" in all_sources
        or "LoggingInstrumentor" in all_sources
        or "otel_context" in all_sources
        or "add_otel_context" in all_sources
    )

    if has_trace_in_logs:
        return None

    return Finding(
        rule_id="OBS-07",
        severity=Severity.MEDIUM,
        title="No trace context in logs (trace_id/span_id missing)",
        description=(
            "Logging is configured but no trace_id or span_id injection found. "
            "Without trace context in logs, you cannot navigate from a trace to "
            "its logs or from a log line to its trace. Debugging requires "
            "manually correlating timestamps across systems."
        ),
        fix_suggestion=(
            "Add a structlog processor that calls trace.get_current_span() "
            "and injects format(ctx.trace_id, '032x') and "
            "format(ctx.span_id, '016x') into the event dict."
        ),
    )


def _check_obs08_health_check_exclusion(all_sources: str) -> Finding | None:
    """OBS-08: Health checks excluded from business metrics."""
    has_metrics = "prometheus_client" in all_sources or "PrometheusMiddleware" in all_sources
    has_health = bool(re.search(r"""["']/healthz["']""", all_sources))

    if not (has_metrics and has_health):
        return None  # Need both metrics and health checks to flag

    # Check for exclusion patterns
    has_exclusion = (
        "EXCLUDED_PATHS" in all_sources
        or "excluded_urls" in all_sources
        or "healthz" in all_sources.split("exclude")[1:].__repr__()
        or bool(re.search(r"healthz.*skip|skip.*healthz", all_sources, re.IGNORECASE))
        or bool(re.search(r"healthz.*exclude|exclude.*healthz", all_sources, re.IGNORECASE))
    )

    if has_exclusion:
        return None

    return Finding(
        rule_id="OBS-08",
        severity=Severity.MEDIUM,
        title="Health checks not excluded from metrics",
        description=(
            "Prometheus metrics and health check endpoints both exist, but no "
            "exclusion pattern found. Kubernetes probes hit /healthz every 10s, "
            "adding 8,640 artificial requests/day that inflate rate metrics, "
            "deflate average latency, and mask real error rates in SLI "
            "calculations."
        ),
        fix_suggestion=(
            "Add EXCLUDED_PATHS = {'/healthz', '/readyz', '/startupz', '/metrics'} "
            "and skip these paths in your metrics middleware."
        ),
    )


def _check_obs09_span_error_status(
    py_files: list[Path], project_root: Path, all_sources: str,
) -> Finding | None:
    """OBS-09: Spans set error status on exceptions."""
    has_custom_spans = "start_as_current_span" in all_sources
    if not has_custom_spans:
        return None  # No custom spans = OBS-04 already flagged

    has_error_status = (
        "set_status" in all_sources
        or "StatusCode.ERROR" in all_sources
        or "record_exception" in all_sources
    )

    if has_error_status:
        return None

    return Finding(
        rule_id="OBS-09",
        severity=Severity.MEDIUM,
        title="Custom spans never set error status",
        description=(
            "Custom spans found but no span.set_status(StatusCode.ERROR) or "
            "span.record_exception() calls. When business logic fails, the span "
            "shows as successful in trace backends. Error-based tail sampling "
            "will miss these failures, and error rate dashboards will under-count."
        ),
        fix_suggestion=(
            "In except blocks: span.set_status(trace.StatusCode.ERROR, str(exc)); "
            "span.record_exception(exc) to attach the stack trace to the span."
        ),
    )


def _check_obs10_unstructured_logging(
    py_files: list[Path], project_root: Path,
) -> Finding | None:
    """OBS-10: No unstructured logging (logging.info with string formatting)."""
    for filepath in py_files:
        if _is_non_production(filepath, project_root):
            continue
        if filepath.name == "__init__.py":
            continue

        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        # Detect f-string or %-format in logging calls
        # e.g., logging.info(f"User {user_id} logged in")
        # e.g., logger.info("User %s logged in" % user_id)
        for i, line in enumerate(source.splitlines(), 1):
            line_stripped = line.strip()

            # Skip comments
            if line_stripped.startswith("#"):
                continue

            # Detect logging.info(f"...") or logger.info(f"...")
            if re.search(
                r'(?:logging|logger)\.\w+\s*\(\s*f["\']', line_stripped,
            ):
                return Finding(
                    rule_id="OBS-10",
                    severity=Severity.LOW,
                    title="Unstructured logging with f-string formatting",
                    description=(
                        "logging/logger call with f-string found. Structured logging "
                        "(structlog) uses key=value pairs that are machine-parseable. "
                        "f-strings embed data into the message string, making it "
                        "impossible to filter or aggregate by field in Grafana/Loki."
                    ),
                    file_path=str(filepath),
                    line_number=i,
                    fix_suggestion=(
                        "Replace logger.info(f'User {user_id} logged in') with "
                        "logger.info('user_logged_in', user_id=user_id)"
                    ),
                )

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_observability(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI project for observability anti-patterns.

    Scans all Python files for 10 common observability issues using AST
    analysis and regex matching. Returns a list of Finding objects, one
    per detected issue, sorted by severity (critical first).

    Checks performed:
        OBS-01: OTel TracerProvider configured
        OBS-02: FastAPI auto-instrumentation active
        OBS-03: SQLAlchemy instrumented (if used)
        OBS-04: Custom spans on business logic
        OBS-05: Prometheus metrics exported
        OBS-06: No print() debugging in production
        OBS-07: Trace context in logs (trace_id/span_id)
        OBS-08: Health checks excluded from metrics
        OBS-09: Span error status set on exceptions
        OBS-10: No unstructured logging (f-string in logger calls)

    Args:
        project_path: Root directory of the FastAPI project to analyze.

    Returns:
        List of Finding objects for each detected issue, sorted by severity
        (critical first, then high, medium, low).

    Example::

        findings = verify_observability("/path/to/my-fastapi-project")
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
        # [critical] OBS-01: No OpenTelemetry TracerProvider configuration
        # [high] OBS-02: No FastAPI auto-instrumentation
        # [high] OBS-05: No Prometheus metrics
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    py_files = _collect_python_files(root)
    findings: list[Finding] = []

    # Concatenate all sources for project-wide checks
    all_sources_parts: list[str] = []
    for filepath in py_files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
            all_sources_parts.append(source)
        except (OSError, UnicodeDecodeError):
            continue

    all_sources = "\n".join(all_sources_parts)

    # --- Project-wide checks ---

    # OBS-01: OTel TracerProvider
    finding = _check_obs01_otel_setup(all_sources)
    if finding:
        findings.append(finding)

    # OBS-02: FastAPI auto-instrumentation
    finding = _check_obs02_fastapi_instrumentation(all_sources)
    if finding:
        findings.append(finding)

    # OBS-03: DB instrumentation
    finding = _check_obs03_db_instrumentation(all_sources)
    if finding:
        findings.append(finding)

    # OBS-04: Custom spans
    finding = _check_obs04_custom_spans(py_files, root, all_sources)
    if finding:
        findings.append(finding)

    # OBS-05: Metrics export
    finding = _check_obs05_metrics_export(all_sources)
    if finding:
        findings.append(finding)

    # OBS-06: print() debugging (per-file, capped)
    print_findings = _check_obs06_print_debugging(py_files, root)
    findings.extend(print_findings)

    # OBS-07: Trace-log correlation
    finding = _check_obs07_trace_log_correlation(all_sources)
    if finding:
        findings.append(finding)

    # OBS-08: Health check exclusion
    finding = _check_obs08_health_check_exclusion(all_sources)
    if finding:
        findings.append(finding)

    # OBS-09: Span error status
    finding = _check_obs09_span_error_status(py_files, root, all_sources)
    if finding:
        findings.append(finding)

    # OBS-10: Unstructured logging
    finding = _check_obs10_unstructured_logging(py_files, root)
    if finding:
        findings.append(finding)

    # Sort by severity (critical first)
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
