"""TOOL-061: add_health_deep — upgrade to production-grade deep health checks.

Migrated to per-tool directory + externalized templates (WP-02b).

Replaces the basic ``/healthz``, ``/readyz``, ``/startupz`` routes with a
full health-check system featuring a ``HealthRegistry``, per-dependency
latency tracking, circuit-breaker-style degraded state, and a dependency
matrix endpoint for dashboards and on-call tooling.

The tool is idempotent: a second run detects ``HealthRegistry`` in
``app/health/registry.py`` and returns ``status="no_op"`` without touching
any file.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_health_deep",
    "description": (
        "Upgrade to production-grade deep health checks with HealthRegistry, "
        "dependency matrix, per-check latency, circuit-breaker degraded state, "
        "and /health/live + /health/ready + /health/deep endpoints."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_health_deep",
    "imports_primitives": [],
    "imports_adapters": [],

}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_health_deep(inp: ToolInput) -> ToolResult:
    """Add deep health-check system to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
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
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    registry_file = app_dir / "health" / "registry.py"
    if registry_file.exists() and "HealthRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["HealthRegistry already present — deep health checks already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/health/ package with registry, checks, and models.",
                "[dry_run] Would create app/api/routes/health_deep.py with /health/live+ready+deep.",
                "[dry_run] Would patch app/core/config.py and app/main.py.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: health package (externalized templates) --------------------
    health_dir = app_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)

    checks_dir = health_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "health_init.py.tmpl", dest=health_dir / "__init__.py", substitutions={})
    files_created.append(str(health_dir / "__init__.py"))

    render_to(_HERE, "health_registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    render_to(_HERE, "health_models.py.tmpl", dest=health_dir / "models.py", substitutions={})
    files_created.append(str(health_dir / "models.py"))

    render_to(
        _HERE, "health_checks_init.py.tmpl", dest=checks_dir / "__init__.py", substitutions={}
    )
    files_created.append(str(checks_dir / "__init__.py"))

    render_to(
        _HERE, "health_check_database.py.tmpl", dest=checks_dir / "database.py", substitutions={}
    )
    files_created.append(str(checks_dir / "database.py"))

    render_to(_HERE, "health_check_redis.py.tmpl", dest=checks_dir / "redis.py", substitutions={})
    files_created.append(str(checks_dir / "redis.py"))

    render_to(_HERE, "health_check_disk.py.tmpl", dest=checks_dir / "disk.py", substitutions={})
    files_created.append(str(checks_dir / "disk.py"))

    render_to(_HERE, "health_check_memory.py.tmpl", dest=checks_dir / "memory.py", substitutions={})
    files_created.append(str(checks_dir / "memory.py"))

    # --- Step 2: deep health routes ------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        deep_route = routes_dir / "health_deep.py"
        render_to(_HERE, "health_deep_route.py.tmpl", dest=deep_route, substitutions={})
        files_created.append(str(deep_route))

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
        if "psutil" not in req_src:
            req_file.write_text(req_src.rstrip("\n") + "\npsutil>=6.0.0\n")
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
            "Deep health checks enabled: HealthRegistry with per-dependency latency tracking.",
            "Three endpoints: /health/live (liveness), /health/ready (critical deps), "
            "/health/deep (full dependency matrix).",
            "Checks: PostgreSQL pool stats, Redis ping+memory, disk space, process RSS.",
            "Circuit-breaker: checks failing N times are marked 'degraded' to avoid flapping.",
            "All checks run with asyncio.wait_for(timeout) — never hang the readiness probe.",
        ],
        next_steps=[
            "pip install 'psutil>=6.0.0'",
            "Set HEALTH_CHECK_TIMEOUT_MS in .env (default: 5000).",
            "Set HEALTH_DISK_THRESHOLD_PCT in .env (default: 90).",
            "Set HEALTH_MEMORY_THRESHOLD_MB in .env (default: 512).",
            "Register your checks in app startup: registry.register_check('db', db_check, critical=True)",
            "Point your k8s liveness probe at /health/live and readiness probe at /health/ready.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# In-place patchers
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path) -> None:
    """Inject health-tuning settings into app/core/config.py."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("HEALTH_CHECK_TIMEOUT_MS", "HEALTH_CHECK_TIMEOUT_MS: int = 5000"),
            ("HEALTH_DISK_THRESHOLD_PCT", "HEALTH_DISK_THRESHOLD_PCT: int = 90"),
            ("HEALTH_MEMORY_THRESHOLD_MB", "HEALTH_MEMORY_THRESHOLD_MB: int = 512"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Register health_deep router in app/main.py."""
    src = main_file.read_text()
    if "health_deep" in src:
        return

    health_import = (
        "\nfrom app.api.routes.health_deep import router as health_deep_router"
        "  # noqa: E402 — deep health\n"
    )
    health_register = render(_HERE, "main_register_snippet.txt.tmpl", {})

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + health_import,
        )
    else:
        src = health_import + src

    src = src.rstrip("\n") + "\n" + health_register
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_health_deep_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_health_deep_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


