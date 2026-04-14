"""Generator for FastAPI application entry point (main.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_app(
    output_dir: str,
    name: str = "app",
    prefix: str = "/api/v1",
    with_sentry: bool = False,
    with_rate_limit: bool = True,
    with_prometheus: bool = True,
) -> dict:
    """Generate a production-grade FastAPI main.py.

    Generates `main.py` that:
    - Configures structlog BEFORE creating the app (so all early logs are JSON)
    - Mounts health router at root (/healthz, /readyz) — K8s convention
    - Mounts api_router under prefix (/api/v1)
    - Uses lifespan context manager (not deprecated on_event)
    - Registers middleware in correct Starlette order

    Args:
        output_dir: Directory where main.py will be written.
        name: Application name used in FastAPI title.
        prefix: URL prefix for API routes (e.g. /api/v1).
        with_sentry: Include Sentry SDK initialization.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rate_limit_import = ""
    rate_limit_init = ""
    if with_rate_limit:
        rate_limit_import = (
            "from slowapi import _rate_limit_exceeded_handler\n"
            "from slowapi.errors import RateLimitExceeded\n"
            "from slowapi.middleware import SlowAPIMiddleware\n\n"
            "from app.core.rate_limit import limiter\n"
        )
        rate_limit_init = textwrap.dedent("""\

            # --- Rate limiting (slowapi) ---
            app.state.limiter = limiter
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
            app.add_middleware(SlowAPIMiddleware)
        """)

    prometheus_import = ""
    prometheus_init = ""
    if with_prometheus:
        prometheus_import = (
            "from app.observability.metrics import PrometheusMiddleware, metrics_app\n"
        )
        prometheus_init = textwrap.dedent("""\

            # --- Prometheus metrics ---
            app.add_middleware(PrometheusMiddleware)
            app.mount("/metrics", metrics_app)
        """)

    sentry_import = ""
    sentry_init = ""
    if with_sentry:
        sentry_import = "import sentry_sdk\n"
        sentry_init = textwrap.dedent("""\

            # --- Sentry ---
            if settings.SENTRY_DSN:
                sentry_sdk.init(
                    dsn=str(settings.SENTRY_DSN),
                    traces_sample_rate=0.1 if settings.ENVIRONMENT == "production" else 1.0,
                    environment=settings.ENVIRONMENT,
                )
        """)

    content = textwrap.dedent("""\
        \"\"\"FastAPI application entry point.\"\"\"

        from contextlib import asynccontextmanager
        from collections.abc import AsyncIterator

        from fastapi import FastAPI
        from fastapi.routing import APIRoute
        {sentry_import}{rate_limit_import}{prometheus_import}
        from app.core.config import settings
        from app.core.db import engine, init_db
        from app.core.logging import configure_logging
        from app.core.errors import register_error_handlers
        from app.middleware import register_middleware
        from app.routes import api_router, health_router

        # Configure structlog BEFORE creating the FastAPI app so all
        # subsequent logs (including startup) are properly formatted.
        configure_logging()


        def custom_generate_unique_id(route: APIRoute) -> str:
            \"\"\"Generate clean OpenAPI operation IDs from route names.

            Produces ``tag-route_name`` instead of the default
            ``tag-module-function`` format.
            \"\"\"
            if route.tags:
                return f"{{route.tags[0]}}-{{route.name}}"
            return route.name


        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            \"\"\"Application lifespan: startup and shutdown hooks.\"\"\"
            # --- Startup ---
            await init_db()
            app.state.db_engine = engine

            # Note: initial data seeding (table creation + first superuser)
            # is handled by the Docker entrypoint or by running:
            #   python -m app.initial_data
            # This avoids race conditions with multiple uvicorn workers.

            yield
            # --- Shutdown ---
            await engine.dispose()


        # Disable Swagger UI and OpenAPI schema in production (SEC-08).
        _is_prod = settings.ENVIRONMENT == "production"
        _openapi_url = None if _is_prod else f"{prefix}/openapi.json"
        _docs_url = None if _is_prod else f"{prefix}/docs"
        _redoc_url = None if _is_prod else f"{prefix}/redoc"

        app = FastAPI(
            title="{name}",
            openapi_url=_openapi_url,
            docs_url=_docs_url,
            redoc_url=_redoc_url,
            generate_unique_id_function=custom_generate_unique_id,
            lifespan=lifespan,
        )
        {sentry_init}{rate_limit_init}{prometheus_init}
        # --- Middleware (order matters: last added = first to execute) ---
        register_middleware(app, settings)

        # --- Error handlers ---
        register_error_handlers(app)

        # --- Health checks at ROOT (K8s convention: /healthz, /readyz, /startupz) ---
        # NOT under the API prefix — orchestrators expect them at root.
        app.include_router(health_router, tags=["health"])

        # --- API routes under prefix ---
        app.include_router(api_router, prefix="{prefix}")
    """).format(
        sentry_import=sentry_import,
        sentry_init=sentry_init,
        rate_limit_import=rate_limit_import,
        rate_limit_init=rate_limit_init,
        prometheus_import=prometheus_import,
        prometheus_init=prometheus_init,
        name=name,
        prefix=prefix,
    )

    file_path = out / "main.py"
    file_path.write_text(content)

    files = [str(file_path)]
    notes = [
        "Generated main.py with lifespan, structlog config, error handlers, and router inclusion.",
        "Health checks mounted at ROOT (/healthz, /readyz, /startupz) — K8s convention.",
        "API routes mounted under prefix (e.g. /api/v1).",
    ]
    if with_sentry:
        notes.append("Sentry SDK initialization included; set SENTRY_DSN in environment.")

    return {"files_created": files, "notes": notes}
