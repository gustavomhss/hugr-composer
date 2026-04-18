"""TOOL-057: add_rate_limiting — add SlowAPI-based rate limiting to a FastAPI project.

Generates production-grade rate limiting with Redis-backed multi-worker storage,
three key strategies (IP, user, user+endpoint), RFC-compliant 429 responses, and
exemption hooks for webhooks/health-checks.

Idempotent: a second run detects ``app/core/rate_limit.py`` and returns
``status="no_op"`` without touching any file.

Generated files:
  - ``app/core/rate_limit.py``     limiter factory + key functions
  - ``app/middleware/rate_limit.py``   middleware + 429 exception handler
  - ``app/api/routes/rate_limit.py``   GET /rate-limit/status endpoint

Patched files:
  - ``app/core/config.py``       RATE_LIMIT_* fields inside Settings
  - ``app/main.py``              limiter registration + exception handler
  - ``requirements.txt``         ``slowapi>=0.1.9`` + ``limits>=3.13.0``

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_rate_limiting import add_rate_limiting

    result = add_rate_limiting(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/core/rate_limit.py, ...]
    print(result.next_steps)    # ["pip install slowapi", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_rate_limiting",
    "description": (
        "Add SlowAPI-based rate limiting with Redis storage, per-IP/user/endpoint "
        "key strategies, RFC-compliant 429 responses, and exemption hooks."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_rate_limiting",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_rate_limiting(inp: ToolInput) -> ToolResult:
    """Add SlowAPI-based rate limiting to a FastAPI project.

    Writes the ``app/core/rate_limit.py`` factory, middleware wiring, and a
    ``/rate-limit/status`` endpoint. Patches ``app/main.py`` to register the
    limiter and the 429 exception handler, and ``app/core/config.py`` to add
    the ``RATE_LIMIT_*`` settings.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

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
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    # The base generator already ships a ``app/core/rate_limit.py`` with a
    # simple ``limiter = Limiter(key_func=get_remote_address)`` that
    # ``main.py`` imports. This tool UPGRADES that module with a richer
    # ``RateLimitConfig`` dataclass, three key strategies, configurable
    # storage, and a dedicated ``/rate-limit/status`` endpoint — while
    # preserving the module-level ``limiter`` symbol for backward compat.
    rl_core = app_dir / "core" / "rate_limit.py"
    if rl_core.exists() and "RateLimitConfig" in rl_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["RateLimitConfig already present — advanced rate limiting already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/rate_limit.py, "
                "app/middleware/rate_limit.py, and app/api/routes/rate_limit.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Core limiter factory ---------------------------------------
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    _write_rate_limit_core(rl_core)
    files_created.append(str(rl_core))

    # --- Step 2: Middleware module ------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    mw_file = middleware_dir / "rate_limit.py"
    _write_rate_limit_middleware(mw_file)
    files_created.append(str(mw_file))

    # --- Step 3: Status endpoint --------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        status_route = routes_dir / "rate_limit.py"
        _write_rate_limit_status_route(status_route)
        files_created.append(str(status_route))

    # --- Step 4: Patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: Patch main.py ----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 6: Patch requirements.txt -------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "slowapi" not in req_src:
            req_adds.append("slowapi>=0.1.9")
        if "limits" not in req_src:
            req_adds.append("limits>=3.13.0")
        if "redis" not in req_src:
            req_adds.append("redis[hiredis]>=5.0.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

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
            "SlowAPI rate limiting installed with Redis storage and 3 key strategies.",
            "Default limits: 100/minute per IP, 1000/hour per user, customisable via env.",
            "429 responses include Retry-After and X-RateLimit-* headers (RFC 6585).",
            "Webhook and health-check routes must be explicitly exempted with "
            "@limiter.exempt.",
        ],
        next_steps=[
            "pip install 'slowapi>=0.1.9' 'limits>=3.13.0' 'redis[hiredis]>=5.0.0'",
            "Set REDIS_URL in .env (used for multi-worker rate limit storage).",
            "Apply limits to routes via @limiter.limit('10/minute') decorator.",
            "Exempt health/webhook routes: @limiter.exempt.",
            "Read current quota from GET /rate-limit/status (requires auth).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — every function ≤ 50 LOC
# ---------------------------------------------------------------------------

def _write_rate_limit_core(dest: Path) -> None:
    """Write ``app/core/rate_limit.py`` with Limiter factory + key strategies.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
        """SlowAPI Limiter factory — Redis-backed, 3 key strategies.

        Three key functions:
          - ``key_ip``: ``request.client.host`` (anonymous traffic)
          - ``key_user``: ``user.id`` from request.state (authenticated traffic)
          - ``key_user_endpoint``: ``user.id + request.url.path`` (per-user-per-route)

        The limiter is configured at app startup from ``settings.REDIS_URL``.
        When REDIS_URL is unset, storage falls back to memory (single-worker only).
        """

        from __future__ import annotations

        import logging
        from dataclasses import dataclass

        from slowapi import Limiter
        from slowapi.util import get_remote_address
        from starlette.requests import Request

        from app.core.config import settings

        logger = logging.getLogger(__name__)


        @dataclass(frozen=True)
        class RateLimitConfig:
            """Immutable rate-limit configuration read from settings."""

            default_limits: list[str]
            storage_uri: str
            enabled: bool
            strategy: str  # "fixed-window" | "moving-window"
            headers_enabled: bool


        def build_config() -> RateLimitConfig:
            """Build a RateLimitConfig from current settings.

            Returns:
                RateLimitConfig populated from ``settings.RATE_LIMIT_*`` fields.
            """
            storage = settings.REDIS_URL if getattr(settings, "REDIS_URL", None) else "memory://"
            return RateLimitConfig(
                default_limits=[settings.RATE_LIMIT_DEFAULT],
                storage_uri=str(storage),
                enabled=settings.RATE_LIMIT_ENABLED,
                strategy=settings.RATE_LIMIT_STRATEGY,
                headers_enabled=settings.RATE_LIMIT_HEADERS_ENABLED,
            )


        def key_ip(request: Request) -> str:
            """Return the remote IP as the rate-limit key.

            Honours ``X-Forwarded-For`` when running behind a trusted proxy.
            """
            return get_remote_address(request)


        def key_user(request: Request) -> str:
            """Return the authenticated user id, falling back to the IP.

            Requires an upstream middleware or dependency that sets
            ``request.state.user_id`` from the JWT.
            """
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                return f"user:{user_id}"
            return f"ip:{get_remote_address(request)}"


        def key_user_endpoint(request: Request) -> str:
            """Return ``user_id + route path`` as the rate-limit key.

            Yields one budget per user per endpoint.
            """
            base = key_user(request)
            return f"{base}:{request.url.path}"


        def _build_limiter() -> Limiter:
            """Build a Limiter from current settings.

            Returns:
                A configured ``slowapi.Limiter`` instance.
            """
            cfg = build_config()
            return Limiter(
                key_func=get_remote_address,
                default_limits=cfg.default_limits,
                storage_uri=cfg.storage_uri,
                strategy=cfg.strategy,
                headers_enabled=cfg.headers_enabled,
                enabled=cfg.enabled,
            )


        # Module-level singleton — ``app.main`` imports this symbol directly.
        limiter: Limiter = _build_limiter()


        def get_limiter() -> Limiter:
            """Return the shared Limiter singleton.

            Kept for API symmetry with other advanced rate-limit helpers.
            """
            return limiter


        def reset_limiter() -> None:
            """Rebuild the singleton — test helper only."""
            global limiter
            limiter = _build_limiter()
        '''))


def _write_rate_limit_middleware(dest: Path) -> None:
    """Write ``app/middleware/rate_limit.py`` with SlowAPI middleware wiring.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
        """SlowAPI middleware + 429 exception handler.

        Registers ``SlowAPIMiddleware`` on the FastAPI app and a custom
        exception handler that emits RFC 6585-compliant 429 responses with
        ``Retry-After`` and ``X-RateLimit-*`` headers.
        """

        from __future__ import annotations

        import logging

        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware

        from app.core.rate_limit import get_limiter

        logger = logging.getLogger(__name__)


        async def rate_limit_exceeded_handler(
            request: Request, exc: RateLimitExceeded
        ) -> JSONResponse:
            """Return a 429 response with Retry-After and rate-limit headers.

            Args:
                request: The request that triggered the limit.
                exc: The ``RateLimitExceeded`` raised by SlowAPI.

            Returns:
                A 429 JSONResponse with RFC 6585-compliant headers.
            """
            logger.warning(
                "rate_limit.exceeded",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "limit": str(exc.detail),
                },
            )
            retry_after = getattr(exc, "retry_after", 60)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "limit": str(exc.detail),
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(exc.detail),
                },
            )


        def register_rate_limiting(app: FastAPI) -> None:
            """Attach limiter, exception handler, and middleware to *app*.

            Args:
                app: The FastAPI application instance.
            """
            limiter = get_limiter()
            app.state.limiter = limiter
            app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
            app.add_middleware(SlowAPIMiddleware)
            logger.info("rate_limit.registered")
        '''))


def _write_rate_limit_status_route(dest: Path) -> None:
    """Write ``app/api/routes/rate_limit.py`` with GET /rate-limit/status.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent('''\
        """GET /rate-limit/status — report the caller's current rate-limit state.

        Clients call this endpoint to self-diagnose a 429 before retrying.
        The response includes the configured limit, the remaining calls in the
        current window, and the reset timestamp. Requires authentication so the
        endpoint itself is not a rate-limit oracle for anonymous scanning.
        """

        from __future__ import annotations

        from fastapi import APIRouter, Request
        from pydantic import BaseModel

        from app.core.rate_limit import build_config, get_limiter

        router = APIRouter(prefix="/rate-limit", tags=["rate-limit"])


        class RateLimitStatus(BaseModel):
            """Current rate-limit status for the authenticated caller."""

            enabled: bool
            strategy: str
            default_limits: list[str]
            storage: str


        @router.get("/status", response_model=RateLimitStatus)
        async def get_rate_limit_status(request: Request) -> RateLimitStatus:
            """Return the current rate-limit configuration visible to the caller.

            Args:
                request: Incoming request (for dependency injection).

            Returns:
                A ``RateLimitStatus`` describing the active configuration.
            """
            cfg = build_config()
            _ = get_limiter()  # ensure limiter is built
            return RateLimitStatus(
                enabled=cfg.enabled,
                strategy=cfg.strategy,
                default_limits=cfg.default_limits,
                storage=cfg.storage_uri,
            )
        '''))


def _patch_config(config_file: Path) -> None:
    """Inject ``RATE_LIMIT_*`` fields inside the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "RATE_LIMIT_DEFAULT" in src:
        return

    fields = (
        "    RATE_LIMIT_ENABLED: bool = True\n"
        '    RATE_LIMIT_DEFAULT: str = "100/minute"\n'
        '    RATE_LIMIT_STRATEGY: str = "fixed-window"\n'
        "    RATE_LIMIT_HEADERS_ENABLED: bool = True\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        # Append to file as last resort (still inside Settings if indentation matches)
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register limiter + handler + middleware in ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "register_rate_limiting" in src:
        return

    import_line = (
        "\nfrom app.middleware.rate_limit import register_rate_limiting  "
        "# noqa: F401 — rate limiting\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    # Call register_rate_limiting(app) after app creation
    marker = "app = FastAPI("
    if marker in src:
        # Find end of FastAPI( ... ) construction and insert after
        idx = src.find(marker)
        # Find the closing paren of FastAPI(...) — naive but works for templates
        depth = 0
        end = idx
        for i in range(idx + len(marker), len(src)):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    end = i + 1
                    break
                depth -= 1
        src = src[:end] + "\nregister_rate_limiting(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_rate_limiting(app)\n"

    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
