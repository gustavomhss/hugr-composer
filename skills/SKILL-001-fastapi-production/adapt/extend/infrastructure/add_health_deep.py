"""TOOL-061: add_health_deep — upgrade to production-grade deep health checks.

Replaces the basic ``/healthz``, ``/readyz``, ``/startupz`` routes with a
full health-check system featuring a ``HealthRegistry``, per-dependency
latency tracking, circuit-breaker-style degraded state, and a dependency
matrix endpoint for dashboards and on-call tooling.

The tool is idempotent: a second run detects ``HealthRegistry`` in
``app/health/registry.py`` and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_health_deep import add_health_deep

    result = add_health_deep(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/health/registry.py, ...]
    print(result.next_steps)     # ["pip install psutil>=6.0.0", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_health_deep",
    "description": (
        "Upgrade to production-grade deep health checks with HealthRegistry, "
        "dependency matrix, per-check latency, circuit-breaker degraded state, "
        "and /health/live + /health/ready + /health/deep endpoints."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_health_deep",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_health_deep(inp: ToolInput) -> ToolResult:
    """Add deep health-check system to a FastAPI project.

    Writes ``app/health/`` package (registry, checks, models), a
    ``app/api/routes/health_deep.py`` router, patches ``app/core/config.py``
    with health-tuning knobs, registers the router in ``app/main.py``, and
    adds ``psutil`` to ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
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

    # --- Step 1: health package ----------------------------------------------
    health_dir = app_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)

    checks_dir = health_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    _write_health_init(health_dir / "__init__.py")
    files_created.append(str(health_dir / "__init__.py"))

    _write_health_registry(registry_file)
    files_created.append(str(registry_file))

    _write_health_models(health_dir / "models.py")
    files_created.append(str(health_dir / "models.py"))

    _write_checks_init(checks_dir / "__init__.py")
    files_created.append(str(checks_dir / "__init__.py"))

    _write_check_database(checks_dir / "database.py")
    files_created.append(str(checks_dir / "database.py"))

    _write_check_redis(checks_dir / "redis.py")
    files_created.append(str(checks_dir / "redis.py"))

    _write_check_disk(checks_dir / "disk.py")
    files_created.append(str(checks_dir / "disk.py"))

    _write_check_memory(checks_dir / "memory.py")
    files_created.append(str(checks_dir / "memory.py"))

    # --- Step 2: deep health routes ------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        deep_route = routes_dir / "health_deep.py"
        _write_health_deep_route(deep_route)
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
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_health_init(dest: Path) -> None:
    """Write ``app/health/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Deep health-check system — public API.\"\"\"

        from app.health.registry import HealthRegistry, get_registry
        from app.health.models import DependencyCheck, HealthReport, HealthStatus

        __all__ = [
            "HealthRegistry",
            "get_registry",
            "DependencyCheck",
            "HealthReport",
            "HealthStatus",
        ]
        """))


def _write_health_registry(dest: Path) -> None:
    """Write ``app/health/registry.py`` — HealthRegistry singleton.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"HealthRegistry: register async checks and run them with timeouts.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import time
        from collections.abc import Callable, Coroutine
        from typing import Any

        from app.health.models import DependencyCheck, HealthReport, HealthStatus

        logger = logging.getLogger(__name__)

        _registry: "HealthRegistry | None" = None

        _CIRCUIT_BREAKER_THRESHOLD = 3  # failures before marking degraded


        class HealthRegistry:
            \"\"\"Singleton registry for async health-check functions.

            Args:
                timeout_ms: Default per-check timeout in milliseconds.
            \"\"\"

            def __init__(self, timeout_ms: int = 5000) -> None:
                self._checks: dict[str, dict[str, Any]] = {}
                self._failure_counts: dict[str, int] = {}
                self.timeout_ms = timeout_ms

            def register_check(
                self,
                name: str,
                check_fn: Callable[[], Coroutine[Any, Any, DependencyCheck]],
                *,
                critical: bool = False,
            ) -> None:
                \"\"\"Register a named async check.

                Args:
                    name: Unique check name (e.g. 'database', 'redis').
                    check_fn: Async callable returning a DependencyCheck.
                    critical: When True, failure blocks readiness probe.
                \"\"\"
                self._checks[name] = {"fn": check_fn, "critical": critical}
                self._failure_counts.setdefault(name, 0)

            async def _run_one(self, name: str) -> DependencyCheck:
                \"\"\"Execute a single check with timeout and circuit-breaker logic.

                Args:
                    name: Registered check name.

                Returns:
                    DependencyCheck with status/latency/details.
                \"\"\"
                entry = self._checks[name]
                t0 = time.monotonic()
                try:
                    result: DependencyCheck = await asyncio.wait_for(
                        entry["fn"](),
                        timeout=self.timeout_ms / 1000,
                    )
                    self._failure_counts[name] = 0
                    return result
                except asyncio.TimeoutError:
                    self._failure_counts[name] += 1
                    lat = int((time.monotonic() - t0) * 1000)
                    logger.warning("Health check '%s' timed out after %d ms", name, lat)
                    status = self._circuit_status(name)
                    return DependencyCheck(
                        name=name, status=status, latency_ms=lat,
                        details={"error": "timeout"},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._failure_counts[name] += 1
                    lat = int((time.monotonic() - t0) * 1000)
                    logger.warning("Health check '%s' raised: %s", name, exc, exc_info=True)
                    status = self._circuit_status(name)
                    return DependencyCheck(
                        name=name, status=status, latency_ms=lat,
                        details={"error": str(exc)},
                    )

            def _circuit_status(self, name: str) -> HealthStatus:
                \"\"\"Return 'degraded' after threshold, else 'unhealthy'.

                Args:
                    name: Check name to inspect.
                \"\"\"
                if self._failure_counts.get(name, 0) >= _CIRCUIT_BREAKER_THRESHOLD:
                    return HealthStatus.DEGRADED
                return HealthStatus.UNHEALTHY

            async def run_all(self) -> HealthReport:
                \"\"\"Run every registered check and return a full HealthReport.\"\"\"
                results = await asyncio.gather(
                    *[self._run_one(n) for n in self._checks],
                    return_exceptions=False,
                )
                checks = list(results)
                overall = _aggregate_status(checks)
                return HealthReport(status=overall, checks=checks)

            async def run_readiness(self) -> HealthReport:
                \"\"\"Run only critical checks (for /health/ready probe).\"\"\"
                names = [n for n, e in self._checks.items() if e["critical"]]
                results = await asyncio.gather(
                    *[self._run_one(n) for n in names],
                    return_exceptions=False,
                )
                checks = list(results)
                overall = _aggregate_status(checks)
                return HealthReport(status=overall, checks=checks)

            async def run_liveness(self) -> HealthReport:
                \"\"\"Liveness check — always healthy unless process is stuck.\"\"\"
                return HealthReport(status=HealthStatus.HEALTHY, checks=[])


        def _aggregate_status(checks: list[DependencyCheck]) -> HealthStatus:
            \"\"\"Derive overall status from individual check results.\"\"\"
            statuses = {c.status for c in checks}
            if HealthStatus.UNHEALTHY in statuses:
                return HealthStatus.UNHEALTHY
            if HealthStatus.DEGRADED in statuses:
                return HealthStatus.DEGRADED
            return HealthStatus.HEALTHY


        def get_registry() -> HealthRegistry:
            \"\"\"Return the process-wide HealthRegistry singleton.\"\"\"
            global _registry
            if _registry is None:
                _registry = HealthRegistry()
            return _registry
        """))


def _write_health_models(dest: Path) -> None:
    """Write ``app/health/models.py`` — Pydantic models for health responses.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic models for health-check API responses.\"\"\"

        from __future__ import annotations

        from typing import Any

        from pydantic import BaseModel, Field


        class HealthStatus(str):
            \"\"\"Health check status values.\"\"\"

            HEALTHY = "healthy"
            DEGRADED = "degraded"
            UNHEALTHY = "unhealthy"


        class DependencyCheck(BaseModel):
            \"\"\"Result of a single dependency health check.

            Attributes:
                name: Dependency name (e.g. 'database', 'redis').
                status: One of 'healthy', 'degraded', 'unhealthy'.
                latency_ms: Round-trip time in milliseconds.
                details: Optional key/value metadata (pool stats, memory, etc.).
            \"\"\"

            name: str
            status: str = HealthStatus.HEALTHY
            latency_ms: int = 0
            details: dict[str, Any] = Field(default_factory=dict)


        class HealthReport(BaseModel):
            \"\"\"Aggregated health report returned by /health endpoints.

            Attributes:
                status: Worst-case status across all checks.
                checks: Ordered list of individual DependencyCheck results.
            \"\"\"

            status: str = HealthStatus.HEALTHY
            checks: list[DependencyCheck] = Field(default_factory=list)
        """))


def _write_checks_init(dest: Path) -> None:
    """Write ``app/health/checks/__init__.py``.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Built-in health check functions.\"\"\"

        from app.health.checks.database import database_check
        from app.health.checks.disk import disk_check
        from app.health.checks.memory import memory_check
        from app.health.checks.redis import redis_check

        __all__ = ["database_check", "redis_check", "disk_check", "memory_check"]
        """))


def _write_check_database(dest: Path) -> None:
    """Write ``app/health/checks/database.py`` — PostgreSQL pool health.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"PostgreSQL connectivity + connection pool stats check.\"\"\"

        from __future__ import annotations

        import logging
        import time

        from app.health.models import DependencyCheck, HealthStatus

        logger = logging.getLogger(__name__)


        async def database_check() -> DependencyCheck:
            \"\"\"Check PostgreSQL connectivity and pool utilisation.

            Executes ``SELECT 1`` and collects active/idle/overflow counts
            from the SQLAlchemy async engine pool.

            Returns:
                DependencyCheck with pool stats in ``details``.
            \"\"\"
            t0 = time.monotonic()
            try:
                from app.core.db import engine  # deferred to avoid import cycles

                async with engine.connect() as conn:
                    await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

                pool = engine.pool
                details: dict = {
                    "pool_size": getattr(pool, "size", lambda: 0)(),
                    "checked_out": getattr(pool, "checkedout", lambda: 0)(),
                    "overflow": getattr(pool, "overflow", lambda: 0)(),
                    "checked_in": getattr(pool, "checkedin", lambda: 0)(),
                }
                latency = int((time.monotonic() - t0) * 1000)
                return DependencyCheck(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    details=details,
                )
            except Exception as exc:  # noqa: BLE001
                latency = int((time.monotonic() - t0) * 1000)
                logger.warning("Database health check failed: %s", exc)
                return DependencyCheck(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    details={"error": str(exc)},
                )
        """))


def _write_check_redis(dest: Path) -> None:
    """Write ``app/health/checks/redis.py`` — Redis ping + memory stats.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Redis ping, memory usage, and connected-clients health check.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import time

        from app.health.models import DependencyCheck, HealthStatus

        logger = logging.getLogger(__name__)


        async def redis_check() -> DependencyCheck:
            \"\"\"Ping Redis and collect memory + client stats.

            Returns:
                DependencyCheck with ``used_memory_human``, ``connected_clients``,
                and ``redis_version`` in ``details``.
            \"\"\"
            t0 = time.monotonic()
            try:
                from redis.asyncio import Redis  # deferred import

                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                client = Redis.from_url(redis_url, decode_responses=True)
                try:
                    await client.ping()
                    info = await client.info("server")
                    mem_info = await client.info("memory")
                    client_info = await client.info("clients")
                    details = {
                        "redis_version": info.get("redis_version", "unknown"),
                        "used_memory_human": mem_info.get("used_memory_human", "N/A"),
                        "connected_clients": client_info.get("connected_clients", 0),
                    }
                finally:
                    await client.aclose()

                latency = int((time.monotonic() - t0) * 1000)
                return DependencyCheck(
                    name="redis",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    details=details,
                )
            except Exception as exc:  # noqa: BLE001
                latency = int((time.monotonic() - t0) * 1000)
                logger.warning("Redis health check failed: %s", exc)
                return DependencyCheck(
                    name="redis",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    details={"error": str(exc)},
                )
        """))


def _write_check_disk(dest: Path) -> None:
    """Write ``app/health/checks/disk.py`` — disk space check via psutil.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Disk space health check using psutil.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import time

        from app.health.models import DependencyCheck, HealthStatus

        logger = logging.getLogger(__name__)


        async def disk_check() -> DependencyCheck:
            \"\"\"Check available disk space against a configured threshold.

            Uses ``psutil.disk_usage`` on the filesystem root.  Marks check as
            ``unhealthy`` when used percentage exceeds
            ``HEALTH_DISK_THRESHOLD_PCT`` (default 90 %).

            Returns:
                DependencyCheck with ``total_gb``, ``used_pct``, and ``free_gb``
                in ``details``.
            \"\"\"
            t0 = time.monotonic()
            try:
                import psutil  # noqa: PLC0415

                threshold = int(os.getenv("HEALTH_DISK_THRESHOLD_PCT", "90"))
                usage = psutil.disk_usage("/")
                used_pct = usage.percent
                details = {
                    "total_gb": round(usage.total / 1_073_741_824, 2),
                    "used_pct": used_pct,
                    "free_gb": round(usage.free / 1_073_741_824, 2),
                    "threshold_pct": threshold,
                }
                status = HealthStatus.UNHEALTHY if used_pct >= threshold else HealthStatus.HEALTHY
                latency = int((time.monotonic() - t0) * 1000)
                return DependencyCheck(
                    name="disk",
                    status=status,
                    latency_ms=latency,
                    details=details,
                )
            except Exception as exc:  # noqa: BLE001
                latency = int((time.monotonic() - t0) * 1000)
                logger.warning("Disk health check failed: %s", exc)
                return DependencyCheck(
                    name="disk",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    details={"error": str(exc)},
                )
        """))


def _write_check_memory(dest: Path) -> None:
    """Write ``app/health/checks/memory.py`` — process RSS check via psutil.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Process memory (RSS) health check using psutil.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import time

        from app.health.models import DependencyCheck, HealthStatus

        logger = logging.getLogger(__name__)


        async def memory_check() -> DependencyCheck:
            \"\"\"Check process RSS against a configured threshold.

            Marks check as ``unhealthy`` when RSS exceeds
            ``HEALTH_MEMORY_THRESHOLD_MB`` (default 512 MB).

            Returns:
                DependencyCheck with ``rss_mb``, ``vms_mb``, and
                ``threshold_mb`` in ``details``.
            \"\"\"
            t0 = time.monotonic()
            try:
                import os as _os

                import psutil  # noqa: PLC0415

                threshold_mb = int(_os.getenv("HEALTH_MEMORY_THRESHOLD_MB", "512"))
                proc = psutil.Process()
                mem = proc.memory_info()
                rss_mb = round(mem.rss / 1_048_576, 2)
                vms_mb = round(mem.vms / 1_048_576, 2)
                details = {
                    "rss_mb": rss_mb,
                    "vms_mb": vms_mb,
                    "threshold_mb": threshold_mb,
                }
                status = (
                    HealthStatus.UNHEALTHY if rss_mb >= threshold_mb else HealthStatus.HEALTHY
                )
                latency = int((time.monotonic() - t0) * 1000)
                return DependencyCheck(
                    name="memory",
                    status=status,
                    latency_ms=latency,
                    details=details,
                )
            except Exception as exc:  # noqa: BLE001
                latency = int((time.monotonic() - t0) * 1000)
                logger.warning("Memory health check failed: %s", exc)
                return DependencyCheck(
                    name="memory",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    details={"error": str(exc)},
                )
        """))


def _write_health_deep_route(dest: Path) -> None:
    """Write ``app/api/routes/health_deep.py`` — 3 health endpoints.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Deep health endpoints: /health/live, /health/ready, /health/deep.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, Response

        from app.health.models import HealthReport, HealthStatus
        from app.health.registry import get_registry

        router = APIRouter(prefix="/health", tags=["health"])


        @router.get("/live", response_model=HealthReport, summary="Liveness probe")
        async def liveness() -> HealthReport:
            \"\"\"Liveness probe — always 200 unless the process is stuck.

            Kubernetes should restart the pod only when this returns 5xx,
            which happens only if the event loop itself is blocked.

            Returns:
                HealthReport with ``status='healthy'`` and no checks.
            \"\"\"
            registry = get_registry()
            return await registry.run_liveness()


        @router.get("/ready", response_model=HealthReport, summary="Readiness probe")
        async def readiness(response: Response) -> HealthReport:
            \"\"\"Readiness probe — checks all critical dependencies.

            Returns 503 when any critical check is unhealthy or degraded,
            preventing traffic routing until the dependency recovers.

            Args:
                response: FastAPI Response for setting status code.

            Returns:
                HealthReport with results for all critical checks only.
            \"\"\"
            registry = get_registry()
            report = await registry.run_readiness()
            if report.status != HealthStatus.HEALTHY:
                response.status_code = 503
            return report


        @router.get("/deep", response_model=HealthReport, summary="Full dependency matrix")
        async def deep_check(response: Response) -> HealthReport:
            \"\"\"Full dependency matrix — all checks with per-check latency.

            Intended for dashboards, on-call tooling, and manual debugging.
            Returns 503 if any check is unhealthy.

            Args:
                response: FastAPI Response for setting status code.

            Returns:
                HealthReport with all dependency results and latencies.
            \"\"\"
            registry = get_registry()
            report = await registry.run_all()
            if report.status == HealthStatus.UNHEALTHY:
                response.status_code = 503
            return report
        """))


def _patch_config(config_file: Path) -> None:
    """Inject health-tuning settings into app/core/config.py.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "HEALTH_CHECK_TIMEOUT_MS" in src:
        return

    health_fields = textwrap.dedent("""\

        # Health check tuning — added by add_health_deep tool
        HEALTH_CHECK_TIMEOUT_MS: int = 5000
        HEALTH_DISK_THRESHOLD_PCT: int = 90
        HEALTH_MEMORY_THRESHOLD_MB: int = 512
    """)

    # Insert before the closing of the Settings class or at the end of the class body
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", health_fields + "\n\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + health_fields
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register health_deep router in app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "health_deep" in src:
        return

    health_import = (
        "\nfrom app.api.routes.health_deep import router as health_deep_router"
        "  # noqa: E402 — deep health\n"
    )
    health_register = textwrap.dedent("""\

        # Deep health checks — added by add_health_deep tool
        app.include_router(health_deep_router)
    """)

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
