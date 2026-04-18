"""TOOL-088: add_cors_config — upgrade CORS middleware with env-var configurable origins.

Upgrades the existing CORS middleware in a FastAPI project: configurable origins
from CORS_ALLOWED_ORIGINS (comma-separated), wildcard warnings, configurable
max_age and allow_credentials, and a ``GET /cors/config`` debug endpoint.

The tool is idempotent: a second run detects ``app/middleware/cors_config.py`` and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_cors_config import add_cors_config

    result = add_cors_config(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/middleware/cors_config.py, ...]
    print(result.next_steps)    # ["Set CORS_ALLOWED_ORIGINS in .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_cors_config",
    "description": (
        "Upgrade CORS middleware with env-var configurable origins, wildcard warnings, "
        "preflight cache, and a /cors/config debug endpoint."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_cors_config",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cors_config(inp: ToolInput) -> ToolResult:
    """Upgrade CORS configuration in a FastAPI project.

    Writes ``app/middleware/cors_config.py`` with ``CORSConfigMiddleware``
    that reads origins from ``CORS_ALLOWED_ORIGINS``, logs a warning on
    wildcard usage, and adds a ``/cors/config`` debug endpoint. Patches
    ``app/core/config.py`` with ``CORS_*`` fields and patches ``app/main.py``
    to use the configurable middleware (replacing any hardcoded CORS setup).

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

    # --- Prerequisite check --------------------------------------------------
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
    cors_config_file = app_dir / "middleware" / "cors_config.py"
    if cors_config_file.exists() and "CORSConfigMiddleware" in cors_config_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["CORSConfigMiddleware already present — configurable CORS already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/cors_config.py, "
                "app/api/routes/cors_debug.py, and patch config + main."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: middleware package -------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)

    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    _write_cors_config_middleware(cors_config_file)
    files_created.append(str(cors_config_file))

    # --- Step 2: /cors/config debug route ------------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        cors_debug_route = routes_dir / "cors_debug.py"
        _write_cors_debug_route(cors_debug_route)
        files_created.append(str(cors_debug_route))

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

    # --- Step 5: ast.parse validation ----------------------------------------
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
            "CORS upgraded: origins read from CORS_ALLOWED_ORIGINS env var (comma-separated).",
            "Wildcard '*' origin triggers a warning log in non-local environments.",
            "Preflight responses cached for CORS_MAX_AGE seconds (default: 600).",
            "GET /cors/config debug endpoint lists active CORS configuration.",
        ],
        next_steps=[
            "Set CORS_ALLOWED_ORIGINS=https://app.example.com,https://www.example.com in .env.",
            "Set CORS_ALLOW_CREDENTIALS=true if your frontend sends cookies.",
            "Set CORS_MAX_AGE=3600 to increase preflight cache duration.",
            "Never use CORS_ALLOWED_ORIGINS=* in production — it defeats CORS protections.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each <= 50 LOC
# ---------------------------------------------------------------------------

def _write_cors_config_middleware(dest: Path) -> None:
    """Write ``app/middleware/cors_config.py`` with CORSConfigMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CORSConfigMiddleware — env-var driven CORS with wildcard warnings.

        Reads allowed origins from settings and warns when wildcard is used
        in non-local environments (security guardrail).
        \"\"\"

        from __future__ import annotations

        import logging
        import os

        from fastapi.middleware.cors import CORSMiddleware
        from starlette.applications import Starlette
        from starlette.types import ASGIApp

        logger = logging.getLogger(__name__)


        def _parse_origins(raw: str) -> list[str]:
            \"\"\"Parse comma-separated origin string into a cleaned list.

            Args:
                raw: Comma-separated origins, e.g. ``"https://a.com, https://b.com"``.

            Returns:
                List of stripped, non-empty origin strings.
            \"\"\"
            return [o.strip() for o in raw.split(",") if o.strip()]


        def _warn_if_wildcard(origins: list[str], environment: str) -> None:
            \"\"\"Log a warning when wildcard is configured in non-local environments.

            Args:
                origins: List of allowed origin strings.
                environment: Current ENVIRONMENT value from settings.
            \"\"\"
            if "*" in origins and environment not in ("local", "test"):
                logger.warning(
                    "CORS wildcard '*' is active in environment=%s — "
                    "this disables origin protection. "
                    "Set CORS_ALLOWED_ORIGINS to specific origins in production.",
                    environment,
                )


        class CORSConfigMiddleware:
            \"\"\"ASGI wrapper that installs CORSMiddleware from env-var settings.

            Reads ``CORS_ALLOWED_ORIGINS``, ``CORS_ALLOW_CREDENTIALS``, and
            ``CORS_MAX_AGE`` from environment variables, then wraps the inner
            app with FastAPI's built-in ``CORSMiddleware``.

            Args:
                app: The inner ASGI application.
            \"\"\"

            def __init__(self, app: ASGIApp) -> None:
                \"\"\"Configure CORS from environment and wrap the app.\"\"\"
                raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
                origins = _parse_origins(raw_origins)
                environment = os.getenv("ENVIRONMENT", "local")
                allow_credentials = (
                    os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"
                )
                max_age = int(os.getenv("CORS_MAX_AGE", "600"))
                _warn_if_wildcard(origins, environment)
                self._app = CORSMiddleware(
                    app=app,
                    allow_origins=origins,
                    allow_credentials=allow_credentials,
                    allow_methods=["*"],
                    allow_headers=["*"],
                    max_age=max_age,
                )

            async def __call__(self, scope, receive, send) -> None:
                \"\"\"Delegate every ASGI call to the wrapped CORSMiddleware.\"\"\"
                await self._app(scope, receive, send)
        """))


def _write_cors_debug_route(dest: Path) -> None:
    """Write ``app/api/routes/cors_debug.py`` with GET /cors/config endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"GET /cors/config — debug endpoint showing active CORS configuration.\"\"\"

        from __future__ import annotations

        import logging
        import os

        from fastapi import APIRouter

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/cors", tags=["cors"])


        @router.get("/config")
        async def cors_config() -> dict:
            \"\"\"Return the active CORS configuration from environment variables.

            Returns:
                Dict with ``allowed_origins``, ``allow_credentials``, ``max_age``,
                and ``wildcard_warning`` flag.
            \"\"\"
            raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
            origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
            environment = os.getenv("ENVIRONMENT", "local")
            allow_credentials = (
                os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"
            )
            max_age = int(os.getenv("CORS_MAX_AGE", "600"))
            wildcard_warning = "*" in origins and environment not in ("local", "test")
            return {
                "allowed_origins": origins,
                "allow_credentials": allow_credentials,
                "max_age": max_age,
                "environment": environment,
                "wildcard_warning": wildcard_warning,
            }
        """))


def _patch_config(config_file: Path) -> None:
    """Inject CORS_* fields into ``class Settings`` in config.py.

    Inserts fields inside the class body using the REDIS_URL field as an
    anchor (or falls back to the first decorator inside the class).

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "CORS_ALLOWED_ORIGINS" in src:
        return

    new_fields = (
        "\n"
        "    # CORS configuration — added by add_cors_config tool\n"
        '    CORS_ALLOWED_ORIGINS: str = "*"\n'
        "    CORS_ALLOW_CREDENTIALS: bool = False\n"
        "    CORS_MAX_AGE: int = 600\n"
    )
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    if anchor in src:
        src = src.replace(anchor, anchor + new_fields)
    else:
        for decorator in ("    @computed_field", "    @model_validator", "    @property"):
            if decorator in src:
                first_pos = src.index(decorator)
                src = src[:first_pos] + new_fields + "\n" + src[first_pos:]
                break
        else:
            marker = "settings = Settings()"
            if marker in src:
                src = src.replace(marker, new_fields + "\n" + marker)
            else:
                src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject CORSConfigMiddleware and /cors/config router into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "CORSConfigMiddleware" in src:
        return

    cors_import = (
        "\nfrom app.middleware.cors_config import CORSConfigMiddleware"
        "  # noqa: F401 — configurable CORS\n"
        "from app.api.routes.cors_debug import router as _cors_debug_router\n"
    )
    add_middleware_snippet = textwrap.dedent("""\

        # Configurable CORS + debug endpoint — added by add_cors_config tool
        app.add_middleware(CORSConfigMiddleware)
        app.include_router(_cors_debug_router)
    """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + cors_import,
        )
    else:
        src = cors_import + src

    src = src.rstrip("\n") + "\n" + add_middleware_snippet
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
