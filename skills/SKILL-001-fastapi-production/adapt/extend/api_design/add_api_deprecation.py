"""TOOL-106: add_api_deprecation — endpoint lifecycle management.

Generates a DeprecationRegistry, DeprecationMiddleware (RFC 8594 Sunset +
Deprecation headers + Link to replacement), DeprecationReporter (usage
tracking), GET /api/deprecations listing route, and a @deprecated decorator.

The tool is idempotent: a second run detects the ``DeprecationRegistry``
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_api_deprecation import add_api_deprecation

    result = add_api_deprecation(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/deprecation/__init__.py", ...]

After applying::

    from app.deprecation import deprecated

    @router.get("/items")
    @deprecated(sunset="2026-06-01", replacement="/api/v2/items")
    async def list_items():
        ...
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_api_add_api_deprecation",
    "description": "Add endpoint lifecycle management with RFC 8594 Sunset headers, usage tracking, and @deprecated decorator.",
    "tags": ["extend", "api_design"],
    "entry": "add_api_deprecation",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_api_deprecation(inp: ToolInput) -> ToolResult:
    """Add API deprecation lifecycle management to a FastAPI project.

    Creates DeprecationRegistry, DeprecationMiddleware (Sunset + Deprecation
    headers per RFC 8594), DeprecationReporter with usage tracking,
    GET /api/deprecations listing route, and @deprecated decorator.
    Patches ``app/core/config.py`` and ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

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
        Prereq.ROUTES_INIT,
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

    # Idempotency guard
    registry_file = app_dir / "deprecation" / "__init__.py"
    if registry_file.exists() and "DeprecationRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DeprecationRegistry already present — API deprecation is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/deprecation/ (DeprecationRegistry, middleware, reporter),",
                "         GET /api/deprecations listing route,",
                "         @deprecated decorator.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — deprecation package with registry + decorator
    deprecation_dir = app_dir / "deprecation"
    deprecation_dir.mkdir(parents=True, exist_ok=True)
    _write_registry_module(registry_file)
    files_created.append(str(registry_file))

    # Step 2 — middleware
    middleware_file = deprecation_dir / "middleware.py"
    _write_middleware_module(middleware_file)
    files_created.append(str(middleware_file))

    # Step 3 — reporter
    reporter_file = deprecation_dir / "reporter.py"
    _write_reporter_module(reporter_file)
    files_created.append(str(reporter_file))

    # Step 4 — HTTP listing route
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    deprecation_route = routes_dir / "deprecation.py"
    _write_deprecation_route(deprecation_route)
    files_created.append(str(deprecation_route))

    # Step 5 — register route in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 6 — patch main.py to add DeprecationMiddleware
    main_file = app_dir / "main.py"
    if main_file.exists():
        if _patch_main(main_file):
            files_modified.append(str(main_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Validate generated Python files
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
            "API deprecation lifecycle management added.",
            "DeprecationRegistry: register endpoints with sunset dates.",
            "DeprecationMiddleware: adds Sunset (RFC 8594) + Deprecation headers on every response.",
            "DeprecationReporter: tracks usage count of deprecated endpoints.",
            "GET /api/deprecations: list all deprecated endpoints + sunset dates.",
            "@deprecated decorator: mark any route function as deprecated.",
        ],
        next_steps=[
            "Decorate deprecated routes: @deprecated(sunset='2026-06-01', replacement='/v2/items')",
            "Register middleware: DeprecationMiddleware is auto-registered in app/main.py",
            "Set DEPRECATION_WARN_DAYS_BEFORE_SUNSET=30 in .env (default: 30)",
            "Monitor usage: GET /api/deprecations to see which deprecated endpoints are still called",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_registry_module(dest: Path) -> None:
    """Write ``app/deprecation/__init__.py`` with DeprecationRegistry + @deprecated.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"API deprecation lifecycle management.

        Usage::

            from app.deprecation import deprecated, registry

            @router.get("/items")
            @deprecated(sunset="2026-06-01", replacement="/api/v2/items")
            async def list_items():
                ...

            # List all deprecated endpoints
            entries = registry.list_all()
        \"\"\"

        from __future__ import annotations

        import functools
        import logging
        from collections.abc import Callable
        from datetime import date, timedelta
        from typing import Any

        from app.core.config import settings

        logger = logging.getLogger(__name__)


        class DeprecationEntry:
            \"\"\"Metadata for a single deprecated endpoint.

            Attributes:
                path: URL path of the deprecated endpoint.
                method: HTTP method (GET, POST, etc.).
                sunset: Date when the endpoint will be removed.
                replacement: URL of the replacement endpoint.
                description: Optional human-readable deprecation reason.
            \"\"\"

            def __init__(
                self,
                path: str,
                method: str,
                sunset: str,
                replacement: str,
                description: str = "",
            ) -> None:
                \"\"\"Initialise a deprecation entry.

                Args:
                    path: URL path of the deprecated endpoint.
                    method: HTTP method (GET, POST, etc.).
                    sunset: ISO date string when endpoint will be removed.
                    replacement: URL of the replacement endpoint.
                    description: Optional human-readable deprecation reason.
                \"\"\"
                self.path = path
                self.method = method.upper()
                self.sunset_date = date.fromisoformat(sunset)
                self.replacement = replacement
                self.description = description

            @property
            def sunset_header(self) -> str:
                \"\"\"RFC 8594 Sunset header value (ISO date string).

                Returns:
                    ISO date string for the Sunset header.
                \"\"\"
                return self.sunset_date.isoformat()

            @property
            def days_until_sunset(self) -> int:
                \"\"\"Number of days until the sunset date.

                Returns:
                    Days remaining until sunset (negative if already past).
                \"\"\"
                return (self.sunset_date - date.today()).days

            @property
            def should_warn(self) -> bool:
                \"\"\"Return True when within the warning window before sunset.

                Returns:
                    True when sunset is within DEPRECATION_WARN_DAYS_BEFORE_SUNSET days.
                \"\"\"
                warn_days = getattr(settings, "DEPRECATION_WARN_DAYS_BEFORE_SUNSET", 30)
                return self.days_until_sunset <= warn_days

            def to_dict(self) -> dict[str, Any]:
                \"\"\"Serialise entry to a JSON-safe dict.

                Returns:
                    Dict with path, method, sunset, replacement, days_until_sunset.
                \"\"\"
                return {
                    "path": self.path,
                    "method": self.method,
                    "sunset": self.sunset_date.isoformat(),
                    "replacement": self.replacement,
                    "description": self.description,
                    "days_until_sunset": self.days_until_sunset,
                    "warn": self.should_warn,
                }


        class DeprecationRegistry:
            \"\"\"Central registry of all deprecated API endpoints.\"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise an empty registry.\"\"\"
                self._entries: dict[str, DeprecationEntry] = {}

            def register(
                self,
                path: str,
                method: str,
                sunset: str,
                replacement: str,
                description: str = "",
            ) -> DeprecationEntry:
                \"\"\"Register an endpoint as deprecated.

                Args:
                    path: URL path of the deprecated endpoint.
                    method: HTTP method (GET, POST, etc.).
                    sunset: ISO date string when endpoint will be removed.
                    replacement: URL of the replacement endpoint.
                    description: Optional human-readable reason.

                Returns:
                    The created DeprecationEntry.
                \"\"\"
                key = f"{method.upper()} {path}"
                entry = DeprecationEntry(path, method, sunset, replacement, description)
                self._entries[key] = entry
                if entry.should_warn:
                    logger.warning(
                        "Deprecated endpoint %s sunsets in %d days -> %s",
                        key,
                        entry.days_until_sunset,
                        replacement,
                    )
                return entry

            def get(self, path: str, method: str) -> DeprecationEntry | None:
                \"\"\"Look up a deprecation entry by path and method.

                Args:
                    path: URL path to look up.
                    method: HTTP method to look up.

                Returns:
                    DeprecationEntry if found, None otherwise.
                \"\"\"
                return self._entries.get(f"{method.upper()} {path}")

            def list_all(self) -> list[dict[str, Any]]:
                \"\"\"Return all registered deprecation entries as serialisable dicts.

                Returns:
                    List of entry dicts sorted by sunset date ascending.
                \"\"\"
                return sorted(
                    (e.to_dict() for e in self._entries.values()),
                    key=lambda d: d["sunset"],
                )


        # Module-level singleton registry
        registry = DeprecationRegistry()


        def deprecated(
            sunset: str,
            replacement: str,
            method: str = "GET",
            description: str = "",
        ) -> Callable[[Any], Any]:
            \"\"\"Decorator to mark a route handler as deprecated.

            Registers the endpoint in the module-level registry so
            DeprecationMiddleware can add response headers automatically.

            Args:
                sunset: ISO date string when the endpoint will be removed.
                replacement: URL of the replacement endpoint.
                method: HTTP method (default 'GET').
                description: Optional human-readable deprecation reason.

            Returns:
                Decorator that wraps the route handler unchanged.

            Example::

                @router.get("/items")
                @deprecated(sunset="2026-06-01", replacement="/api/v2/items")
                async def list_items():
                    ...
            \"\"\"
            def decorator(func: Any) -> Any:
                path = getattr(func, "__route_path__", f"/{func.__name__}")
                registry.register(path, method, sunset, replacement, description)
                func.__deprecated__ = True
                func.__sunset__ = sunset
                func.__replacement__ = replacement

                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return await func(*args, **kwargs)

                wrapper.__deprecated__ = True
                wrapper.__sunset__ = sunset
                wrapper.__replacement__ = replacement
                return wrapper
            return decorator
    """)
    dest.write_text(content)


def _write_middleware_module(dest: Path) -> None:
    """Write ``app/deprecation/middleware.py`` with DeprecationMiddleware.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"DeprecationMiddleware — add RFC 8594 Sunset and Deprecation headers.

        For every response to a deprecated endpoint, automatically injects:
        - ``Sunset: <ISO-date>`` (RFC 8594)
        - ``Deprecation: true``
        - ``Link: <replacement>; rel="successor-version"``
        \"\"\"

        from __future__ import annotations

        import logging

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.deprecation import registry
        from app.deprecation.reporter import reporter

        logger = logging.getLogger(__name__)


        class DeprecationMiddleware(BaseHTTPMiddleware):
            \"\"\"Add RFC 8594 Sunset/Deprecation headers to deprecated endpoint responses.\"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                \"\"\"Intercept response and add deprecation headers when applicable.

                Args:
                    request: Incoming HTTP request.
                    call_next: ASGI call-next handler.

                Returns:
                    Response with Sunset/Deprecation/Link headers if deprecated.
                \"\"\"
                response = await call_next(request)
                entry = registry.get(request.url.path, request.method)
                if entry is not None:
                    response.headers["Sunset"] = entry.sunset_header
                    response.headers["Deprecation"] = "true"
                    if entry.replacement:
                        response.headers["Link"] = (
                            f'<{entry.replacement}>; rel="successor-version"'
                        )
                    reporter.record(request.url.path, request.method)
                return response
    """)
    dest.write_text(content)


def _write_reporter_module(dest: Path) -> None:
    """Write ``app/deprecation/reporter.py`` with DeprecationReporter.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"DeprecationReporter — track usage of deprecated endpoints.

        Records how many times each deprecated endpoint is called so operators
        can see which deprecated APIs still have active consumers.
        \"\"\"

        from __future__ import annotations

        import logging
        from collections import defaultdict
        from typing import Any

        logger = logging.getLogger(__name__)


        class DeprecationReporter:
            \"\"\"In-memory tracker for deprecated endpoint call counts.

            Attributes:
                _counts: Dict mapping 'METHOD /path' to total call count.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise with empty call count storage.\"\"\"
                self._counts: dict[str, int] = defaultdict(int)

            def record(self, path: str, method: str) -> None:
                \"\"\"Increment call count for a deprecated endpoint.

                Args:
                    path: URL path of the deprecated endpoint.
                    method: HTTP method of the call.
                \"\"\"
                key = f"{method.upper()} {path}"
                self._counts[key] += 1
                logger.debug("Deprecated endpoint called: %s (total: %d)", key, self._counts[key])

            def get_count(self, path: str, method: str) -> int:
                \"\"\"Return call count for a specific deprecated endpoint.

                Args:
                    path: URL path to query.
                    method: HTTP method to query.

                Returns:
                    Total number of times this deprecated endpoint has been called.
                \"\"\"
                return self._counts.get(f"{method.upper()} {path}", 0)

            def usage_report(self) -> list[dict[str, Any]]:
                \"\"\"Return usage report sorted by call count descending.

                Returns:
                    List of dicts with 'endpoint' and 'call_count' keys.
                \"\"\"
                return sorted(
                    [
                        {"endpoint": endpoint, "call_count": count}
                        for endpoint, count in self._counts.items()
                    ],
                    key=lambda d: d["call_count"],
                    reverse=True,
                )

            def reset(self) -> None:
                \"\"\"Reset all call counts (for testing purposes).\"\"\"
                self._counts.clear()


        # Module-level singleton reporter
        reporter = DeprecationReporter()
    """)
    dest.write_text(content)


def _write_deprecation_route(dest: Path) -> None:
    """Write ``app/api/routes/deprecation.py`` with GET /deprecations route.

    The router has no prefix; the mount prefix (e.g. ``/api/v1``) comes from
    the parent ``api_router`` in ``app/routes/__init__.py``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"GET /deprecations — list all deprecated endpoints and sunset dates.

        Mounted under the api_router prefix (e.g. /api/v1/deprecations).
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from fastapi import APIRouter

        logger = logging.getLogger(__name__)

        router = APIRouter(tags=["lifecycle"])


        @router.get("/deprecations")
        async def list_deprecations() -> dict[str, Any]:
            \"\"\"List all deprecated endpoints with sunset dates and usage statistics.

            Returns:
                Dict with 'deprecated' list and 'usage' list.
            \"\"\"
            from app.deprecation import registry
            from app.deprecation.reporter import reporter
            entries = registry.list_all()
            usage = reporter.usage_report()
            return {
                "deprecated": entries,
                "usage": usage,
                "total_deprecated": len(entries),
            }
    """)
    dest.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the deprecation router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    content = routes_init.read_text()
    import_line = "from app.api.routes.deprecation import router as deprecation_router"
    include_line = "api_router.include_router(deprecation_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_main(main_file: Path) -> bool:
    """Inject DeprecationMiddleware into app/main.py idempotently.

    Args:
        main_file: Path to ``app/main.py``.

    Returns:
        True if the file was modified, False if already patched.
    """
    content = main_file.read_text()
    if "DeprecationMiddleware" in content:
        return False
    import_line = "from app.deprecation.middleware import DeprecationMiddleware"
    add_middleware_line = "app.add_middleware(DeprecationMiddleware)"
    if import_line in content:
        return False
    # Append after existing imports block
    lines = content.splitlines(keepends=True)
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            insert_idx = i + 1
    lines.insert(insert_idx, f"{import_line}\n")
    # Find where app is created and add middleware right after
    new_content = "".join(lines)
    if "app = FastAPI" in new_content and add_middleware_line not in new_content:
        new_content = new_content.replace(
            "app = FastAPI",
            f"app = FastAPI",
            1,
        )
        new_content = new_content + f"\n{add_middleware_line}\n"
    main_file.write_text(new_content)
    return True


def _patch_config(config_file: Path) -> None:
    """Append DEPRECATION_* settings to app/core/config.py idempotently.

    Args:
        config_file: Path to the project's ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("DEPRECATION_WARN_DAYS_BEFORE_SUNSET", "DEPRECATION_WARN_DAYS_BEFORE_SUNSET: int = 30"),
        ],
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot taken at function entry.

    Returns:
        Elapsed time in integer milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
