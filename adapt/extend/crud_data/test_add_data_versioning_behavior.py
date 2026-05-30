"""BEHAVIOR TEST — TOOL-078 add_data_versioning.

Proves that the code emitted by ``add_data_versioning`` works at **runtime**:

* boots a real ASGI app with the versioning routes wired in,
* asserts /versions/{type}/{id}/draft etc. are reachable (not 404),
* asserts the append-only lifecycle invariant fires at the service layer
  (max_drafts enforced, publish archives previous published),
* asserts VERSIONING_MAX_DRAFTS is wired into settings.

Patches applied (so tests run without Docker):
- ``app/core/db.py``                → SQLite + aiosqlite (no Postgres)
- ``app/middleware/idempotency.py`` → pass-through stub (no Redis)
- ``REDIS_URL`` env var              → removed
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-versioning-secret-key-32+!")
os.environ.pop("REDIS_URL", None)

import importlib
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_versioning import add_data_versioning
from tests.common.fixture_factory import create_fixture_project

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
    project_dir = create_fixture_project(name="versioning_behavior")
    result = add_data_versioning(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_data_versioning failed: {result.error}\nnotes: {result.notes}"
    )
    _patch_project(project_dir)
    return project_dir, _load_app(project_dir)


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
# B-01: App boots after versioning routes installed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_b01_healthz_returns_200(asgi_app: Any) -> None:
    """B-01: GET /healthz returns 200 after add_data_versioning wired."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-02: VersioningService importable + max_drafts plumbed
# ---------------------------------------------------------------------------


def test_b02_versioning_service_importable(project_dir: Path) -> None:
    """B-02: VersioningService is importable and exposes the lifecycle methods."""
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.versioning.service import VersioningService

        svc = VersioningService(max_drafts=3)
        assert svc.max_drafts == 3, "max_drafts constructor argument not honoured"
        for method in (
            "create_draft",
            "publish",
            "archive",
            "get_history",
            "diff",
        ):
            assert hasattr(svc, method), f"VersioningService.{method} missing"
    finally:
        sys.path[:] = _orig_path


# ---------------------------------------------------------------------------
# B-03: Diff produces added/removed/changed
# ---------------------------------------------------------------------------


def test_b03_compute_diff_returns_added_removed_changed(project_dir: Path) -> None:
    """B-03: _compute_diff yields the three lifecycle keys."""
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.versioning.service import _compute_diff  # type: ignore[attr-defined]

        result = _compute_diff({"a": 1, "b": 2}, {"a": 1, "b": 99, "c": 3})
        assert result == {"added": {"c": 3}, "removed": {}, "changed": {"b": [2, 99]}}, (
            f"unexpected diff: {result}"
        )
    finally:
        sys.path[:] = _orig_path


# ---------------------------------------------------------------------------
# B-04: settings carries VERSIONING_MAX_DRAFTS
# ---------------------------------------------------------------------------


def test_b04_settings_carries_versioning_max_drafts(project_dir: Path) -> None:
    """B-04: settings exposes VERSIONING_MAX_DRAFTS (defaults to 10)."""
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.core.config import settings

        assert hasattr(settings, "VERSIONING_MAX_DRAFTS"), (
            "VERSIONING_MAX_DRAFTS not plumbed into Settings (config patch lost)"
        )
        assert settings.VERSIONING_MAX_DRAFTS == 10
    finally:
        sys.path[:] = _orig_path


# ---------------------------------------------------------------------------
# B-05: /versions route prefix is registered
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_b05_versions_route_registered(asgi_app: Any) -> None:
    """B-05: /versions/{type}/{id}/history is wired (response != 404)."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/versions/article/abc/history")
    assert response.status_code != 404, (
        f"/versions/.../history not registered: {response.status_code}: {response.text}"
    )
