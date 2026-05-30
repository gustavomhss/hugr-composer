"""TOOL-085: add_opentelemetry — add OpenTelemetry traces, metrics, and logs.

Writes an OTEL telemetry bootstrap (TracerProvider, MeterProvider,
LoggerProvider with ALL opentelemetry imports lazy), a
``OTELMiddleware`` for request tracing, metric counters
(request_count, request_duration, error_count), and integrates with
the existing structlog pipeline.

Idempotent: a second run detects ``init_telemetry`` in
``app/telemetry/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_opentelemetry import add_opentelemetry

    result = add_opentelemetry(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["\u2026/app/telemetry/setup.py", \u2026]
    print(result.next_steps)    # ["pip install opentelemetry-sdk", \u2026]
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base.render import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

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

_NOTES_SUCCESS = [
    "OpenTelemetry layer added: TracerProvider, MeterProvider, LoggerProvider "
    "(all SDK imports lazy), OTELMiddleware for request tracing, "
    "metric counters (request_count, request_duration, error_count).",
    "Structlog integration: trace/span IDs injected into log context.",
    "OTEL_ENABLED=false (default) = zero SDK imports, pure pass-through.",
]
_NEXT_STEPS = [
    "pip install opentelemetry-sdk opentelemetry-exporter-otlp",
    "Set OTEL_ENABLED=true, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME in .env.",
    "Add OTELMiddleware to app/main.py: app.add_middleware(OTELMiddleware)",
    "Call init_telemetry() in your FastAPI lifespan startup.",
    "Restart the FastAPI app to activate tracing.",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


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
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"

    telemetry_init = app_dir / "telemetry" / "__init__.py"
    if telemetry_init.exists() and "init_telemetry" in telemetry_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "init_telemetry already present in app/telemetry/__init__.py — "
                "OpenTelemetry already installed, skipped.",
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/telemetry/ (setup.py, middleware.py, metrics.py),",
                "[dry_run] Would patch app/core/config.py with OTEL_* settings.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    pkg_dir = app_dir / "telemetry"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "telemetry_init.py.tmpl", dest=telemetry_init, substitutions={})
    files_created.append(str(telemetry_init))

    render_to(_HERE, "telemetry_setup.py.tmpl", dest=pkg_dir / "setup.py", substitutions={})
    files_created.append(str(pkg_dir / "setup.py"))

    render_to(
        _HERE, "telemetry_middleware.py.tmpl", dest=pkg_dir / "middleware.py", substitutions={}
    )
    files_created.append(str(pkg_dir / "middleware.py"))

    render_to(_HERE, "telemetry_metrics.py.tmpl", dest=pkg_dir / "metrics.py", substitutions={})
    files_created.append(str(pkg_dir / "metrics.py"))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_opentelemetry_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_opentelemetry_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_opentelemetry_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject OTEL settings into the Settings class body.

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
    """Ensure opentelemetry base packages are in requirements.txt.

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


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
