"""TOOL-123: add_dependency_health_map — visual dependency status map.

Generates a ``HealthMapBuilder`` that discovers all dependencies from config
(DB, Redis, S3, Stripe, etc.), runs async health checks per dependency with
latency and status, and serves the results as both a JSON graph and a
self-contained SVG visualization.

Idempotent: a second run detects ``HealthMapBuilder`` in
``app/health_map/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_dependency_health_map import (
        add_dependency_health_map,
    )

    result = add_dependency_health_map(ToolInput(project_dir="/path/to/project"))
    print(result.status)          # "success"
    print(result.files_created)   # [.../app/health_map/__init__.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


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
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_dependency_health_map(inp: ToolInput) -> ToolResult:
    """Add a dependency health map to a FastAPI project.

    Writes ``app/health_map/`` package, a JSON+HTML route, patches
    ``app/core/config.py``, and registers the router in ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

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
            notes=["HealthMapBuilder already present — dependency health map already enabled, skipped."],
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

    # --- Step 1: health_map package ------------------------------------------
    hmap_dir = app_dir / "health_map"
    hmap_dir.mkdir(parents=True, exist_ok=True)

    _write_health_map_init(hmap_init)
    files_created.append(str(hmap_init))

    _write_dependency_checker(hmap_dir / "checker.py")
    files_created.append(str(hmap_dir / "checker.py"))

    # --- Step 2: health map routes -------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        route_file = routes_dir / "health_map.py"
        _write_health_map_routes(route_file)
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

    # --- Validate generated .py files ----------------------------------------
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
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_health_map_init(dest: Path) -> None:
    """Write app/health_map/__init__.py — HealthMapBuilder discovery.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Dependency health map — HealthMapBuilder and public API.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import os
        import time
        from typing import Any

        logger = logging.getLogger(__name__)

        _KNOWN_DEPS = {
            "database": "POSTGRES_SERVER",
            "redis": "REDIS_URL",
            "s3": "AWS_S3_BUCKET",
            "stripe": "STRIPE_SECRET_KEY",
        }


        class HealthMapBuilder:
            \"\"\"Discovers dependencies from environment and builds a health graph.

            Uses config env vars to detect which dependencies are configured.
            Only enabled deps (env var present and non-empty) appear in the map.
            \"\"\"

            def __init__(self) -> None:
                self._extra: dict[str, Any] = {}

            def discover(self) -> list[str]:
                \"\"\"Return list of dependency names that are configured in env.\"\"\"
                found = []
                for dep, env_key in _KNOWN_DEPS.items():
                    if os.getenv(env_key, ""):
                        found.append(dep)
                found.extend(self._extra.keys())
                return found

            def register(self, name: str, check_fn: Any) -> None:
                \"\"\"Register a custom dependency check function.

                Args:
                    name: Dependency name (used as graph node label).
                    check_fn: Async callable returning dict with 'status' key.
                \"\"\"
                self._extra[name] = check_fn

            async def build_graph(self) -> dict[str, Any]:
                \"\"\"Run all checks and return a JSON-serializable dependency graph.

                Returns:
                    Dict with 'nodes' (list of dep status) and 'edges'
                    (list of {"from": "api", "to": dep_name}).
                \"\"\"
                from app.health_map.checker import DependencyChecker

                checker = DependencyChecker()
                dep_names = self.discover()
                results = await asyncio.gather(
                    *[checker.check(name) for name in dep_names],
                    return_exceptions=True,
                )
                nodes = []
                for name, res in zip(dep_names, results):
                    if isinstance(res, Exception):
                        nodes.append({"name": name, "status": "error", "latency_ms": 0})
                    else:
                        nodes.append(res)
                edges = [{"from": "api", "to": n["name"]} for n in nodes]
                overall = _aggregate(nodes)
                return {"status": overall, "nodes": nodes, "edges": edges}


        def _aggregate(nodes: list[dict[str, Any]]) -> str:
            \"\"\"Return worst-case status across all nodes.

            Args:
                nodes: List of node dicts with 'status' key.
            \"\"\"
            statuses = {n.get("status", "unknown") for n in nodes}
            if "error" in statuses or "unhealthy" in statuses:
                return "unhealthy"
            if "degraded" in statuses:
                return "degraded"
            return "healthy"


        _builder: HealthMapBuilder | None = None


        def get_health_map_builder() -> HealthMapBuilder:
            \"\"\"Return the process-wide HealthMapBuilder singleton.\"\"\"
            global _builder
            if _builder is None:
                _builder = HealthMapBuilder()
            return _builder
        """))


def _write_dependency_checker(dest: Path) -> None:
    """Write app/health_map/checker.py — DependencyChecker per-dep async check.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"DependencyChecker — async health check per dependency with latency.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import os
        import time
        from typing import Any

        logger = logging.getLogger(__name__)

        _TIMEOUT_S = 5.0


        class DependencyChecker:
            \"\"\"Performs async health checks for known dependency types.\"\"\"

            async def check(self, name: str) -> dict[str, Any]:
                \"\"\"Run the health check for a named dependency.

                Args:
                    name: Dependency name (database, redis, s3, stripe, or custom).

                Returns:
                    Dict with 'name', 'status', 'latency_ms', and 'detail'.
                \"\"\"
                dispatch = {
                    "database": self._check_database,
                    "redis": self._check_redis,
                    "s3": self._check_s3,
                    "stripe": self._check_stripe,
                }
                fn = dispatch.get(name, self._check_unknown)
                t0 = time.monotonic()
                try:
                    result = await asyncio.wait_for(fn(name), timeout=_TIMEOUT_S)
                    result["latency_ms"] = int((time.monotonic() - t0) * 1000)
                    return result
                except asyncio.TimeoutError:
                    return {"name": name, "status": "unhealthy",
                            "latency_ms": int(_TIMEOUT_S * 1000), "detail": "timeout"}
                except Exception as exc:  # noqa: BLE001
                    return {"name": name, "status": "unhealthy",
                            "latency_ms": int((time.monotonic() - t0) * 1000),
                            "detail": str(exc)}

            async def _check_database(self, name: str) -> dict[str, Any]:
                \"\"\"Check PostgreSQL connectivity via SELECT 1.

                Args:
                    name: Dependency label for the result dict.
                \"\"\"
                try:
                    from app.core.db import engine  # deferred import
                    import sqlalchemy  # noqa: PLC0415

                    async with engine.connect() as conn:
                        await conn.execute(sqlalchemy.text("SELECT 1"))
                    return {"name": name, "status": "healthy", "detail": "ok"}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("DB health check failed: %s", exc)
                    return {"name": name, "status": "unhealthy", "detail": str(exc)}

            async def _check_redis(self, name: str) -> dict[str, Any]:
                \"\"\"Ping Redis to verify connectivity.

                Args:
                    name: Dependency label for the result dict.
                \"\"\"
                try:
                    from redis.asyncio import Redis  # noqa: PLC0415

                    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                    client = Redis.from_url(url, decode_responses=True)
                    try:
                        await client.ping()
                    finally:
                        await client.aclose()
                    return {"name": name, "status": "healthy", "detail": "pong"}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Redis health check failed: %s", exc)
                    return {"name": name, "status": "unhealthy", "detail": str(exc)}

            async def _check_s3(self, name: str) -> dict[str, Any]:
                \"\"\"Check S3 bucket accessibility via head_bucket.

                Args:
                    name: Dependency label for the result dict.
                \"\"\"
                try:
                    import aiobotocore.session  # noqa: PLC0415

                    bucket = os.getenv("AWS_S3_BUCKET", "")
                    session = aiobotocore.session.get_session()
                    async with session.create_client("s3") as client:
                        await client.head_bucket(Bucket=bucket)
                    return {"name": name, "status": "healthy", "detail": bucket}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("S3 health check failed: %s", exc)
                    return {"name": name, "status": "unhealthy", "detail": str(exc)}

            async def _check_stripe(self, name: str) -> dict[str, Any]:
                \"\"\"Verify Stripe API key is set (avoids live API call).

                Args:
                    name: Dependency label for the result dict.
                \"\"\"
                key = os.getenv("STRIPE_SECRET_KEY", "")
                if key:
                    return {"name": name, "status": "healthy", "detail": "key present"}
                return {"name": name, "status": "unhealthy", "detail": "STRIPE_SECRET_KEY not set"}

            async def _check_unknown(self, name: str) -> dict[str, Any]:
                \"\"\"Fallback for unrecognised dependency names.

                Args:
                    name: Dependency label for the result dict.
                \"\"\"
                return {"name": name, "status": "unknown", "detail": "no check registered"}
        """))


def _write_health_map_routes(dest: Path) -> None:
    """Write app/api/routes/health_map.py — JSON graph + SVG HTML endpoints.

    Args:
        dest: Absolute path for the file.
    """
    # Build the template as explicit lines to avoid textwrap.dedent
    # misidentifying the minimum indent due to implicit string continuation.
    lines = [
        '"""Dependency health map endpoints: JSON graph and SVG visualization."""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "import math",
        "from typing import Any",
        "",
        "from fastapi import APIRouter, Response",
        "from fastapi.responses import HTMLResponse",
        "",
        "from app.health_map import get_health_map_builder",
        "",
        'router = APIRouter(prefix="/health", tags=["health-map"])',
        "",
        "",
        '@router.get("/map", response_model=dict[str, Any])',
        "async def dependency_map() -> dict[str, Any]:",
        '    """Return the dependency health graph as JSON.',
        "",
        "    Returns:",
        "        Dict with 'status', 'nodes' (per-dep status+latency),",
        "        and 'edges' (api to each dep).",
        '    """',
        "    builder = get_health_map_builder()",
        "    return await builder.build_graph()",
        "",
        "",
        '@router.get("/map.html", response_class=HTMLResponse)',
        "async def dependency_map_html(response: Response) -> HTMLResponse:",
        '    """Return a self-contained SVG visualization of the dependency health map.',
        "",
        "    Sets HTTP 503 when any dependency is unhealthy.",
        "",
        "    Args:",
        "        response: FastAPI Response for setting the status code.",
        "",
        "    Returns:",
        "        HTMLResponse with inline SVG dependency graph.",
        '    """',
        "    builder = get_health_map_builder()",
        "    graph = await builder.build_graph()",
        '    if graph.get("status") == "unhealthy":',
        "        response.status_code = 503",
        '    nodes = graph.get("nodes", [])',
        "    graph_json = json.dumps(graph, indent=2)",
        "    html = _render_svg_page(nodes, graph_json)",
        "    return HTMLResponse(content=html)",
        "",
        "",
        "def _status_color(status: str) -> str:",
        '    """Return an SVG fill colour for a given status string.',
        "",
        "    Args:",
        "        status: 'healthy', 'degraded', 'unhealthy', or other.",
        '    """',
        '    _map = {"healthy": "#22c55e", "degraded": "#f59e0b", "unhealthy": "#ef4444"}',
        '    return _map.get(status, "#64748b")',
        "",
        "",
        "def _render_svg_page(nodes: list[dict], graph_json: str) -> str:",
        '    """Build the complete HTML page with an inline SVG dependency map.',
        "",
        "    Args:",
        "        nodes: List of node dicts from the health graph.",
        "        graph_json: Pretty-printed JSON for the raw data panel.",
        "",
        "    Returns:",
        "        Complete HTML string ready to serve.",
        '    """',
        "    cx, cy, r_orbit = 400, 150, 200",
        "    parts: list[str] = []",
        '    parts.append(\'<circle cx="{}" cy="{}" r="40" fill="#3b82f6"/>\'.format(cx, cy))',
        '    parts.append(\'<text x="{}" y="{}" text-anchor="middle" fill="#fff"\'',
        '                 \' font-size="14" dy=".35em">API</text>\'.format(cx, cy))',
        "    n = len(nodes)",
        "    for i, node in enumerate(nodes):",
        "        angle = (2 * math.pi * i / max(n, 1)) - math.pi / 2",
        "        nx = int(cx + r_orbit * math.cos(angle))",
        "        ny = int(cy + r_orbit * math.sin(angle))",
        "        color = _status_color(node.get(\"status\", \"unknown\"))",
        "        label = node.get(\"name\", \"?\")",
        "        lat = node.get(\"latency_ms\", 0)",
        '        parts.append(\'<line x1="{0}" y1="{1}" x2="{2}" y2="{3}"\'',
        '                     \' stroke="#334155" stroke-width="2"/>\'.format(cx, cy, nx, ny))',
        '        parts.append(\'<circle cx="{0}" cy="{1}" r="35" fill="{2}"/>\'.format(',
        "            nx, ny, color))",
        '        parts.append(\'<text x="{0}" y="{1}" text-anchor="middle" fill="#fff"\'',
        '                     \' font-size="11" dy=".35em">{2}</text>\'.format(nx, ny, label))',
        '        parts.append(\'<text x="{0}" y="{1}" text-anchor="middle"\'',
        '                     \' fill="#e2e8f0" font-size="9">{2} ms</text>\'.format(',
        "            nx, ny + 20, lat))",
        '    svg_inner = "\\n  ".join(parts)',
        '    head = (\'<!DOCTYPE html><html lang="en"><head>\'',
        '            \'<meta charset="UTF-8"><title>Dependency Health Map</title>\'',
        '            \'<style>body{background:#0f172a;color:#e2e8f0;font-family:sans-serif;\'',
        "            'padding:1.5rem}h1{color:#7dd3fc;margin-bottom:1rem}'",
        "            'pre{background:#1e293b;padding:1rem;border-radius:.5rem;'",
        "            'overflow:auto;font-size:.8rem;margin-top:1rem;color:#bfdbfe}'",
        "            '</style></head><body>'",
        "            '<h1>&#x1f5fa; Dependency Health Map</h1>')",
        '    svg_tag = \'<svg width="800" height="400" style="background:#1e293b">\' + svg_inner + "</svg>"',
        '    tail = "<pre>" + graph_json + "</pre></body></html>"',
        "    return head + svg_tag + tail",
    ]
    dest.write_text("\n".join(lines) + "\n")


def _patch_config(config_file: Path) -> None:
    """Inject health map settings into app/core/config.py.

    Fields are inserted inside the ``class Settings`` body with 4-space
    indent so Pydantic picks them up as class-level field declarations.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("HEALTH_MAP_ENABLED", "HEALTH_MAP_ENABLED: bool = False"),
            ("HEALTH_MAP_CHECK_INTERVAL_S", "HEALTH_MAP_CHECK_INTERVAL_S: int = 30"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Register health_map router in app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "health_map" in src:
        return

    hmap_import = (
        "\nfrom app.api.routes.health_map import router as health_map_router"
        "  # noqa: E402 — dependency health map\n"
    )
    hmap_register = textwrap.dedent("""\

        # Dependency health map — added by add_dependency_health_map tool
        app.include_router(health_map_router)
    """)

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
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
