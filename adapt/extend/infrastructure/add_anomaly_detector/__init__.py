"""TOOL-102: add_anomaly_detector — statistical anomaly detection for FastAPI.

Migrated to per-tool directory + externalized templates (WP-02b).

Generates an ``AnomalyDetector`` (Z-score + EMA on sliding windows), an
``AlertDispatcher`` (webhook + log, lazy httpx), an ``AnomalyMiddleware``
(updates metrics per request), and a ``GET /anomaly/status`` endpoint.

The tool is idempotent: a second run detects ``app/anomaly/detector.py``
containing ``AnomalyDetector`` and returns ``status="no_op"`` without touching
any file.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_anomaly_detector",
    "description": (
        "Add statistical anomaly detection: Z-score + EMA on sliding windows for "
        "request rate, error rate, latency, and payload size. Alerts via webhook or log."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_anomaly_detector",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_anomaly_detector(inp: ToolInput) -> ToolResult:
    """Add anomaly detector to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    detector_file = app_dir / "anomaly" / "detector.py"
    if detector_file.exists() and "AnomalyDetector" in detector_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["AnomalyDetector already present — anomaly detection already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/anomaly/ package with detector, alerter, models.",
                "[dry_run] Would add AnomalyMiddleware to app/main.py.",
                "[dry_run] Would add GET /anomaly/status route.",
                "[dry_run] Would patch app/core/config.py with ANOMALY_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # --- Step 1: anomaly package (externalized templates) -------------------
    anomaly_dir = app_dir / "anomaly"
    anomaly_dir.mkdir(parents=True, exist_ok=True)

    init_file = anomaly_dir / "__init__.py"
    render_to(_HERE, "anomaly_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    render_to(_HERE, "anomaly_detector.py.tmpl", dest=detector_file, substitutions={})
    files_created.append(str(detector_file))

    alerter_file = anomaly_dir / "alerter.py"
    render_to(_HERE, "anomaly_alerter.py.tmpl", dest=alerter_file, substitutions={})
    files_created.append(str(alerter_file))

    models_file = anomaly_dir / "models.py"
    render_to(_HERE, "anomaly_models.py.tmpl", dest=models_file, substitutions={})
    files_created.append(str(models_file))

    # --- Step 2: middleware --------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_file = middleware_dir / "anomaly.py"
    render_to(_HERE, "anomaly_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    # --- Step 3: routes ------------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "anomaly.py"
        render_to(_HERE, "anomaly_routes.py.tmpl", dest=status_route, substitutions={})
        files_created.append(str(status_route))

    # --- Step 4: patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: emit project test (P1 #15) ---------------------------------
    _emit_project_test(project, files_created)

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
            "Anomaly detector added: Z-score + EMA on sliding windows.",
            "Metrics tracked: request rate, error rate, p99 latency, payload size.",
            "Alerts dispatched via webhook (lazy httpx) and log.",
            "GET /anomaly/status returns current baselines + deviations.",
        ],
        next_steps=[
            "Set ANOMALY_ENABLED=true in .env (default: false).",
            "Optional: set ANOMALY_SENSITIVITY (default: 3.0 — standard deviations).",
            "Optional: set ANOMALY_WINDOW_SIZE (default: 100 — samples per window).",
            "Optional: set ANOMALY_ALERT_WEBHOOK_URL for webhook alerts.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# In-place patchers
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path) -> None:
    """Inject ANOMALY_* fields into ``class Settings`` in config.py."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("ANOMALY_ENABLED", "ANOMALY_ENABLED: bool = False"),
            ("ANOMALY_SENSITIVITY", "ANOMALY_SENSITIVITY: float = 3.0"),
            ("ANOMALY_WINDOW_SIZE", "ANOMALY_WINDOW_SIZE: int = 100"),
            ("ANOMALY_ALERT_WEBHOOK_URL", 'ANOMALY_ALERT_WEBHOOK_URL: str = ""'),
        ],
    )


# ---------------------------------------------------------------------------
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_anomaly_detector_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_anomaly_detector_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
