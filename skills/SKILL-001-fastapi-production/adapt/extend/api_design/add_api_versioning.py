"""TOOL-017: add_api_versioning — add path-based API versioning to a FastAPI project.

Adds versioned routers under ``/api/v1/`` and ``/api/v2/``, a ``VersionRegistry``
with deprecation and sunset metadata, a ``VersionResolverMiddleware`` that sets
``request.state.api_version`` and attaches ``Sunset``/``Deprecation``/``Link``
response headers, and versioned schema stubs under ``app/schemas/v1/`` and
``app/schemas/v2/``.

The tool is idempotent: a second run on an already-patched project detects the
``VersionRegistry`` fingerprint and returns ``status="no_op"`` without touching any
file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_api_versioning import add_api_versioning

    result = add_api_versioning(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/core/version_registry.py", ...]
    print(result.next_steps)    # ["Restart application", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_api_versioning",
    "description": "Add URL-based API versioning (/api/v1, /api/v2) with deprecation headers.",
    "tags": ["extend", "api_design"],
    "entry": "add_api_versioning",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_api_versioning(inp: ToolInput) -> ToolResult:
    """Add path-based API versioning to a FastAPI project.

    Creates version registry, deprecation middleware, versioned schema stubs,
    versioned router packages, and wires everything into ``app/main.py``.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
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

    registry_file = app_dir / "core" / "version_registry.py"
    if registry_file.exists() and "VersionRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["VersionRegistry already present — API versioning is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    model_names = _discover_models(app_dir)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add VersionRegistry, VersionResolverMiddleware, versioned routers.",
                f"[dry_run] Models found: {', '.join(model_names) or 'none'}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: version_registry.py
    _write_version_registry(registry_file)
    files_created.append(str(registry_file))

    # Step 2: version_resolver middleware
    mw_file = app_dir / "middleware" / "version_resolver.py"
    _write_version_resolver(mw_file)
    files_created.append(str(mw_file))

    # Step 3: versioned schema stubs
    for ver in ("v1", "v2"):
        schema_init = app_dir / "schemas" / ver / "__init__.py"
        _write_versioned_schema_init(schema_init, ver, model_names)
        files_created.append(str(schema_init))

    # Step 4: versioned router packages
    for ver in ("v1", "v2"):
        router_init = app_dir / "api" / ver / "__init__.py"
        _write_versioned_router_init(router_init, ver, model_names)
        files_created.append(str(router_init))

    # Step 5: per-model versioned routes stubs
    for ver in ("v1", "v2"):
        for model in model_names:
            route_file = app_dir / "api" / ver / f"{model.lower()}.py"
            _write_versioned_route(route_file, ver, model)
            files_created.append(str(route_file))

    # Step 6: patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file, model_names)
        files_modified.append(str(main_file))

    # Validate all generated files parse cleanly
    warnings: list[str] = []
    for path_str in files_created:
        w = _validate_py(Path(path_str))
        if w:
            warnings.append(w)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        warnings=warnings,
        notes=[
            "Path-based versioning added: /api/v1/ and /api/v2/.",
            "VersionResolverMiddleware sets request.state.api_version.",
            "Sunset/Deprecation/Link headers emitted for deprecated versions.",
            "Versioned schema stubs placed under app/schemas/v1/ and app/schemas/v2/.",
        ],
        next_steps=[
            "Restart the application to activate VersionResolverMiddleware.",
            "Populate app/schemas/v1/ and app/schemas/v2/ with real schema classes.",
            "Move existing endpoint logic into app/api/v1/<model>.py.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names found in ``app/models/`` that have a
    matching route file in ``app/api/routes/``.

    Only models with a corresponding ``app/api/routes/{stem}.py`` are included
    so that versioned stubs can safely delegate to the existing router.  This
    guards against infrastructure/auth models (e.g. ``api_key``, ``rbac``,
    ``tenant``) whose route files use a different name or do not exist.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item"]``).
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    names: list[str] = []
    if not models_dir.exists():
        return names
    # Build the set of route stems available in app/api/routes/
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        # Only include the model when a same-named route file exists,
        # i.e. app/api/routes/{stem}.py is present.
        if f.stem in available_routes:
            names.append(f.stem.capitalize())
    return names


def _write_version_registry(dest: Path) -> None:
    """Write ``app/core/version_registry.py`` with ``VersionRegistry``.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"API version registry with deprecation and sunset lifecycle.

        Usage::

            from app.core.version_registry import registry

            info = registry.get("v1")
            print(info.is_deprecated)  # True
            print(info.sunset_header)  # RFC 7231 date string
        \"\"\"

        from __future__ import annotations

        import re
        from dataclasses import dataclass, field
        from datetime import date, timedelta
        from typing import Final


        # ---------------------------------------------------------------------------
        # Data model
        # ---------------------------------------------------------------------------

        @dataclass(frozen=True)
        class VersionInfo:
            \"\"\"Immutable descriptor for a single API version.

            Attributes:
                name: Version label, e.g. "v1".
                is_deprecated: True when this version is scheduled for removal.
                sunset_date: Calendar date after which the version is removed.
                changelog_url: Link to the version's changelog entry.
            \"\"\"

            name: str
            is_deprecated: bool = False
            sunset_date: date | None = None
            changelog_url: str = ""

            @property
            def sunset_header(self) -> str | None:
                \"\"\"Return an RFC 7231-formatted Sunset header value, or None.

                Returns:
                    Formatted date string or None if sunset_date is unset.
                \"\"\"
                if self.sunset_date is None:
                    return None
                # RFC 7231 IMF-fixdate: Thu, 01 Jan 2026 00:00:00 GMT
                import calendar
                d = self.sunset_date
                wd = calendar.day_abbr[d.weekday()]
                mon = calendar.month_abbr[d.month]
                return f"{wd}, {d.day:02d} {mon} {d.year} 00:00:00 GMT"


        # ---------------------------------------------------------------------------
        # Registry
        # ---------------------------------------------------------------------------

        class VersionRegistry:
            \"\"\"Holds all known API versions.

            Attributes:
                _versions: Internal mapping from version label to VersionInfo.
            \"\"\"

            def __init__(self) -> None:
                self._versions: dict[str, VersionInfo] = {}

            def register(self, info: VersionInfo) -> None:
                \"\"\"Add a version descriptor to the registry.

                Args:
                    info: VersionInfo to register.
                \"\"\"
                self._versions[info.name] = info

            def get(self, name: str) -> VersionInfo | None:
                \"\"\"Return VersionInfo for *name*, or None if unknown.

                Args:
                    name: Version label (e.g. "v1").

                Returns:
                    VersionInfo or None.
                \"\"\"
                return self._versions.get(name)

            def supported(self) -> list[str]:
                \"\"\"Return all registered version labels.

                Returns:
                    List of version label strings.
                \"\"\"
                return list(self._versions.keys())

            def deprecated(self) -> list[str]:
                \"\"\"Return labels of deprecated versions.

                Returns:
                    List of deprecated version label strings.
                \"\"\"
                return [v for v, info in self._versions.items() if info.is_deprecated]


        # ---------------------------------------------------------------------------
        # Singleton registry — configure deprecation windows here
        # ---------------------------------------------------------------------------

        registry: Final[VersionRegistry] = VersionRegistry()

        registry.register(VersionInfo(
            name="v1",
            is_deprecated=True,
            sunset_date=date.today() + timedelta(days=180),
            changelog_url="/docs/changelog#v1",
        ))
        registry.register(VersionInfo(
            name="v2",
            is_deprecated=False,
            changelog_url="/docs/changelog#v2",
        ))


        # ---------------------------------------------------------------------------
        # Path version extractor (used by middleware)
        # ---------------------------------------------------------------------------

        _PATH_VERSION_RE = re.compile(r"^/api/(v\\d+)(/|$)")


        def extract_version_from_path(path: str) -> str | None:
            \"\"\"Return the version token from a URL path, or None.

            Args:
                path: URL path string (e.g. "/api/v1/items/").

            Returns:
                Version label (e.g. "v1") or None if not present.
            \"\"\"
            m = _PATH_VERSION_RE.match(path)
            return m.group(1) if m else None
        """)
    dest.write_text(content)


def _write_version_resolver(dest: Path) -> None:
    """Write ``app/middleware/version_resolver.py``.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Starlette middleware that resolves the API version for each request.

        Sets ``request.state.api_version`` and attaches ``Sunset``, ``Deprecation``,
        and ``Link`` headers to responses for deprecated versions.

        Mount in ``app/main.py``::

            from app.middleware.version_resolver import VersionResolverMiddleware
            app.add_middleware(VersionResolverMiddleware)
        \"\"\"

        from __future__ import annotations

        from fastapi import Request, Response
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.types import ASGIApp

        from app.core.version_registry import extract_version_from_path, registry

        _DEFAULT_VERSION = "v2"


        class VersionResolverMiddleware(BaseHTTPMiddleware):
            \"\"\"Resolve API version from URL path and annotate the request/response.

            For unknown versions the middleware returns a 400 JSON error.
            For deprecated versions it attaches Deprecation/Sunset/Link headers.

            Args:
                app: The ASGI application to wrap.
            \"\"\"

            def __init__(self, app: ASGIApp) -> None:
                super().__init__(app)

            async def dispatch(self, request: Request, call_next) -> Response:
                \"\"\"Intercept every request to resolve and validate the API version.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next ASGI handler.

                Returns:
                    HTTP response, possibly with versioning headers injected.
                \"\"\"
                version = extract_version_from_path(request.url.path)

                if version is None:
                    version = _DEFAULT_VERSION

                if version not in registry.supported():
                    return Response(
                        content='{"detail": "Unsupported API version: ' + version + '"}',
                        status_code=400,
                        media_type="application/json",
                    )

                request.state.api_version = version
                response: Response = await call_next(request)
                response.headers["X-API-Version"] = version

                info = registry.get(version)
                if info and info.is_deprecated:
                    response.headers["Deprecation"] = "true"
                    if info.sunset_header:
                        response.headers["Sunset"] = info.sunset_header
                    next_ver = _next_version(version)
                    if next_ver:
                        successor = request.url.path.replace(
                            f"/api/{version}", f"/api/{next_ver}", 1
                        )
                        response.headers["Link"] = (
                            f'<{successor}>; rel="successor-version"'
                        )

                return response


        def _next_version(current: str) -> str | None:
            \"\"\"Return the next non-deprecated version after *current*, or None.

            Args:
                current: Current version label (e.g. "v1").

            Returns:
                Next version label or None.
            \"\"\"
            supported = registry.supported()
            try:
                idx = supported.index(current)
                for candidate in supported[idx + 1:]:
                    if not registry.get(candidate).is_deprecated:
                        return candidate
            except (ValueError, IndexError):
                pass
            return None
        """)
    dest.write_text(content)


def _write_versioned_schema_init(dest: Path, version: str, model_names: list[str]) -> None:
    """Write ``app/schemas/{version}/__init__.py`` re-exporting schema stubs.

    Args:
        dest: Absolute destination path.
        version: Version label (e.g. "v1").
        model_names: List of model names to generate stubs for.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    model_lines = "\n".join(
        f"# from app.schemas.{version}.{m.lower()} import {m}Create, {m}Public  # noqa: F401"
        for m in model_names
    ) or "# No models discovered — add imports here."

    content = textwrap.dedent("""\
        \"\"\"Versioned schemas for API {version}.

        Add version-specific schema overrides here.  By default schemas delegate
        to the base schemas in ``app/schemas/``.

        Example::

            from app.schemas.{version} import ItemCreate, ItemPublic
        \"\"\"

        from __future__ import annotations

        # Uncomment and customise when you introduce breaking changes:
        {model_lines}
        """).replace("{version}", version).replace("{model_lines}", model_lines)
    dest.write_text(content)


def _write_versioned_router_init(dest: Path, version: str, model_names: list[str]) -> None:
    """Write ``app/api/{version}/__init__.py`` assembling the versioned router.

    Args:
        dest: Absolute destination path.
        version: Version label (e.g. "v1").
        model_names: List of model names to include.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    include_lines = "\n".join(
        "router.include_router("
        + f"{m.lower()}_router, prefix='/{m.lower()}s', tags=['{version}-{m.lower()}s']"
        + ")"
        for m in model_names
    ) or "# No models discovered — include routers here."

    import_lines = "\n".join(
        f"from app.api.{version}.{m.lower()} import router as {m.lower()}_router"
        for m in model_names
    ) or "# No models discovered."

    content = textwrap.dedent("""\
        \"\"\"Versioned router package for API {version}.

        All endpoints served under ``/api/{version}/`` are assembled here.
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter

        {import_lines}

        router = APIRouter()
        {include_lines}
        """).replace("{version}", version).replace("{import_lines}", import_lines).replace(
            "{include_lines}", include_lines
        )
    dest.write_text(content)


def _write_versioned_route(dest: Path, version: str, model_name: str) -> None:
    """Write a versioned route stub for one model.

    Args:
        dest: Absolute destination path.
        version: Version label (e.g. "v1").
        model_name: PascalCase model name.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    lower = model_name.lower()
    content = textwrap.dedent("""\
        \"\"\"API {version} routes for {Model}.

        Delegates to the shared CRUD layer; override response schemas here when
        introducing breaking changes between versions.
        \"\"\"

        from __future__ import annotations

        from fastapi import APIRouter

        from app.api.routes.{lower} import router as _base_router

        # Re-export the base router unchanged for {version}.
        # When introducing a breaking change, replace this with a custom router.
        router = APIRouter()
        router.include_router(_base_router)
        """).replace("{version}", version).replace("{Model}", model_name).replace(
            "{lower}", lower
        )
    dest.write_text(content)


def _patch_main(main_file: Path, model_names: list[str]) -> None:
    """Wire VersionResolverMiddleware and versioned routers into main.py.

    Args:
        main_file: Path to ``app/main.py``.
        model_names: Discovered model names (unused but kept for signature consistency).
    """
    src = main_file.read_text()

    if "VersionResolverMiddleware" in src:
        return

    middleware_import = (
        "\nfrom app.middleware.version_resolver import VersionResolverMiddleware"
    )
    v1_import = "\nfrom app.api.v1 import router as _v1_router"
    v2_import = "\nfrom app.api.v2 import router as _v2_router"

    # Append imports after last existing import block
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + middleware_import + v1_import + v2_import,
        )
    else:
        src = middleware_import + v1_import + v2_import + "\n" + src

    # Add middleware registration before app.include_router lines if possible
    middleware_call = (
        "\napp.add_middleware(VersionResolverMiddleware)"
        "\napp.include_router(_v1_router, prefix='/api/v1')"
        "\napp.include_router(_v2_router, prefix='/api/v2')"
    )
    if "app.add_middleware" in src:
        # Insert after last add_middleware call
        idx = src.rfind("app.add_middleware")
        end = src.find("\n", idx)
        src = src[: end + 1] + middleware_call + src[end + 1:]
    else:
        src = src.rstrip("\n") + "\n" + middleware_call + "\n"

    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _validate_py(path: Path) -> str | None:
    """Return an error string if *path* fails ``ast.parse``, else None.

    Args:
        path: Python file to validate.

    Returns:
        Error string or None.
    """
    try:
        ast.parse(path.read_text())
        return None
    except SyntaxError as exc:
        return f"SyntaxError in {path}: {exc}"


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
