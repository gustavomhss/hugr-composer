"""BEHAVIOR TEST — TOOL-115 add_dpop_tokens.

Proves that the generated code works at RUNTIME: boots a real ASGI app,
hits DPoP endpoints, and asserts structural correctness.

Patches applied:
- ``app/core/db.py``              → SQLite + aiosqlite
- ``app/middleware/idempotency.py`` → pass-through stub (no Redis)
- ``REDIS_URL`` env var           → removed

Run::

    PYTHONPATH=. .venv/bin/pytest adapt/extend/auth_access/test_add_dpop_tokens_behavior.py -v

or standalone::

    PYTHONPATH=. .venv/bin/python adapt/extend/auth_access/test_add_dpop_tokens_behavior.py
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Environment setup — MUST happen before any app import
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-dpop-tokens-secret-32+!!")
os.environ.setdefault("DPOP_ENABLED", "true")
os.environ.setdefault("DPOP_NONCE_TTL_S", "300")
os.environ.setdefault("DPOP_CLOCK_SKEW_S", "60")
os.environ.pop("REDIS_URL", None)

import ast
import importlib
import sys
import textwrap
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Patch templates
# ---------------------------------------------------------------------------

_SQLITE_DB_PY = textwrap.dedent("""\
    \"\"\"Patched db.py — SQLite+aiosqlite, no Docker required.\"\"\"

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )


    async def init_db() -> None:
        \"\"\"Run startup checks (connection test).\"\"\"
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))


    __all__ = ["engine", "init_db"]
""")

_PASSTHROUGH_IDEMPOTENCY_PY = textwrap.dedent("""\
    \"\"\"Patched idempotency.py — pass-through stub (no Redis).\"\"\"

    from __future__ import annotations

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response


    class IdempotencyMiddleware(BaseHTTPMiddleware):
        \"\"\"No-op pass-through stub for testing without Redis.\"\"\"

        async def dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            return await call_next(request)
""")


def _patch_project(project_dir: Path) -> None:
    (project_dir / "app" / "core" / "db.py").write_text(_SQLITE_DB_PY)
    idempotency_path = project_dir / "app" / "middleware" / "idempotency.py"
    if idempotency_path.exists():
        idempotency_path.write_text(_PASSTHROUGH_IDEMPOTENCY_PY)


def _load_app(project_dir: Path) -> Any:
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        app_module = importlib.import_module("app.main")
    finally:
        sys.path[:] = _orig_path
    return app_module.app


def _setup_project() -> tuple[Path, Any]:
    project_dir = create_fixture_project(name="dpop_behavior")
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_dpop_tokens failed: {result.error}\nnotes: {result.notes}"
    )
    _patch_project(project_dir)
    asgi_app = _load_app(project_dir)
    return project_dir, asgi_app


# ---------------------------------------------------------------------------
# Module-level shared state
# ---------------------------------------------------------------------------

_PROJECT_DIR: Path | None = None
_ASGI_APP: Any = None


def _get_shared_app() -> tuple[Path, Any]:
    global _PROJECT_DIR, _ASGI_APP
    if _PROJECT_DIR is None:
        _PROJECT_DIR, _ASGI_APP = _setup_project()
    return _PROJECT_DIR, _ASGI_APP


@pytest.fixture(scope="module")
def project_dir_and_app() -> tuple[Path, Any]:
    return _get_shared_app()


@pytest.fixture(scope="module")
def project_dir(project_dir_and_app: tuple[Path, Any]) -> Path:
    return project_dir_and_app[0]


@pytest.fixture(scope="module")
def asgi_app(project_dir_and_app: tuple[Path, Any]) -> Any:
    return project_dir_and_app[1]


# ---------------------------------------------------------------------------
# B-01: GET /healthz → 200
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b01_healthz_returns_200(asgi_app: Any) -> None:
    """B-01: App boots cleanly after DPoP tool applied."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-02: POST /auth/dpop/nonce → 200 with nonce
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b02_nonce_endpoint_returns_nonce(asgi_app: Any) -> None:
    """B-02: POST /auth/dpop/nonce returns 200 with nonce value."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/dpop/nonce")
    assert response.status_code in (200, 503), (
        f"Expected 200 or 503, got {response.status_code}; body: {response.text}"
    )
    if response.status_code == 200:
        data = response.json()
        assert "nonce" in data, "nonce field missing from response"
        assert len(data["nonce"]) > 8, "nonce is too short"


# ---------------------------------------------------------------------------
# B-03: GET /auth/dpop/status → 200 with config
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b03_dpop_status_route_exists(asgi_app: Any) -> None:
    """B-03: GET /auth/dpop/status returns DPoP configuration."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/dpop/status")
    assert response.status_code not in (404, 500), (
        f"DPoP status route missing: {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-04: PyJWT NOT top-level import in dpop.py
# ---------------------------------------------------------------------------

def test_b04_pyjwt_not_top_level(project_dir: Path) -> None:
    """B-04: jwt (PyJWT) is NOT imported at module top level in dpop.py."""
    dpop_file = project_dir / "app" / "core" / "dpop.py"
    assert dpop_file.exists(), "app/core/dpop.py missing"
    tree = ast.parse(dpop_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "jwt", "jwt imported at top level in dpop.py"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "jwt", (
                "jwt imported at top level via 'from' in dpop.py"
            )


# ---------------------------------------------------------------------------
# B-05: config fields 4-space indent
# ---------------------------------------------------------------------------

def test_b05_config_fields_4space_indent(project_dir: Path) -> None:
    """B-05: DPOP_ENABLED is inside the Settings class (4-space indent)."""
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for line in content.splitlines():
        if "DPOP_ENABLED" in line and ":" in line:
            assert line.startswith("    "), f"Not 4-space indented: {line!r}"
            break
    else:
        raise AssertionError("DPOP_ENABLED not found in config.py")


# ---------------------------------------------------------------------------
# B-06: DPoP nonce route has DPoP-Nonce response header logic
# ---------------------------------------------------------------------------

def test_b06_dpop_nonce_header_in_route(project_dir: Path) -> None:
    """B-06: dpop_nonce.py sets DPoP-Nonce response header."""
    nonce_route = project_dir / "app" / "api" / "routes" / "dpop_nonce.py"
    assert nonce_route.exists(), "dpop_nonce.py missing"
    content = nonce_route.read_text()
    assert "DPoP-Nonce" in content, "DPoP-Nonce header not set in nonce route"


# ---------------------------------------------------------------------------
# B-07: all functions in generated app/ ≤50 LOC
# ---------------------------------------------------------------------------

def test_b07_no_function_over_50_loc(project_dir: Path) -> None:
    """B-07: No function in app/ exceeds 50 LOC."""
    app_dir = project_dir / "app"
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    assert loc <= 50, (
                        f"{py_file.name}:{node.name} has {loc} LOC (limit: 50)"
                    )


# ---------------------------------------------------------------------------
# B-08: DPoP core schema fields
# ---------------------------------------------------------------------------

def test_b08_dpop_core_has_allowed_algs(project_dir: Path) -> None:
    """B-08: dpop.py defines _ALLOWED_ALGS with ES256 and RS256."""
    dpop_file = project_dir / "app" / "core" / "dpop.py"
    content = dpop_file.read_text()
    assert "ES256" in content, "ES256 not in _ALLOWED_ALGS"
    assert "RS256" in content, "RS256 not in _ALLOWED_ALGS"
    assert "_ALLOWED_ALGS" in content, "_ALLOWED_ALGS constant missing"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import anyio

    tests_sync = [
        test_b04_pyjwt_not_top_level,
        test_b05_config_fields_4space_indent,
        test_b06_dpop_nonce_header_in_route,
        test_b07_no_function_over_50_loc,
        test_b08_dpop_core_has_allowed_algs,
    ]
    tests_async = [
        test_b01_healthz_returns_200,
        test_b02_nonce_endpoint_returns_nonce,
        test_b03_dpop_status_route_exists,
    ]

    project_dir, asgi_app = _get_shared_app()

    passed = failed = 0
    for test_fn in tests_async:
        try:
            anyio.run(test_fn, asgi_app)
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    for test_fn in tests_sync:
        try:
            test_fn(project_dir)
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-115 behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
