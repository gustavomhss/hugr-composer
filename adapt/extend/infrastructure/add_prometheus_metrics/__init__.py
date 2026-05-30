"""TOOL-086: add_prometheus_metrics — Prometheus RED metrics for a FastAPI project.

Migrated to per-tool directory + externalized templates (WP-02a).

Generates a ``RequestMetrics`` class with request_total, request_duration_seconds,
and request_errors_total counters/histograms via lazy ``prometheus_client`` import,
a ``PrometheusMiddleware`` that instruments every request, and a ``GET /metrics``
endpoint that returns text/plain in Prometheus exposition format.

The tool is idempotent: a second run detects ``app/metrics/collectors.py`` and
returns ``status="no_op"`` without touching any file.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_observability_add_prometheus_metrics",
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
    """Add Prometheus metrics layer to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

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

    # --- Step 1: metrics package (externalized templates) -------------------
    metrics_dir = app_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    init_file = metrics_dir / "__init__.py"
    render_to(_HERE, "metrics_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    render_to(_HERE, "metrics_collectors.py.tmpl", dest=collectors_file, substitutions={})
    files_created.append(str(collectors_file))

    middleware_file = metrics_dir / "middleware.py"
    render_to(_HERE, "metrics_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    # --- Step 2: /metrics route ----------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        metrics_route = routes_dir / "metrics.py"
        render_to(_HERE, "metrics_route.py.tmpl", dest=metrics_route, substitutions={})
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
            req_file.write_text(req_src.rstrip("\n") + "\nprometheus-client>=0.20.0\n")
            files_modified.append(str(req_file))

    # --- Step 6: emit project test (P1 #15) ---------------------------------
    _emit_project_test(project, files_created)

    # --- Step 7: ast.parse validation ----------------------------------------
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
# In-place patchers — surgical edits to existing files
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path) -> None:
    """Inject PROMETHEUS_* fields into ``class Settings`` in config.py."""
    src = config_file.read_text()
    if "PROMETHEUS_ENABLED" in src:
        return

    new_fields = (
        "\n"
        "    # Prometheus metrics — added by add_prometheus_metrics tool\n"
        "    PROMETHEUS_ENABLED: bool = True\n"
        '    PROMETHEUS_PREFIX: str = "http"\n'
    )
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    if anchor in src:
        src = src.replace(anchor, anchor + new_fields)
    else:
        for decorator in ("    @computed_field", "    @model_validator", "    @property"):
            if decorator in src:
                first_pos = src.index(decorator)
                src = src[:first_pos] + new_fields + "\n" + src[first_pos:]
                break
        else:
            marker = "settings = Settings()"
            if marker in src:
                src = src.replace(marker, new_fields + "\n" + marker)
            else:
                src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject PrometheusMiddleware and /metrics router into app/main.py."""
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
    add_middleware_snippet = render(_HERE, "main_middleware_snippet.txt.tmpl", {})

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
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_prometheus_metrics_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_prometheus_metrics_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
