"""
SKILL-001 Core Tool: Scaffold a production-ready FastAPI project.

Generates a minimal but complete FastAPI project with all 8 core
production patterns baked in from the start.

Generated structure:
    {project}/
        main.py            — App with lifespan, middleware stack, error handlers
        config.py          — pydantic-settings based configuration
        middleware.py       — Correlation, SecurityHeaders, RequestLogging
        health.py          — 3-level health checks (/healthz, /readyz, /startupz)
        deps.py            — Annotated DI (session, http client)
        errors.py          — Centralized exception handlers
        requirements.txt   — Pinned dependencies
        Dockerfile          — Multi-stage, non-root, healthcheck
        .env.example        — Environment template
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.models import ScaffoldInput, ScaffoldResult


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _main_py(inp: ScaffoldInput) -> str:
    db_imports = ""
    db_startup = ""
    db_shutdown = ""
    if inp.with_db:
        db_imports = textwrap.dedent("""\
            from sqlalchemy.ext.asyncio import create_async_engine
        """)
        db_startup = textwrap.dedent("""\
                app.state.db_engine = create_async_engine(
                    settings.database_url,
                    pool_size=5,
                    max_overflow=10,
                    pool_recycle=1800,
                    pool_pre_ping=True,
                )
        """)
        db_shutdown = textwrap.dedent("""\
                await app.state.db_engine.dispose()
        """)

    redis_imports = ""
    redis_startup = ""
    redis_shutdown = ""
    if inp.with_redis:
        redis_imports = textwrap.dedent("""\
            import redis.asyncio as aioredis
        """)
        redis_startup = textwrap.dedent("""\
                app.state.redis = aioredis.from_url(
                    settings.redis_url, decode_responses=True
                )
        """)
        redis_shutdown = textwrap.dedent("""\
                await app.state.redis.aclose()
        """)

    cors_origins = repr(inp.cors_origins)

    return textwrap.dedent(f"""\
        \"\"\"
        {inp.project_name} — FastAPI Application
        \"\"\"

        from contextlib import asynccontextmanager

        import httpx
        import structlog
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from starlette.middleware.gzip import GZipMiddleware

        from config import settings
        from errors import register_error_handlers
        from health import health_router
        from middleware import (
            CorrelationMiddleware,
            RequestLoggingMiddleware,
            SecurityHeadersMiddleware,
        )
        {db_imports}{redis_imports}
        logger = structlog.get_logger()


        @asynccontextmanager
        async def lifespan(app: FastAPI):
            \"\"\"Manage application lifecycle — startup and shutdown.\"\"\"
            # --- STARTUP ---
            logger.info("starting_up", project="{inp.project_name}")
        {db_startup}{redis_startup}    app.state.http_client = httpx.AsyncClient(timeout=10.0)
            yield
            # --- SHUTDOWN (reverse order) ---
            await app.state.http_client.aclose()
        {redis_shutdown}{db_shutdown}    logger.info("shut_down", project="{inp.project_name}")


        app = FastAPI(
            title="{inp.project_name}",
            lifespan=lifespan,
        )

        # --- Middleware stack (LIFO: last added = first executed on request) ---
        # Request flow: Correlation -> CORS -> Security -> Logging -> GZip -> Route
        app.add_middleware(GZipMiddleware, minimum_size=500)
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins={cors_origins},
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
            expose_headers=["X-Correlation-ID"],
            max_age=600,
        )
        app.add_middleware(CorrelationMiddleware)

        # --- Error handlers ---
        register_error_handlers(app)

        # --- Routes ---
        app.include_router(health_router)


        @app.get("/")
        async def root():
            return {{"service": "{inp.project_name}", "status": "running"}}
    """)


def _config_py(inp: ScaffoldInput) -> str:
    db_field = ""
    if inp.with_db:
        db_field = '    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/db"\n'

    redis_field = ""
    if inp.with_redis:
        redis_field = '    redis_url: str = "redis://localhost:6379/0"\n'

    return textwrap.dedent(f"""\
        \"\"\"Application configuration via pydantic-settings.\"\"\"

        from pydantic import field_validator
        from pydantic_settings import BaseSettings


        class Settings(BaseSettings):
            model_config = {{"env_file": ".env", "env_file_encoding": "utf-8"}}

            # --- Core ---
            project_name: str = "{inp.project_name}"
            debug: bool = False
            workers: int = {inp.worker_count}
            cors_origins: list[str] = {repr(inp.cors_origins)}

            # --- Security ---
            jwt_secret: str = "CHANGE-ME-IN-PRODUCTION"

        {db_field}{redis_field}    @field_validator("jwt_secret")
            @classmethod
            def jwt_not_default(cls, v: str) -> str:
                if v in ("change-me", "secret", "CHANGE-ME", "CHANGE-ME-IN-PRODUCTION"):
                    import os
                    if os.getenv("ENVIRONMENT", "development") == "production":
                        raise ValueError("JWT_SECRET must be changed from default in production")
                return v


        # Instantiate at import time — crash before serving if config is invalid
        settings = Settings()
    """)


def _middleware_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Custom middleware stack.\"\"\"

        import time
        import uuid

        import structlog
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        logger = structlog.get_logger()

        REDACT_HEADERS = {"authorization", "cookie", "x-api-key"}


        class CorrelationMiddleware(BaseHTTPMiddleware):
            \"\"\"Propagate or generate X-Correlation-ID for request tracing.\"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
                structlog.contextvars.bind_contextvars(correlation_id=cid)
                response = await call_next(request)
                response.headers["X-Correlation-ID"] = cid
                structlog.contextvars.unbind_contextvars("correlation_id")
                return response


        class SecurityHeadersMiddleware(BaseHTTPMiddleware):
            \"\"\"Add standard security headers to every response.\"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                response = await call_next(request)
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["X-XSS-Protection"] = "1; mode=block"
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
                response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                response.headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
                return response


        class RequestLoggingMiddleware(BaseHTTPMiddleware):
            \"\"\"Log every request with timing. Redact sensitive headers.\"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                start = time.perf_counter()
                response = await call_next(request)
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                logger.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                    client=request.client.host if request.client else "unknown",
                )
                return response
    """)


def _health_py(inp: ScaffoldInput) -> str:
    readiness_checks = ""
    if inp.with_db:
        readiness_checks += textwrap.dedent("""\
                try:
                    async with request.app.state.db_engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    checks["database"] = "ok"
                except Exception:
                    checks["database"] = "failed"
                    all_ok = False
        """)
    if inp.with_redis:
        readiness_checks += textwrap.dedent("""\
                try:
                    await request.app.state.redis.ping()
                    checks["redis"] = "ok"
                except Exception:
                    checks["redis"] = "failed"
                    all_ok = False
        """)

    text_import = ""
    if inp.with_db:
        text_import = "\nfrom sqlalchemy import text"

    return textwrap.dedent(f"""\
        \"\"\"Health check endpoints — 3-level probes for Kubernetes.\"\"\"

        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse{text_import}

        health_router = APIRouter(tags=["health"])


        @health_router.get("/healthz")
        async def liveness():
            \"\"\"Liveness: is the process alive? NEVER check DB/Redis here.\"\"\"
            return {{"status": "alive"}}


        @health_router.get("/readyz")
        async def readiness(request: Request):
            \"\"\"Readiness: can we accept traffic? Check ALL dependencies.\"\"\"
            checks: dict[str, str] = {{}}
            all_ok = True
        {readiness_checks}    if not all_ok:
                return JSONResponse(
                    {{"status": "not_ready", "checks": checks}}, status_code=503
                )
            return {{"status": "ready", "checks": checks}}


        @health_router.get("/startupz")
        async def startup_check(request: Request):
            \"\"\"Startup: has initialization completed?\"\"\"
            if not hasattr(request.app.state, "http_client"):
                return JSONResponse({{"status": "starting"}}, status_code=503)
            return {{"status": "started"}}
    """)


def _deps_py(inp: ScaffoldInput) -> str:
    db_deps = ""
    if inp.with_db:
        db_deps = textwrap.dedent("""\

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


        async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
            \"\"\"Yield a DB session with auto-commit/rollback.\"\"\"
            factory = async_sessionmaker(
                request.app.state.db_engine, expire_on_commit=False
            )
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise


        SessionDep = Annotated[AsyncSession, Depends(get_session)]
        """)

    return textwrap.dedent(f"""\
        \"\"\"Dependency injection with Annotated types.\"\"\"

        from typing import Annotated, AsyncGenerator

        import httpx
        from fastapi import Depends, Request


        async def get_http_client(request: Request) -> httpx.AsyncClient:
            \"\"\"Return the shared async HTTP client from app state.\"\"\"
            return request.app.state.http_client


        HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
        {db_deps}""")


def _errors_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Centralized exception handlers — consistent error format, no secret leaks.\"\"\"

        import structlog
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse

        logger = structlog.get_logger()


        def register_error_handlers(app: FastAPI) -> None:
            \"\"\"Register all exception handlers on the app.\"\"\"

            @app.exception_handler(HTTPException)
            async def http_exc(request: Request, exc: HTTPException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"error": exc.detail, "type": "http_error"},
                )

            @app.exception_handler(RequestValidationError)
            async def validation_exc(request: Request, exc: RequestValidationError):
                return JSONResponse(
                    status_code=422,
                    content={"error": "validation_error", "details": exc.errors()},
                )

            @app.exception_handler(Exception)
            async def unhandled_exc(request: Request, exc: Exception):
                logger.error(
                    "unhandled_exception", exc_info=exc, path=request.url.path
                )
                # NEVER expose str(exc) — may contain DB URLs, SQL, or secrets
                return JSONResponse(
                    status_code=500,
                    content={"error": "internal_server_error"},
                )
    """)


def _requirements_txt(inp: ScaffoldInput) -> str:
    lines = [
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.30.0",
        "pydantic>=2.7",
        "pydantic-settings>=2.3",
        "structlog>=24.1",
        "httpx>=0.27",
    ]
    if inp.with_db:
        lines.extend([
            "sqlalchemy[asyncio]>=2.0",
            "asyncpg>=0.29",
            "alembic>=1.13",
        ])
    if inp.with_redis:
        lines.append("redis[hiredis]>=5.0")
    return "\n".join(lines) + "\n"


def _dockerfile(inp: ScaffoldInput) -> str:
    return textwrap.dedent(f"""\
        # --- Build stage ---
        FROM python:3.12-slim AS builder

        WORKDIR /build
        COPY requirements.txt .
        RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

        # --- Runtime stage ---
        FROM python:3.12-slim

        # Non-root user
        RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

        WORKDIR /app

        COPY --from=builder /install /usr/local
        COPY . .

        RUN chown -R app:app /app
        USER app

        EXPOSE 8000

        HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
            CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"

        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "{inp.worker_count}"]
    """)


def _env_example(inp: ScaffoldInput) -> str:
    lines = [
        f"# {inp.project_name} — Environment Variables",
        "",
        "# Core",
        "ENVIRONMENT=development",
        "DEBUG=false",
        f"WORKERS={inp.worker_count}",
        "",
        "# Security",
        "JWT_SECRET=CHANGE-ME-IN-PRODUCTION",
        f"CORS_ORIGINS={','.join(inp.cors_origins)}",
    ]
    if inp.with_db:
        lines.extend([
            "",
            "# Database",
            "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db",
        ])
    if inp.with_redis:
        lines.extend([
            "",
            "# Redis",
            "REDIS_URL=redis://localhost:6379/0",
        ])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Map of filename -> generator function (or tuple of (generator, needs_input))
_FILE_GENERATORS: dict[str, str] = {
    "main.py": "_main_py",
    "config.py": "_config_py",
    "middleware.py": "_middleware_py",
    "health.py": "_health_py",
    "deps.py": "_deps_py",
    "errors.py": "_errors_py",
    "requirements.txt": "_requirements_txt",
    "Dockerfile": "_dockerfile",
    ".env.example": "_env_example",
}

# Generators that take no input
_NO_INPUT_GENERATORS = {"_middleware_py", "_errors_py"}


def create_app(input: ScaffoldInput) -> ScaffoldResult:
    """
    Generate a production-ready FastAPI project scaffold.

    Creates a directory with all core files implementing the 8 production
    patterns from SKILL-001.

    Args:
        input: Configuration for the project to generate.

    Returns:
        ScaffoldResult with list of created files, project path, and run command.

    Raises:
        FileExistsError: If the project directory already exists.
    """
    project_dir = Path(input.output_dir) / input.project_name
    if project_dir.exists():
        raise FileExistsError(
            f"Directory already exists: {project_dir}. "
            "Remove it first or choose a different name."
        )

    project_dir.mkdir(parents=True, exist_ok=False)

    created_files: list[str] = []

    for filename, gen_name in _FILE_GENERATORS.items():
        gen_func = globals()[gen_name]
        if gen_name in _NO_INPUT_GENERATORS:
            content = gen_func()
        else:
            content = gen_func(input)

        filepath = project_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created_files.append(filename)

    return ScaffoldResult(
        created_files=created_files,
        project_path=str(project_dir),
        run_command=f"cd {project_dir} && pip install -r requirements.txt && uvicorn main:app --reload",
    )
