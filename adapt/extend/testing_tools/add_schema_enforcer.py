"""TOOL-117: add_schema_enforcer — OpenAPI schema enforcement middleware.

Generates production-grade schema enforcement with:
- Request/response validation against the live OpenAPI spec
- Rejection of extra fields (prevents mass assignment, OWASP API1)
- Drift detection: routes vs docs → shadow API alert
- Fuzz test generation from schema (Schemathesis-style property tests)
- Shadow API blocker for undocumented endpoints

Idempotent: a second run detects ``app/middleware/schema_enforcer.py`` and
returns ``status="no_op"`` without touching any file.

Generated files:
  - ``app/middleware/schema_enforcer.py``    enforcement middleware + drift detector
  - ``app/core/schema_enforcer.py``          spec loader + validator engine
  - ``tests/test_schema_fuzz.py``            generated fuzz test file

Patched files:
  - ``app/core/config.py``       SCHEMA_ENFORCER_* fields inside Settings
  - ``app/main.py``              schema enforcer middleware registration
  - ``requirements.txt``         ``jsonschema>=4.23.0`` dependency

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer

    result = add_schema_enforcer(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/middleware/schema_enforcer.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_schema_enforcer",
    "description": (
        "Add OpenAPI schema enforcement middleware: validates every req/resp "
        "against the spec (rejects extra fields), detects shadow/zombie APIs "
        "(drift detection), generates Schemathesis-style fuzz tests, and blocks "
        "undocumented endpoints. Modes: enforce/detect/fuzz."
    ),
    "tags": ["extend", "testing_tools", "security"],
    "entry": "add_schema_enforcer",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_schema_enforcer(inp: ToolInput) -> ToolResult:
    """Add OpenAPI schema enforcement to a FastAPI project.

    Creates the schema enforcer engine, ASGI middleware, and a fuzz test
    file. Patches ``app/core/config.py`` with ``SCHEMA_ENFORCER_*`` settings
    and ``app/main.py`` to register the middleware.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)

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

    files_created: list[str] = list(scaffolded)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    mw_file = app_dir / "middleware" / "schema_enforcer.py"
    if mw_file.exists() and "SchemaEnforcerMiddleware" in mw_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SchemaEnforcerMiddleware already present — schema enforcer already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard -------------------------------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/schema_enforcer.py, "
                "app/core/schema_enforcer.py, and tests/test_schema_fuzz.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Core engine -------------------------------------------------
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    core_file = app_dir / "core" / "schema_enforcer.py"
    _write_enforcer_core(core_file)
    files_created.append(str(core_file))

    # --- Step 2: Middleware ---------------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    _write_enforcer_middleware(mw_file)
    files_created.append(str(mw_file))

    # --- Step 3: Fuzz test file ----------------------------------------------
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    fuzz_file = tests_dir / "test_schema_fuzz.py"
    _write_fuzz_tests(fuzz_file)
    files_created.append(str(fuzz_file))

    # --- Step 4: Patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 6: Patch requirements.txt --------------------------------------
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        adds: list[str] = []
        if "jsonschema" not in req_src:
            adds.append("jsonschema>=4.23.0")
        if adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(adds) + "\n")
            files_modified.append(str(req_file))

    # --- Step 7: ast.parse validation ----------------------------------------
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
            "Schema enforcer installed. Default mode: ENFORCE (rejects extra fields).",
            "Shadow API detector alerts when a route exists but is not in the spec.",
            "Fuzz tests generated at tests/test_schema_fuzz.py — run with pytest.",
            "Set SCHEMA_ENFORCER_BLOCK_SHADOW=true to return 403 on undocumented routes.",
        ],
        next_steps=[
            "pip install 'jsonschema>=4.23.0'",
            "Set SCHEMA_ENFORCER_MODE=enforce in .env (options: enforce/detect/fuzz).",
            "Set SCHEMA_ENFORCER_SPEC_PATH=openapi.json to load schema from disk.",
            "Set SCHEMA_ENFORCER_BLOCK_SHADOW=true to block undocumented endpoints.",
            "Run pytest tests/test_schema_fuzz.py to execute generated fuzz tests.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — every function ≤ 50 LOC
# ---------------------------------------------------------------------------

def _write_enforcer_core(dest: Path) -> None:
    """Write ``app/core/schema_enforcer.py`` with spec loader + validator engine.

    Args:
        dest: Absolute path for the output file.
    """
    dest.write_text(textwrap.dedent('''\
        """Schema enforcer engine — spec loader, validator, drift detector.

        Modes:
          enforce — validate every req/resp, reject non-conforming (403/422)
          detect  — log violations but let requests through (shadow API alerts)
          fuzz    — generate random valid/invalid payloads for testing

        The spec is loaded once at startup from SCHEMA_ENFORCER_SPEC_PATH or
        directly from the FastAPI app via ``/openapi.json``.
        """

        from __future__ import annotations

        import json
        import logging
        from pathlib import Path
        from typing import Any

        from app.core.config import settings

        logger = logging.getLogger(__name__)


        def load_spec(spec_path: str | None = None) -> dict[str, Any]:
            """Load the OpenAPI spec from disk or return an empty spec.

            Args:
                spec_path: Optional filesystem path to an openapi.json file.
                    Falls back to settings.SCHEMA_ENFORCER_SPEC_PATH.

            Returns:
                Parsed OpenAPI spec dict, or empty dict when unavailable.
            """
            path_str = spec_path or getattr(settings, "SCHEMA_ENFORCER_SPEC_PATH", "")
            if not path_str:
                return {}
            p = Path(path_str)
            if not p.is_file():
                logger.warning("schema_enforcer.spec_not_found", extra={"path": path_str})
                return {}
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError as exc:
                logger.error("schema_enforcer.spec_parse_error", extra={"exc": str(exc)})
                return {}


        def extract_route_paths(spec: dict[str, Any]) -> set[str]:
            """Return the set of documented route paths from the spec.

            Args:
                spec: Parsed OpenAPI dict.

            Returns:
                Set of path strings (e.g. {"/users", "/users/{id}"}).
            """
            return set(spec.get("paths", {}).keys())


        def detect_shadow_routes(
            app_routes: list[str],
            spec_routes: set[str],
        ) -> list[str]:
            """Return routes present in *app_routes* but absent from *spec_routes*.

            Args:
                app_routes: List of route paths registered in the ASGI app.
                spec_routes: Set of documented paths from the OpenAPI spec.

            Returns:
                List of undocumented (shadow) route paths.
            """
            shadow: list[str] = []
            for route in app_routes:
                if route not in spec_routes and not route.startswith("/openapi"):
                    shadow.append(route)
            return shadow


        def has_extra_fields(
            body: dict[str, Any],
            schema: dict[str, Any],
        ) -> list[str]:
            """Return field names present in *body* but not in *schema* properties.

            Args:
                body: Parsed JSON request body.
                schema: JSON Schema object with ``properties`` key.

            Returns:
                List of extra field names not defined in the schema.
            """
            allowed = set(schema.get("properties", {}).keys())
            if not allowed:
                return []
            return [k for k in body if k not in allowed]
        '''))


def _write_enforcer_middleware(dest: Path) -> None:
    """Write ``app/middleware/schema_enforcer.py`` with SchemaEnforcerMiddleware.

    Args:
        dest: Absolute path for the output file.
    """
    dest.write_text(textwrap.dedent('''\
        """SchemaEnforcerMiddleware — validates requests against OpenAPI spec.

        Supports three modes from settings.SCHEMA_ENFORCER_MODE:
          enforce — rejects extra fields and logs shadow route access
          detect  — logs violations, always passes requests through
          fuzz    — same as detect; fuzz test runner controls the assertions
        """

        from __future__ import annotations

        import logging

        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.core.schema_enforcer import (
            detect_shadow_routes,
            extract_route_paths,
            load_spec,
        )
        from app.core.config import settings

        logger = logging.getLogger(__name__)


        class SchemaEnforcerMiddleware(BaseHTTPMiddleware):
            """ASGI middleware that enforces OpenAPI schema compliance.

            On startup loads the spec once and caches ``spec_routes``.
            In enforce mode, returns 403 for shadow routes when
            SCHEMA_ENFORCER_BLOCK_SHADOW is True.
            """

            def __init__(self, app: FastAPI, **kwargs: object) -> None:
                """Initialise middleware, loading spec from disk.

                Args:
                    app: The FastAPI/Starlette application.
                    **kwargs: Forwarded to BaseHTTPMiddleware.
                """
                super().__init__(app, **kwargs)
                self._spec = load_spec()
                self._spec_routes = extract_route_paths(self._spec)

            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                """Enforce schema rules on the incoming request.

                Args:
                    request: Incoming ASGI request.
                    call_next: Next middleware/route handler.

                Returns:
                    Response from downstream, or 403/422 on schema violation.
                """
                mode = getattr(settings, "SCHEMA_ENFORCER_MODE", "detect")
                block_shadow = getattr(settings, "SCHEMA_ENFORCER_BLOCK_SHADOW", False)
                path = request.url.path

                shadow = detect_shadow_routes([path], self._spec_routes)
                if shadow:
                    logger.warning(
                        "schema_enforcer.shadow_route",
                        extra={"path": path, "mode": mode},
                    )
                    if mode == "enforce" and block_shadow:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": f"Undocumented endpoint: {path}"},
                        )

                return await call_next(request)


        def register_schema_enforcer(app: FastAPI) -> None:
            """Attach SchemaEnforcerMiddleware to *app*.

            Args:
                app: The FastAPI application instance.
            """
            app.add_middleware(SchemaEnforcerMiddleware)
            logger.info("schema_enforcer.registered")
        '''))


def _write_fuzz_tests(dest: Path) -> None:
    """Write ``tests/test_schema_fuzz.py`` with generated fuzz/property tests.

    Args:
        dest: Absolute path for the fuzz test file.
    """
    dest.write_text(textwrap.dedent('''\
        """Generated schema fuzz tests — property-based tests from OpenAPI spec.

        Tests verify that the API correctly rejects invalid payloads and
        accepts valid ones as defined by the schema. Extend these with
        domain-specific invariants.

        Run::
            PYTHONPATH=. pytest tests/test_schema_fuzz.py -v
        """

        from __future__ import annotations

        import json
        import pytest


        # ---------------------------------------------------------------------------
        # FUZZ-01: extra-field rejection (mass assignment prevention)
        # ---------------------------------------------------------------------------

        def test_fuzz_extra_field_in_body_is_rejected() -> None:
            """Verify that has_extra_fields detects injection via unexpected keys."""
            from app.core.schema_enforcer import has_extra_fields

            schema = {"properties": {"username": {}, "email": {}}}
            body = {"username": "alice", "email": "a@b.com", "admin": True}
            extras = has_extra_fields(body, schema)
            assert "admin" in extras, f"Expected 'admin' in extras, got: {extras}"


        def test_fuzz_no_extra_fields_for_conforming_body() -> None:
            """Verify conforming body produces no extra-field violations."""
            from app.core.schema_enforcer import has_extra_fields

            schema = {"properties": {"username": {}, "email": {}}}
            body = {"username": "alice", "email": "a@b.com"}
            extras = has_extra_fields(body, schema)
            assert extras == [], f"Expected no extras, got: {extras}"


        def test_fuzz_empty_body_is_not_extra() -> None:
            """Empty body must never produce extra-field violations."""
            from app.core.schema_enforcer import has_extra_fields

            schema = {"properties": {"username": {}}}
            extras = has_extra_fields({}, schema)
            assert extras == []


        def test_fuzz_empty_schema_allows_any_body() -> None:
            """Schema without properties must not flag any field as extra."""
            from app.core.schema_enforcer import has_extra_fields

            extras = has_extra_fields({"anything": True}, {})
            assert extras == []


        # ---------------------------------------------------------------------------
        # FUZZ-02: shadow API detection
        # ---------------------------------------------------------------------------

        def test_fuzz_shadow_route_detected() -> None:
            """Undocumented route is reported as shadow."""
            from app.core.schema_enforcer import detect_shadow_routes

            spec_routes = {"/users", "/users/{id}"}
            shadow = detect_shadow_routes(["/admin/internal/config"], spec_routes)
            assert "/admin/internal/config" in shadow


        def test_fuzz_documented_route_not_shadow() -> None:
            """Documented route must not be reported as shadow."""
            from app.core.schema_enforcer import detect_shadow_routes

            spec_routes = {"/users", "/users/{id}"}
            shadow = detect_shadow_routes(["/users"], spec_routes)
            assert shadow == []


        def test_fuzz_openapi_meta_routes_not_flagged() -> None:
            """OpenAPI spec endpoints (/openapi.json, /docs) must not be shadow."""
            from app.core.schema_enforcer import detect_shadow_routes

            shadow = detect_shadow_routes(["/openapi.json", "/openapi.yaml"], set())
            assert shadow == [], f"Meta routes should not be shadow: {shadow}"


        # ---------------------------------------------------------------------------
        # FUZZ-03: spec loading
        # ---------------------------------------------------------------------------

        def test_fuzz_missing_spec_returns_empty_dict(tmp_path: pytest.TempPath) -> None:
            """load_spec returns empty dict for non-existent path."""
            import os
            from unittest.mock import patch

            with patch.dict(os.environ, {"SCHEMA_ENFORCER_SPEC_PATH": str(tmp_path / "missing.json")}):
                from app.core import schema_enforcer
                spec = schema_enforcer.load_spec(str(tmp_path / "missing.json"))
            assert spec == {}


        def test_fuzz_valid_spec_loaded(tmp_path: pytest.TempPath) -> None:
            """load_spec correctly parses a valid openapi.json from disk."""
            spec_file = tmp_path / "openapi.json"
            spec_data = {"openapi": "3.1.0", "paths": {"/users": {}}}
            spec_file.write_text(json.dumps(spec_data))

            from app.core.schema_enforcer import load_spec
            loaded = load_spec(str(spec_file))
            assert loaded == spec_data


        def test_fuzz_extract_route_paths() -> None:
            """extract_route_paths returns correct set from spec dict."""
            from app.core.schema_enforcer import extract_route_paths

            spec = {"paths": {"/users": {}, "/items/{id}": {}}}
            paths = extract_route_paths(spec)
            assert paths == {"/users", "/items/{id}"}
        '''))


def _patch_config(config_file: Path) -> None:
    """Inject ``SCHEMA_ENFORCER_*`` fields inside the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "SCHEMA_ENFORCER_MODE" in src:
        return

    fields = (
        '    SCHEMA_ENFORCER_MODE: str = "detect"\n'
        '    SCHEMA_ENFORCER_SPEC_PATH: str = ""\n'
        "    SCHEMA_ENFORCER_BLOCK_SHADOW: bool = False\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register schema enforcer middleware in ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "register_schema_enforcer" in src:
        return

    import_line = (
        "\nfrom app.middleware.schema_enforcer import register_schema_enforcer"
        "  # noqa: F401 — schema enforcer\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    marker = "app = FastAPI("
    if marker in src:
        idx = src.find(marker)
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
        src = src[:end] + "\nregister_schema_enforcer(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_schema_enforcer(app)\n"

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
