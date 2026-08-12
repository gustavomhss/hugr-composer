"""TOOL-123: add_dependency_health_map — visual dependency status map.

Migrated to per-tool directory + externalized templates (WP-02b).

Generates a ``HealthMapBuilder`` that discovers all dependencies from config
(DB, Redis, S3, Stripe, etc.), runs async health checks per dependency with
latency and status, and serves the results as both a JSON graph and a
self-contained SVG visualization.

Idempotent: a second run detects ``HealthMapBuilder`` in
``app/health_map/__init__.py`` and returns ``status="no_op"``.
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
    "name": "fastapi_resiliency_add_dependency_health_map",
    "description": (
        "Add a visual dependency health map: HealthMapBuilder discovers all deps from config "
        "(DB, Redis, S3, Stripe), DependencyChecker async health check per dep with latency+status, "
        "GET /health/map (JSON graph), GET /health/map.html (self-contained SVG visualization). "
        "Config: HEALTH_MAP_ENABLED, HEALTH_MAP_CHECK_INTERVAL_S."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_dependency_health_map",
    "imports_primitives": [],
    "imports_adapters": [],

}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_dependency_health_map(inp: ToolInput) -> ToolResult:
    """Add a dependency health map to a FastAPI project."""
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
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    hmap_init = app_dir / "health_map" / "__init__.py"
    if hmap_init.exists() and "HealthMapBuilder" in hmap_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "HealthMapBuilder already present — dependency health map already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/health_map/ package with HealthMapBuilder and DependencyChecker.",
                "[dry_run] Would create app/api/routes/health_map.py with JSON + HTML endpoints.",
                "[dry_run] Would patch app/core/config.py and app/main.py.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: health_map package (externalized templates) -----------------
    hmap_dir = app_dir / "health_map"
    hmap_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "health_map_init.py.tmpl", dest=hmap_init, substitutions={})
    files_created.append(str(hmap_init))

    checker_file = hmap_dir / "checker.py"
    render_to(_HERE, "health_map_checker.py.tmpl", dest=checker_file, substitutions={})
    files_created.append(str(checker_file))

    # --- Step 2: health map routes -------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        route_file = routes_dir / "health_map.py"
        render_to(_HERE, "health_map_routes.py.tmpl", dest=route_file, substitutions={})
        files_created.append(str(route_file))

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
            "Dependency health map enabled: HealthMapBuilder discovers deps from config env vars.",
            "DependencyChecker runs async checks with timeout+latency per dependency.",
            "GET /health/map returns a JSON dependency graph (nodes+edges with status).",
            "GET /health/map.html returns a self-contained SVG visualization (no build step).",
            "Discovered dependencies: database, redis, s3, stripe (config-driven).",
        ],
        next_steps=[
            "Set HEALTH_MAP_ENABLED=true in .env (default: false).",
            "Set HEALTH_MAP_CHECK_INTERVAL_S in .env (default: 30).",
            "Visit /health/map.html in your browser for the visual dependency status map.",
            "Add custom deps: HealthMapBuilder.register('my-service', check_fn).",
            "Wire /health/map into your on-call runbook for instant dependency triage.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# In-place patchers
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path) -> None:
    """Inject health map settings into app/core/config.py."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("HEALTH_MAP_ENABLED", "HEALTH_MAP_ENABLED: bool = False"),
            ("HEALTH_MAP_CHECK_INTERVAL_S", "HEALTH_MAP_CHECK_INTERVAL_S: int = 30"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Register health_map router in app/main.py."""
    src = main_file.read_text()
    if "health_map" in src:
        return

    hmap_import = (
        "\nfrom app.api.routes.health_map import router as health_map_router"
        "  # noqa: E402 — dependency health map\n"
    )
    hmap_register = render(_HERE, "main_register_snippet.txt.tmpl", {})

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + hmap_import,
        )
    else:
        src = hmap_import + src

    src = src.rstrip("\n") + "\n" + hmap_register
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_dependency_health_map_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_dependency_health_map_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


