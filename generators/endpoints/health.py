"""Generator for health check endpoints."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_api_generate_health',
    'description': 'Generate 3-level health checks: /healthz (liveness), /readyz (readiness), /startupz (startup).',
    'tags': ['endpoints', 'generator'],
    'entry': 'generate_health_checks',
}

import textwrap
from pathlib import Path


def generate_health_checks(
    output_dir: str,
    check_db: bool = True,
    check_redis: bool = False,
) -> dict:
    """Generate liveness, readiness, and startup probe endpoints.

    Args:
        output_dir: Directory where routes/health.py will be written.
        check_db: Include database connectivity check in readiness probe.
        check_redis: Include Redis ping in readiness probe.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "routes"
    out.mkdir(parents=True, exist_ok=True)

    # Build imports
    extra_imports = ["import logging"]
    if check_db:
        extra_imports.append("from sqlalchemy import text")
        extra_imports.append("from app.core.db import engine")
    if check_redis:
        extra_imports.append("import redis.asyncio as aioredis")
        extra_imports.append("from app.core.config import settings")

    extra_import_block = ""
    if extra_imports:
        extra_import_block = "\n".join(extra_imports) + "\n"

    # Build readiness check blocks (indented 4 spaces for function body).
    # IMPORTANT: /readyz is unauthenticated and consumed by k8s, load
    # balancers, and external probes.  Never leak exception text —
    # only a generic "down" status.  The real error is logged server-side.
    readiness_checks = ""
    if check_db:
        readiness_checks += textwrap.dedent("""\
            # Database
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                checks["database"] = "ok"
            except Exception as exc:
                _log.error("readiness_db_check_failed", exc_info=exc)
                checks["database"] = "down"
                healthy = False

        """)
    if check_redis:
        readiness_checks += textwrap.dedent("""\
            # Redis
            try:
                r = aioredis.from_url(settings.REDIS_URL)
                await r.ping()
                await r.aclose()
                checks["redis"] = "ok"
            except Exception as exc:
                _log.error("readiness_redis_check_failed", exc_info=exc)
                checks["redis"] = "down"
                healthy = False

        """)

    # Indent checks to function body level (4 spaces)
    if readiness_checks:
        readiness_checks = textwrap.indent(readiness_checks, "    ")

    content = textwrap.dedent("""\
        \"\"\"Health check endpoints for Kubernetes / load-balancer probes.

        - ``/healthz``  -- Liveness: is the process alive? No dependency checks.
        - ``/readyz``   -- Readiness: can the service handle traffic?
        - ``/startupz`` -- Startup: has initialization completed?
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Request, Response
        from fastapi.responses import JSONResponse
        {extra_imports}

        _log = logging.getLogger(__name__)

        router = APIRouter(tags=["health"])


        @router.get("/healthz")
        async def liveness() -> dict:
            \"\"\"Liveness probe -- always returns 200 if the process is running.

            NO dependency checks here. If the process can respond, it is alive.
            \"\"\"
            return {{"status": "alive"}}


        @router.get("/readyz")
        async def readiness() -> Response:
            \"\"\"Readiness probe -- checks all downstream dependencies.

            Returns 200 if all dependencies are reachable, 503 otherwise.
            \"\"\"
            checks: dict[str, str] = {{}}
            healthy = True

        {readiness_checks}    if not healthy:
                return JSONResponse(
                    status_code=503,
                    content={{"status": "not_ready", "checks": checks}},
                )

            return JSONResponse(
                content={{"status": "ready", "checks": checks}},
            )


        @router.get("/startupz")
        async def startup(request: Request) -> Response:
            \"\"\"Startup probe -- verifies that application initialization completed.

            Checks whether the database engine was set on ``app.state`` during
            lifespan startup.
            \"\"\"
            engine_ready = (
                hasattr(request.app.state, "db_engine")
                and request.app.state.db_engine is not None
            )

            if not engine_ready:
                return JSONResponse(
                    status_code=503,
                    content={{"status": "starting", "detail": "Database engine not initialized"}},
                )

            return JSONResponse(content={{"status": "started"}})
    """).format(
        extra_imports=extra_import_block,
        readiness_checks=readiness_checks,
    )

    file_path = out / "health.py"
    file_path.write_text(content)

    probes = ["liveness (/healthz)", "readiness (/readyz)", "startup (/startupz)"]
    notes = [f"Generated health endpoints: {', '.join(probes)}."]
    if check_db:
        notes.append("Readiness checks database with SELECT 1.")
    if check_redis:
        notes.append("Readiness checks Redis with ping.")

    return {"files_created": [str(file_path)], "notes": notes}
