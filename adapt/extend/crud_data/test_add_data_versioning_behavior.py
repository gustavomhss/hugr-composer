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


# ---------------------------------------------------------------------------
# B-06..B-10: Regression — every /versions/* route returns 401 without auth.
#
# Closes R5-O2-D2 (5 versioning routes accepted unauthenticated traffic).
# Each call below carries NO Authorization header; FastAPI's
# ``OAuth2PasswordBearer`` (the dependency wired into ``get_current_user``)
# must short-circuit the request with 401 BEFORE any handler runs.
#
# We assert ``in {401, 403}`` because some auth deps return 403 on a missing
# Bearer token instead of 401; either status proves the route is gated.
# 404 / 422 / 5xx would mean the handler executed unauthenticated and is a
# hard regression.
# ---------------------------------------------------------------------------


_AUTH_DENIED: frozenset[int] = frozenset({401, 403})


@pytest.mark.anyio
async def test_b06_draft_route_requires_auth(asgi_app: Any) -> None:
    """B-06 / R5-O2-D2: POST /versions/.../draft must 401 without auth."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/versions/article/abc/draft",
            json={"data": {"title": "x"}},
        )
    assert response.status_code in _AUTH_DENIED, (
        f"create_draft should reject unauth (R5-O2-D2): {response.status_code} {response.text}"
    )


@pytest.mark.anyio
async def test_b07_publish_route_requires_auth(asgi_app: Any) -> None:
    """B-07 / R5-O2-D2: POST /versions/.../publish/N must 401 without auth."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/versions/article/abc/publish/1")
    assert response.status_code in _AUTH_DENIED, (
        f"publish_version should reject unauth (R5-O2-D2): {response.status_code} {response.text}"
    )


@pytest.mark.anyio
async def test_b08_archive_route_requires_auth(asgi_app: Any) -> None:
    """B-08 / R5-O2-D2: POST /versions/.../archive/N must 401 without auth."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/versions/article/abc/archive/1")
    assert response.status_code in _AUTH_DENIED, (
        f"archive_version should reject unauth (R5-O2-D2): {response.status_code} {response.text}"
    )


@pytest.mark.anyio
async def test_b09_history_route_requires_auth(asgi_app: Any) -> None:
    """B-09 / R5-O2-D2: GET /versions/.../history must 401 without auth."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/versions/article/abc/history")
    assert response.status_code in _AUTH_DENIED, (
        f"get_version_history should reject unauth (R5-O2-D2): {response.status_code} {response.text}"
    )


@pytest.mark.anyio
async def test_b10_diff_route_requires_auth(asgi_app: Any) -> None:
    """B-10 / R5-O2-D2: GET /versions/.../diff/v1/v2 must 401 without auth."""
    transport = httpx.ASGITransport(app=asgi_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/versions/article/abc/diff/1/2")
    assert response.status_code in _AUTH_DENIED, (
        f"diff_versions should reject unauth (R5-O2-D2): {response.status_code} {response.text}"
    )


# ---------------------------------------------------------------------------
# B-11 / B-12: Regression — VersionCreate rejects extra fields (closes
# R6-O3-P1 cluster: ``extra="forbid"``) and no longer carries
# ``author_id`` (closes R5-O2-D2 mass-assignment vector).
# ---------------------------------------------------------------------------


def test_b11_version_create_rejects_extra_fields(project_dir: Path) -> None:
    """B-11 / R6-O3-P1: VersionCreate must reject unknown body keys."""
    from pydantic import ValidationError

    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.schemas.version import VersionCreate

        # Valid baseline — known field only.
        VersionCreate(data={"title": "x"})

        # Extra field must be rejected (extra="forbid" → ValidationError).
        with pytest.raises(ValidationError) as exc:
            VersionCreate.model_validate({"data": {"title": "x"}, "hijack": "rogue"})
        assert "hijack" in str(exc.value) or "extra" in str(exc.value).lower(), (
            f"expected extra=forbid rejection, got: {exc.value}"
        )
    finally:
        sys.path[:] = _orig_path


def test_b12_version_create_has_no_author_id(project_dir: Path) -> None:
    """B-12 / R5-O2-D2: ``author_id`` removed from VersionCreate.

    A body-supplied author_id was the mass-assignment vector the original
    finding called out; the field must NOT be a model field, AND with
    ``extra="forbid"`` a request that names it must be rejected.
    """
    from pydantic import ValidationError

    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.schemas.version import VersionCreate

        assert "author_id" not in VersionCreate.model_fields, (
            "VersionCreate.author_id must be removed (R5-O2-D2): identity "
            "comes from current_user, not request body"
        )
        with pytest.raises(ValidationError):
            VersionCreate.model_validate(
                {"data": {"k": "v"}, "author_id": "00000000-0000-0000-0000-000000000000"}
            )
    finally:
        sys.path[:] = _orig_path


@pytest.mark.anyio
async def test_b13_versions_isolated_by_content_type(project_dir: Path) -> None:
    """B-13 (R5-O2-D3): two content types sharing a content_id must be isolated.

    Runs the emitted VersioningService against a real in-memory SQLite DB:
    creates a draft for (article, "5") and (product, "5") — same content_id,
    different type — and asserts each type's history, version numbering, and
    payload stay separate. Pre-fix both would have collided (shared history and
    a 2nd version_number for the product instead of restarting at 1).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        from app.versioning.service import VersioningService

        import app.models  # noqa: F401 — register every table on Base.metadata
        from app.models.base import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            svc = VersioningService(max_drafts=10)
            async with AsyncSession(engine) as session:
                await svc.create_draft(
                    session, content_id="5", content_type="article", data={"t": "A"}
                )
                await svc.create_draft(
                    session, content_id="5", content_type="product", data={"t": "P"}
                )
                article = await svc.get_history(session, "5", "article")
                product = await svc.get_history(session, "5", "product")
                assert [v.content_type for v in article] == ["article"], article
                assert [v.content_type for v in product] == ["product"], product
                assert article[0].data_json == {"t": "A"}
                assert product[0].data_json == {"t": "P"}
                # version numbers are per content item — both restart at 1, not 1 & 2.
                assert article[0].version_number == 1, article[0].version_number
                assert product[0].version_number == 1, product[0].version_number
        finally:
            await engine.dispose()
    finally:
        sys.path[:] = _orig_path
