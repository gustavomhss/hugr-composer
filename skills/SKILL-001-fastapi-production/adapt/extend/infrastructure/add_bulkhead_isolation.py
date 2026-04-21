"""TOOL-097: add_bulkhead_isolation — separate semaphore pools per endpoint group.

Generates a Bulkhead with per-group semaphores, a BulkheadMiddleware that
routes requests to groups and rejects with 503 when a pool is full, a status
endpoint at GET /resilience/bulkheads, and config fields for max_concurrent
per group.

The tool is idempotent: a second run detects ``Bulkhead`` in
``app/resilience/bulkhead.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_bulkhead_isolation import add_bulkhead_isolation

    result = add_bulkhead_isolation(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/resilience/bulkhead.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_bulkhead_isolation",
    "description": (
        "Add bulkhead isolation with separate semaphore pools per endpoint group, "
        "preventing one slow endpoint from exhausting the entire service."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_bulkhead_isolation",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_bulkhead_isolation(inp: ToolInput) -> ToolResult:
    """Add bulkhead isolation pattern to a FastAPI project.

    Writes ``app/resilience/bulkhead.py``, ``app/resilience/pool_config.py``,
    ``app/middleware/bulkhead.py``, ``app/api/routes/bulkhead_status.py``,
    and patches ``app/core/config.py`` with the required env vars.

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
    bulkhead_file = app_dir / "resilience" / "bulkhead.py"
    if bulkhead_file.exists() and "Bulkhead" in bulkhead_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Bulkhead already present — bulkhead isolation already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create bulkhead.py, pool_config.py, bulkhead middleware, "
                "bulkhead_status route, and patch config.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: resilience package ------------------------------------------
    resilience_dir = app_dir / "resilience"
    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    _write_bulkhead(bulkhead_file)
    files_created.append(str(bulkhead_file))

    pool_config_file = resilience_dir / "pool_config.py"
    _write_pool_config(pool_config_file)
    files_created.append(str(pool_config_file))

    # --- Step 2: middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    mw_file = middleware_dir / "bulkhead.py"
    _write_middleware(mw_file)
    files_created.append(str(mw_file))

    # --- Step 3: status route ------------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "bulkhead_status.py"
        _write_status_route(status_route)
        files_created.append(str(status_route))

    # --- Step 4: patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- AST validation ------------------------------------------------------
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
            "Bulkhead isolation added: separate semaphore pools per endpoint group.",
            "Groups: payments (max 10), crud (max 50), analytics (max 20).",
            "BulkheadMiddleware rejects excess requests with 503 + X-Bulkhead-Group header.",
            "Status endpoint: GET /resilience/bulkheads (pool utilization per group).",
            "Config: BULKHEAD_ENABLED, BULKHEAD_PAYMENTS_MAX, BULKHEAD_CRUD_MAX, "
            "BULKHEAD_ANALYTICS_MAX.",
        ],
        next_steps=[
            "Set BULKHEAD_ENABLED=true in .env to activate.",
            "Add BulkheadMiddleware to app.add_middleware() in main.py.",
            "Include bulkhead_status router in app for /resilience/bulkheads.",
            "Tune BULKHEAD_*_MAX values to match your workload profiles.",
            "Monitor /resilience/bulkheads to identify bottleneck groups.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_bulkhead(dest: Path) -> None:
    """Write ``app/resilience/bulkhead.py`` with semaphore-based Bulkhead.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Bulkhead: separate semaphore pools per endpoint group.

        Inspired by Netflix Hystrix. Prevents one slow endpoint group from
        consuming all concurrency and taking down the entire service.

        Usage::

            bulkhead = get_bulkhead()
            async with bulkhead.acquire("payments"):
                # up to BULKHEAD_PAYMENTS_MAX concurrent requests here
                result = await call_payment_service()
        \"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import os

        from app.resilience.pool_config import BulkheadConfig, get_default_config

        logger = logging.getLogger(__name__)


        class BulkheadFullError(Exception):
            \"\"\"Raised when a bulkhead pool is at maximum concurrency.

            Args:
                group: Name of the pool that is full.
                current: Current concurrency count.
                maximum: Maximum concurrency for this group.
            \"\"\"

            def __init__(self, group: str, current: int, maximum: int) -> None:
                \"\"\"Initialise with group and capacity info.\"\"\"
                self.group = group
                self.current = current
                self.maximum = maximum
                super().__init__(
                    f"Bulkhead pool '{group}' full: {current}/{maximum} concurrent requests"
                )


        class _PoolState:
            \"\"\"Internal state for a single bulkhead pool.\"\"\"

            def __init__(self, max_concurrent: int) -> None:
                \"\"\"Initialise pool state with a semaphore.\"\"\"
                self._semaphore = asyncio.Semaphore(max_concurrent)
                self._max = max_concurrent
                self._active = 0

            async def __aenter__(self) -> "_PoolState":
                \"\"\"Acquire semaphore or raise BulkheadFullError if none available.\"\"\"
                acquired = self._semaphore._value > 0
                if not acquired:
                    raise BulkheadFullError(
                        group="unknown", current=self._max, maximum=self._max
                    )
                await self._semaphore.acquire()
                self._active += 1
                return self

            async def __aexit__(self, *_: object) -> None:
                \"\"\"Release the semaphore slot.\"\"\"
                self._semaphore.release()
                self._active = max(0, self._active - 1)

            @property
            def active(self) -> int:
                \"\"\"Current number of active concurrent requests.\"\"\"
                return self._active

            @property
            def max(self) -> int:
                \"\"\"Maximum configured concurrency for this pool.\"\"\"
                return self._max

            @property
            def available(self) -> int:
                \"\"\"Free slots available (max - active).\"\"\"
                return max(0, self._max - self._active)


        class Bulkhead:
            \"\"\"Manages separate semaphore pools per endpoint group.

            Args:
                config: BulkheadConfig specifying max_concurrent per group.
            \"\"\"

            def __init__(self, config: BulkheadConfig | None = None) -> None:
                \"\"\"Initialise Bulkhead with per-group pools from config.\"\"\"
                cfg = config or get_default_config()
                self._pools: dict[str, _PoolState] = {
                    name: _PoolState(limit)
                    for name, limit in cfg.limits.items()
                }

            def acquire(self, group: str) -> _PoolState:
                \"\"\"Return the pool context manager for *group*.

                Usage::

                    async with bulkhead.acquire("payments"):
                        result = await call_payment_service()

                Args:
                    group: Endpoint group name.

                Returns:
                    Async context manager that acquires/releases a semaphore slot.

                Raises:
                    BulkheadFullError: When the pool is at maximum concurrency.
                \"\"\"
                pool = self._pools.get(group)
                if pool is None:
                    default_limit = int(os.getenv("BULKHEAD_DEFAULT_MAX", "50"))
                    self._pools[group] = _PoolState(default_limit)
                    logger.info("Created bulkhead pool '%s' with limit %d", group, default_limit)
                    pool = self._pools[group]
                return pool

            def status(self) -> dict[str, dict[str, int]]:
                \"\"\"Return current pool utilization for all groups.

                Returns:
                    Dict mapping group name → dict with 'active', 'max', 'available'.
                \"\"\"
                return {
                    name: {
                        "active": pool.active,
                        "max": pool.max,
                        "available": pool.available,
                    }
                    for name, pool in self._pools.items()
                }


        _default_bulkhead: Bulkhead | None = None


        def get_bulkhead() -> Bulkhead:
            \"\"\"Return the process-global Bulkhead instance (lazy init).\"\"\"
            global _default_bulkhead
            if _default_bulkhead is None:
                _default_bulkhead = Bulkhead()
            return _default_bulkhead
    """))


def _write_pool_config(dest: Path) -> None:
    """Write ``app/resilience/pool_config.py`` with BulkheadConfig dataclass.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"BulkheadConfig: per-group concurrency limits read from environment.

        Groups:
            payments   — payment processing (default: 10)
            crud       — standard CRUD endpoints (default: 50)
            analytics  — analytics / reporting queries (default: 20)
        \"\"\"

        from __future__ import annotations

        import os
        from dataclasses import dataclass, field


        @dataclass
        class BulkheadConfig:
            \"\"\"Configuration for per-group concurrency limits.

            Attributes:
                limits: Dict mapping group name → max_concurrent integer.
            \"\"\"

            limits: dict[str, int] = field(default_factory=dict)

            def __post_init__(self) -> None:
                \"\"\"Validate that all limits are positive integers.\"\"\"
                for group, limit in self.limits.items():
                    if limit < 1:
                        raise ValueError(
                            f"Bulkhead limit for '{group}' must be >= 1, got {limit}"
                        )


        def get_default_config() -> BulkheadConfig:
            \"\"\"Return BulkheadConfig populated from environment variables.

            Reads:
                BULKHEAD_PAYMENTS_MAX  (default 10)
                BULKHEAD_CRUD_MAX      (default 50)
                BULKHEAD_ANALYTICS_MAX (default 20)

            Returns:
                ``BulkheadConfig`` with per-group limits.
            \"\"\"
            return BulkheadConfig(
                limits={
                    "payments": int(os.getenv("BULKHEAD_PAYMENTS_MAX", "10")),
                    "crud": int(os.getenv("BULKHEAD_CRUD_MAX", "50")),
                    "analytics": int(os.getenv("BULKHEAD_ANALYTICS_MAX", "20")),
                }
            )


        def classify_route(path: str) -> str:
            \"\"\"Map a URL path to a bulkhead group name.

            Args:
                path: URL path of the incoming request.

            Returns:
                Bulkhead group name: 'payments', 'analytics', or 'crud'.
            \"\"\"
            if path.startswith(("/payments", "/billing", "/subscriptions", "/invoices")):
                return "payments"
            if path.startswith(("/analytics", "/reports", "/exports", "/metrics")):
                return "analytics"
            return "crud"
    """))


def _write_middleware(dest: Path) -> None:
    """Write ``app/middleware/bulkhead.py`` with ASGI middleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"BulkheadMiddleware: route → group → acquire semaphore → 503 if full.

        Requests are classified into groups (payments, crud, analytics) by path.
        If the group pool is full the request is immediately rejected with 503
        and an X-Bulkhead-Group header naming the exhausted pool.
        \"\"\"

        from __future__ import annotations

        import logging
        import os

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.resilience.bulkhead import BulkheadFullError, get_bulkhead
        from app.resilience.pool_config import classify_route

        logger = logging.getLogger(__name__)


        class BulkheadMiddleware(BaseHTTPMiddleware):
            \"\"\"Middleware that isolates endpoint groups with separate semaphore pools.\"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Process the request through the appropriate bulkhead pool.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next middleware / route handler.

                Returns:
                    503 with detail if pool is full, else upstream response.
                \"\"\"
                if not _is_enabled():
                    return await call_next(request)

                group = classify_route(request.url.path)
                bulkhead = get_bulkhead()

                try:
                    async with bulkhead.acquire(group):
                        return await call_next(request)
                except BulkheadFullError as exc:
                    logger.warning(
                        "Bulkhead full for group '%s': %d/%d",
                        group, exc.current, exc.maximum,
                    )
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": (
                                f"Service unavailable: '{group}' pool at capacity. "
                                "Please retry."
                            )
                        },
                        headers={"X-Bulkhead-Group": group},
                    )


        def _is_enabled() -> bool:
            \"\"\"Return True if bulkhead isolation is enabled via environment variable.\"\"\"
            return os.getenv("BULKHEAD_ENABLED", "false").lower() == "true"
    """))


def _write_status_route(dest: Path) -> None:
    """Write ``app/api/routes/bulkhead_status.py`` with pool utilization endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"GET /resilience/bulkheads — pool utilization per bulkhead group.

        Returns current active, max, and available counts for every group
        registered in the global Bulkhead instance.
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter

        from app.resilience.bulkhead import get_bulkhead

        router = APIRouter(prefix="/resilience", tags=["resilience"])


        @router.get("/bulkheads", response_model=dict)
        async def bulkhead_status() -> dict:
            \"\"\"Return current pool utilization for all bulkhead groups.

            Returns:
                Dict mapping group name → dict with 'active', 'max', 'available'.

            Example response::

                {
                    "payments":  {"active": 2, "max": 10, "available": 8},
                    "crud":      {"active": 12, "max": 50, "available": 38},
                    "analytics": {"active": 5, "max": 20, "available": 15}
                }
            \"\"\"
            return get_bulkhead().status()
    """))


def _patch_config(config_file: Path) -> None:
    """Add BULKHEAD_* fields to ``app/core/config.py`` Settings class.

    Args:
        config_file: Path to the existing config.py.
    """
    src = config_file.read_text()
    if "BULKHEAD_ENABLED" in src:
        return

    fields = (
        "\n    # Bulkhead isolation\n"
        "    BULKHEAD_ENABLED: bool = False\n"
        "    BULKHEAD_PAYMENTS_MAX: int = 10\n"
        "    BULKHEAD_CRUD_MAX: int = 50\n"
        "    BULKHEAD_ANALYTICS_MAX: int = 20\n"
    )

    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"

    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Add BulkheadMiddleware + bulkhead_status router comment to main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "bulkhead" in src:
        return

    note = (
        "\n# Bulkhead isolation — added by add_bulkhead_isolation tool\n"
        "# from app.middleware.bulkhead import BulkheadMiddleware\n"
        "# from app.api.routes.bulkhead_status import router as bulkhead_router\n"
        "# app.add_middleware(BulkheadMiddleware)\n"
        "# app.include_router(bulkhead_router)\n"
    )
    main_file.write_text(src.rstrip("\n") + "\n" + note)


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
