"""TOOL-099: add_chaos_testing — fault injection for dev/staging environments.

Generates ``app/chaos/__init__.py`` (ChaosEngine), ``app/chaos/injectors.py``
(LatencyInjector, ErrorInjector, TimeoutInjector), ``app/chaos/middleware.py``
(ChaosMiddleware — ONLY active when ``CHAOS_ENABLED=true`` and
``ENVIRONMENT != "production"``), and ``app/api/routes/chaos.py``
(POST /chaos/enable, POST /chaos/disable, GET /chaos/status).

The production guard is hardcoded: chaos **cannot** be enabled when
``ENVIRONMENT == "production"``, regardless of ``CHAOS_ENABLED``.

The tool is idempotent: a second run detects ``ChaosEngine`` in
``app/chaos/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_chaos_testing import add_chaos_testing

    result = add_chaos_testing(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/chaos/__init__.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_chaos_testing",
    "description": (
        "Add chaos engineering fault injection for dev/staging. "
        "Hardcoded guard: NEVER active in production (ENVIRONMENT=production)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_chaos_testing",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_chaos_testing(inp: ToolInput) -> ToolResult:
    """Add chaos testing fault injection to a FastAPI project.

    Writes ``app/chaos/__init__.py``, ``app/chaos/injectors.py``,
    ``app/chaos/middleware.py``, ``app/api/routes/chaos.py``, patches
    ``app/core/config.py`` with ``CHAOS_*`` settings, and registers the
    middleware and router in ``app/main.py``.

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

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    chaos_init = app_dir / "chaos" / "__init__.py"
    if chaos_init.exists() and "ChaosEngine" in chaos_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["ChaosEngine already present — chaos testing already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/chaos/__init__.py, injectors.py, "
                "middleware.py, and app/api/routes/chaos.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: chaos package -----------------------------------------------
    chaos_dir = app_dir / "chaos"
    chaos_dir.mkdir(parents=True, exist_ok=True)

    _write_chaos_engine(chaos_init)
    files_created.append(str(chaos_init))

    # --- Step 2: injectors ---------------------------------------------------
    injectors_file = chaos_dir / "injectors.py"
    _write_chaos_injectors(injectors_file)
    files_created.append(str(injectors_file))

    # --- Step 3: middleware ---------------------------------------------------
    middleware_file = chaos_dir / "middleware.py"
    _write_chaos_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 4: routes ------------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        chaos_route = routes_dir / "chaos.py"
        _write_chaos_routes(chaos_route)
        files_created.append(str(chaos_route))

    # --- Step 5: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 6: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- ast.parse validation ------------------------------------------------
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
            "Chaos testing added: LatencyInjector, ErrorInjector, TimeoutInjector.",
            "PRODUCTION GUARD: chaos is physically blocked when ENVIRONMENT=production.",
            "ChaosMiddleware only activates when CHAOS_ENABLED=true AND not production.",
            "Endpoints: POST /chaos/enable, POST /chaos/disable, GET /chaos/status.",
            "Config: CHAOS_ENABLED (default false), CHAOS_LATENCY_MS, CHAOS_ERROR_RATE.",
        ],
        next_steps=[
            "Set CHAOS_ENABLED=true in .env for dev/staging ONLY.",
            "Set CHAOS_LATENCY_MS=200 to inject 200ms latency.",
            "Set CHAOS_ERROR_RATE=0.1 for 10% random 500 errors.",
            "Set CHAOS_TIMEOUT_RATE=0.05 for 5% request timeouts.",
            "POST /chaos/enable to activate (blocked in production).",
            "POST /chaos/disable to deactivate.",
            "Wire ChaosMiddleware into app.add_middleware() in main.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_chaos_engine(dest: Path) -> None:
    """Write ``app/chaos/__init__.py`` with ChaosEngine.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Chaos engineering engine — fault injection for dev/staging.

        PRODUCTION GUARD: chaos is physically blocked when
        ``ENVIRONMENT == \"production\"``. The guard is hardcoded and cannot
        be bypassed via configuration.

        Usage::

            engine = get_chaos_engine()
            engine.enable()
            # All requests now subject to injected faults
        \"\"\"

        from __future__ import annotations

        import logging
        import os

        logger = logging.getLogger(__name__)

        _engine: "ChaosEngine | None" = None


        class ChaosEngine:
            \"\"\"Central registry for chaos injectors.

            Args:
                latency_ms: Extra latency to inject (milliseconds).
                error_rate: Fraction of requests to fail with 500 (0.0–1.0).
                timeout_rate: Fraction of requests to hang until timeout (0.0–1.0).
            \"\"\"

            def __init__(
                self,
                latency_ms: int = 0,
                error_rate: float = 0.0,
                timeout_rate: float = 0.0,
            ) -> None:
                \"\"\"Initialise chaos engine with given injection parameters.

                Args:
                    latency_ms: Milliseconds of extra latency per request.
                    error_rate: Fraction of requests that receive a 500 error.
                    timeout_rate: Fraction of requests that are timed out.
                \"\"\"
                self.latency_ms = latency_ms
                self.error_rate = error_rate
                self.timeout_rate = timeout_rate
                self._enabled = False

            def enable(self) -> None:
                \"\"\"Enable fault injection (blocked in production).\"\"\"
                env = os.getenv("ENVIRONMENT", "local")
                if env == "production":
                    logger.error(
                        "CHAOS BLOCKED: cannot enable chaos in production environment."
                    )
                    return
                self._enabled = True
                logger.warning(
                    "Chaos enabled: latency=%dms, error_rate=%.2f, timeout_rate=%.2f",
                    self.latency_ms,
                    self.error_rate,
                    self.timeout_rate,
                )

            def disable(self) -> None:
                \"\"\"Disable all fault injection.\"\"\"
                self._enabled = False
                logger.info("Chaos disabled.")

            def is_enabled(self) -> bool:
                \"\"\"Return True if chaos is active (and not in production).

                Returns:
                    ``True`` when chaos is enabled and environment is not production.
                \"\"\"
                if os.getenv("ENVIRONMENT", "local") == "production":
                    return False
                return self._enabled

            def status(self) -> dict:
                \"\"\"Return the current chaos configuration as a dict.

                Returns:
                    Dict with keys: enabled, environment, latency_ms,
                    error_rate, timeout_rate.
                \"\"\"
                return {
                    "enabled": self.is_enabled(),
                    "environment": os.getenv("ENVIRONMENT", "local"),
                    "latency_ms": self.latency_ms,
                    "error_rate": self.error_rate,
                    "timeout_rate": self.timeout_rate,
                }


        def get_chaos_engine() -> ChaosEngine:
            \"\"\"Return the global ChaosEngine instance, creating it on first call.

            Reads ``CHAOS_LATENCY_MS``, ``CHAOS_ERROR_RATE``, and
            ``CHAOS_TIMEOUT_RATE`` from the environment for initial configuration.

            Returns:
                The singleton ``ChaosEngine`` instance.
            \"\"\"
            global _engine
            if _engine is None:
                _engine = ChaosEngine(
                    latency_ms=int(os.getenv("CHAOS_LATENCY_MS", "0")),
                    error_rate=float(os.getenv("CHAOS_ERROR_RATE", "0.0")),
                    timeout_rate=float(os.getenv("CHAOS_TIMEOUT_RATE", "0.0")),
                )
                if os.getenv("CHAOS_ENABLED", "false").lower() == "true":
                    _engine.enable()
            return _engine
    """))


def _write_chaos_injectors(dest: Path) -> None:
    """Write ``app/chaos/injectors.py`` with fault injector classes.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Fault injector implementations for chaos testing.

        Injectors:
            LatencyInjector  — sleep for a configured duration
            ErrorInjector    — randomly raise HTTP 500
            TimeoutInjector  — sleep long enough to trigger upstream timeouts
        \"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import random

        from fastapi import HTTPException

        logger = logging.getLogger(__name__)


        class LatencyInjector:
            \"\"\"Inject artificial latency into requests.

            Args:
                latency_ms: Milliseconds of extra delay to add.
            \"\"\"

            def __init__(self, latency_ms: int = 200) -> None:
                \"\"\"Initialise with a fixed latency value.

                Args:
                    latency_ms: Delay in milliseconds.
                \"\"\"
                self.latency_ms = latency_ms

            async def inject(self) -> None:
                \"\"\"Sleep for the configured latency duration.\"\"\"
                if self.latency_ms > 0:
                    logger.debug("Chaos: injecting %dms latency", self.latency_ms)
                    await asyncio.sleep(self.latency_ms / 1000.0)


        class ErrorInjector:
            \"\"\"Randomly inject HTTP 500 errors.

            Args:
                error_rate: Probability (0.0–1.0) of injecting an error.
            \"\"\"

            def __init__(self, error_rate: float = 0.1) -> None:
                \"\"\"Initialise with an error probability.

                Args:
                    error_rate: Fraction of calls that result in a 500.
                \"\"\"
                self.error_rate = error_rate

            def inject(self) -> None:
                \"\"\"Raise HTTPException(500) at the configured rate.

                Raises:
                    HTTPException: With status 500 when randomly triggered.
                \"\"\"
                if random.random() < self.error_rate:
                    logger.debug("Chaos: injecting 500 error (rate=%.2f)", self.error_rate)
                    raise HTTPException(
                        status_code=500,
                        detail="Chaos fault injection — simulated server error",
                    )


        class TimeoutInjector:
            \"\"\"Simulate a hung request to trigger upstream timeouts.

            Args:
                timeout_rate: Probability (0.0–1.0) of injecting a hang.
                hang_seconds: How long to hang (default 35s — exceeds common 30s timeouts).
            \"\"\"

            def __init__(
                self, timeout_rate: float = 0.05, hang_seconds: float = 35.0
            ) -> None:
                \"\"\"Initialise with a hang probability and duration.

                Args:
                    timeout_rate: Fraction of calls that get a hang injected.
                    hang_seconds: Duration in seconds for the simulated hang.
                \"\"\"
                self.timeout_rate = timeout_rate
                self.hang_seconds = hang_seconds

            async def inject(self) -> None:
                \"\"\"Sleep for hang_seconds at the configured rate.\"\"\"
                if random.random() < self.timeout_rate:
                    logger.debug(
                        "Chaos: injecting timeout hang (%.1fs)", self.hang_seconds
                    )
                    await asyncio.sleep(self.hang_seconds)
    """))


def _write_chaos_middleware(dest: Path) -> None:
    """Write ``app/chaos/middleware.py`` with ChaosMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"ASGI middleware that applies chaos fault injection.

        PRODUCTION GUARD: The middleware is completely inert when
        ``ENVIRONMENT == \"production\"`` — it passes every request through
        unchanged regardless of the ``CHAOS_ENABLED`` setting.
        \"\"\"

        from __future__ import annotations

        import os

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.chaos import get_chaos_engine
        from app.chaos.injectors import ErrorInjector, LatencyInjector, TimeoutInjector


        class ChaosMiddleware(BaseHTTPMiddleware):
            \"\"\"Apply chaos fault injection to incoming requests.

            Only active when chaos engine reports ``is_enabled() == True``.
            Never active in production (hardcoded guard in ChaosEngine).

            Args:
                app: ASGI application to wrap.
            \"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Apply chaos faults then forward the request.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware / route handler.

                Returns:
                    Response from downstream, possibly after injected faults.
                \"\"\"
                engine = get_chaos_engine()
                if not engine.is_enabled():
                    return await call_next(request)

                # Skip chaos on health and chaos management endpoints
                path = request.url.path
                if path in ("/healthz", "/chaos/status", "/chaos/enable", "/chaos/disable"):
                    return await call_next(request)

                latency_inj = LatencyInjector(latency_ms=engine.latency_ms)
                error_inj = ErrorInjector(error_rate=engine.error_rate)
                timeout_inj = TimeoutInjector(timeout_rate=engine.timeout_rate)

                await latency_inj.inject()
                error_inj.inject()
                await timeout_inj.inject()

                return await call_next(request)
    """))


def _write_chaos_routes(dest: Path) -> None:
    """Write ``app/api/routes/chaos.py`` with enable/disable/status endpoints.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Chaos engineering control endpoints.

        Endpoints:
            POST /chaos/enable   — enable fault injection (dev/staging only)
            POST /chaos/disable  — disable fault injection
            GET  /chaos/status   — current chaos configuration
        \"\"\"

        from __future__ import annotations

        import os

        from fastapi import APIRouter, HTTPException

        from app.chaos import get_chaos_engine

        router = APIRouter(prefix="/chaos", tags=["chaos"])


        @router.post("/enable", response_model=dict)
        async def enable_chaos() -> dict:
            \"\"\"Enable chaos fault injection.

            Blocked when ``ENVIRONMENT == \"production\"``.

            Returns:
                Confirmation dict with current chaos status.

            Raises:
                HTTPException: 403 when called in production environment.
            \"\"\"
            if os.getenv("ENVIRONMENT", "local") == "production":
                raise HTTPException(
                    status_code=403,
                    detail="Chaos testing cannot be enabled in production.",
                )
            engine = get_chaos_engine()
            engine.enable()
            return engine.status()


        @router.post("/disable", response_model=dict)
        async def disable_chaos() -> dict:
            \"\"\"Disable chaos fault injection.

            Returns:
                Confirmation dict with current chaos status.
            \"\"\"
            engine = get_chaos_engine()
            engine.disable()
            return engine.status()


        @router.get("/status", response_model=dict)
        async def chaos_status() -> dict:
            \"\"\"Return the current chaos engine configuration.

            Returns:
                Dict with keys: enabled, environment, latency_ms,
                error_rate, timeout_rate.
            \"\"\"
            return get_chaos_engine().status()
    """))


def _patch_config(config_file: Path) -> None:
    """Inject CHAOS_* settings into app/core/config.py Settings class.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "CHAOS_ENABLED" in src:
        return
    fields = (
        "\n    # Chaos testing (TOOL-099) — NEVER enable in production\n"
        "    CHAOS_ENABLED: bool = False\n"
        "    CHAOS_LATENCY_MS: int = 0\n"
        "    CHAOS_ERROR_RATE: float = 0.0\n"
        "    CHAOS_TIMEOUT_RATE: float = 0.0\n"
    )
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject chaos middleware and router into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "ChaosMiddleware" in src:
        return

    import_snippet = (
        "\nfrom app.chaos.middleware import ChaosMiddleware"
        "  # noqa: F401 — chaos fault injection\n"
        "from app.api.routes.chaos import router as _chaos_router"
        "  # noqa: F401 — chaos endpoints\n"
    )
    wire_snippet = (
        "\n# Chaos testing middleware + router — added by add_chaos_testing tool\n"
        "app.add_middleware(ChaosMiddleware)\n"
        "app.include_router(_chaos_router)\n"
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_snippet,
        )
    else:
        src = import_snippet + src

    src = src.rstrip("\n") + "\n" + wire_snippet
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
