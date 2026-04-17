"""Behavior test for TOOL-064 add_feature_toggles_api.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub

Then fires real HTTP requests via ASGI transport to verify the feature
toggle endpoints behave correctly end-to-end.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_feature_toggles_api_behavior.py -v

or::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_feature_toggles_api_behavior.py
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Set env vars BEFORE importing the app (avoids Settings validation errors)
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-key-for-feature-toggles-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

import asyncio
import pytest

# ---------------------------------------------------------------------------
# Shared fixture setup (module-level so we build the project once)
# ---------------------------------------------------------------------------

_TMPDIR: tempfile.TemporaryDirectory | None = None
_PROJECT_DIR: Path | None = None


def _build_project() -> Path:
    """Generate fixture project and apply the tool once.

    Returns:
        Path to the generated project root.
    """
    global _TMPDIR, _PROJECT_DIR
    if _PROJECT_DIR is not None:
        return _PROJECT_DIR

    from tests.common.fixture_factory import create_fixture_project
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_feature_toggles_api import add_feature_toggles_api

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="ft_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_feature_toggles_api failed: {result.error}")

    _PROJECT_DIR = project_dir
    return project_dir


def _load_app(project_dir: Path):
    """Load the FastAPI app from a generated project, clearing module cache.

    Args:
        project_dir: Path to the project root.

    Returns:
        FastAPI application instance.
    """
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    # Clear all app.* modules so each test gets a fresh import
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    # Import models __init__ to register all ORM models with Base.metadata
    importlib.import_module("app.models")
    return importlib.import_module("app.main").app


async def _make_sqlite_client(project_dir: Path):
    """Create an ASGI test client backed by SQLite in-memory.

    Patches ``app.core.session.get_session`` to yield from a single
    session that shares the SQLite in-memory engine.  Creates all tables
    from Base.metadata so no Alembic run is needed.

    Args:
        project_dir: Path to the project root.

    Returns:
        Tuple of (AsyncClient, AsyncSession, AsyncEngine, app).
    """
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        async_sessionmaker,
        AsyncSession,
    )
    from httpx import ASGITransport, AsyncClient

    app = _load_app(project_dir)
    get_session_mod = importlib.import_module("app.core.session")
    base_mod = importlib.import_module("app.models.base")

    engine = create_async_engine("sqlite+aiosqlite://", echo=False, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(base_mod.Base.metadata.create_all)

    session = factory()

    async def _override():
        yield session

    app.dependency_overrides[get_session_mod.get_session] = _override

    # Disable idempotency middleware if present (requires Redis)
    try:
        idempotency_mod = importlib.import_module("app.middleware.idempotency")
        from starlette.middleware.base import BaseHTTPMiddleware

        class _PassThrough(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                return await call_next(request)

        if hasattr(idempotency_mod, "IdempotencyMiddleware"):
            idempotency_mod.IdempotencyMiddleware = _PassThrough
    except (ModuleNotFoundError, AttributeError):
        pass

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, session, engine, app


async def _teardown(app, client, session, engine) -> None:
    """Clean up client, session, engine and dependency overrides.

    Args:
        app: FastAPI application.
        client: httpx AsyncClient.
        session: SQLAlchemy AsyncSession.
        engine: SQLAlchemy AsyncEngine.
    """
    await client.aclose()
    await session.close()
    from app.models.base import Base  # type: ignore[import]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    app.dependency_overrides.clear()


async def _create_superuser(session) -> dict[str, str]:
    """Insert a superuser row and return {'email': ..., 'password': ...}.

    Args:
        session: SQLAlchemy AsyncSession.

    Returns:
        Dict with email and password for the new superuser.
    """
    security_mod = importlib.import_module("app.core.security")
    user_model_mod = importlib.import_module("app.models.user")
    email = "admin@toggletest.local"
    password = "Admin1234!"
    su = user_model_mod.User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=security_mod.get_password_hash(password),
        full_name="Toggle Admin",
        is_active=True,
        is_superuser=True,
    )
    session.add(su)
    await session.commit()
    return {"email": email, "password": password}


async def _login(client, email: str, password: str) -> str:
    """Log in and return a JWT access token.

    Args:
        client: httpx AsyncClient.
        email: User email.
        password: User password.

    Returns:
        JWT access token string.
    """
    r = await client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_beh_01_app_boots() -> None:
    """BEH-01: App boots cleanly with feature toggles tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_create_toggle() -> None:
    """BEH-02: POST /feature-toggles creates a new toggle and returns 201."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        payload = {
            "name": "new_dashboard",
            "enabled": True,
            "rollout_percentage": 100,
            "allowed_users": [],
            "environments": [],
        }
        r = await client.post("/api/v1/feature-toggles/", json=payload, headers=h)
        assert r.status_code == 201, f"create toggle: {r.status_code} {r.text}"
        body = r.json()
        assert body["name"] == "new_dashboard"
        assert body["enabled"] is True
        assert "id" in body
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_list_toggles() -> None:
    """BEH-03: GET /feature-toggles returns the created toggle."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "list_me", "enabled": False, "rollout_percentage": 50,
        }, headers=h)

        r = await client.get("/api/v1/feature-toggles/", headers=h)
        assert r.status_code == 200, f"list toggles: {r.status_code} {r.text}"
        body = r.json()
        assert isinstance(body, list)
        names = [t["name"] for t in body]
        assert "list_me" in names
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_update_toggle() -> None:
    """BEH-04: PUT /feature-toggles/{name} updates the toggle."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "update_me", "enabled": False, "rollout_percentage": 0,
        }, headers=h)

        r = await client.put("/api/v1/feature-toggles/update_me", json={"enabled": True, "rollout_percentage": 75}, headers=h)
        assert r.status_code == 200, f"update toggle: {r.status_code} {r.text}"
        body = r.json()
        assert body["enabled"] is True
        assert body["rollout_percentage"] == 75
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_delete_toggle() -> None:
    """BEH-05: DELETE /feature-toggles/{name} removes the toggle, GET after returns 404."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "delete_me", "enabled": True, "rollout_percentage": 100,
        }, headers=h)

        r = await client.delete("/api/v1/feature-toggles/delete_me", headers=h)
        assert r.status_code == 204, f"delete toggle: {r.status_code} {r.text}"

        # Attempting to update a deleted toggle → 404
        r2 = await client.put("/api/v1/feature-toggles/delete_me", json={"enabled": False}, headers=h)
        assert r2.status_code == 404
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_evaluate_enabled_toggle() -> None:
    """BEH-06: POST /{name}/evaluate returns enabled=True for an active toggle."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "active_feat", "enabled": True, "rollout_percentage": 100,
        }, headers=h)

        r = await client.post(
            "/api/v1/feature-toggles/active_feat/evaluate",
            json={"user_id": "user-abc", "environment": "production"},
            headers=h,
        )
        assert r.status_code == 200, f"evaluate: {r.status_code} {r.text}"
        body = r.json()
        assert body["enabled"] is True
        assert body["name"] == "active_feat"
        assert "reason" in body
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_07_evaluate_disabled_toggle() -> None:
    """BEH-07: POST /{name}/evaluate returns enabled=False for a disabled toggle."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "off_feat", "enabled": False, "rollout_percentage": 100,
        }, headers=h)

        r = await client.post(
            "/api/v1/feature-toggles/off_feat/evaluate",
            json={"user_id": "user-xyz", "environment": "production"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["reason"] == "disabled"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_08_evaluate_allowlist() -> None:
    """BEH-08: User in allowed_users is enabled regardless of rollout_percentage=0."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "vip_feat",
            "enabled": True,
            "rollout_percentage": 0,
            "allowed_users": ["vip-user-001"],
        }, headers=h)

        r = await client.post(
            "/api/v1/feature-toggles/vip_feat/evaluate",
            json={"user_id": "vip-user-001", "environment": "production"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["reason"] == "allowlist"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_09_evaluate_environment_gate() -> None:
    """BEH-09: Environment gate blocks when env not in allowed list."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "staging_feat",
            "enabled": True,
            "rollout_percentage": 100,
            "environments": ["staging"],
        }, headers=h)

        r = await client.post(
            "/api/v1/feature-toggles/staging_feat/evaluate",
            json={"user_id": "user-prod", "environment": "production"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["reason"] == "environment_gate"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_10_evaluate_missing_toggle_404() -> None:
    """BEH-10: Evaluate on a non-existent toggle returns 404."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        r = await client.post(
            "/api/v1/feature-toggles/nonexistent_flag/evaluate",
            json={"user_id": "u1", "environment": "production"},
            headers=h,
        )
        assert r.status_code == 404
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_11_create_duplicate_409() -> None:
    """BEH-11: Creating a toggle with a duplicate name returns 409."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        payload = {"name": "dup_toggle", "enabled": False, "rollout_percentage": 0}
        await client.post("/api/v1/feature-toggles/", json=payload, headers=h)
        r2 = await client.post("/api/v1/feature-toggles/", json=payload, headers=h)
        assert r2.status_code == 409
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_12_openapi_has_toggle_paths() -> None:
    """BEH-12: OpenAPI schema includes /feature-toggles paths."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        toggle_paths = [p for p in paths if "feature-toggle" in p]
        assert len(toggle_paths) >= 1, f"No feature-toggle paths in OpenAPI: {list(paths.keys())[:20]}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_13_rollout_deterministic() -> None:
    """BEH-13: Same user + toggle always maps to the same evaluation result."""
    from adapt.extend.auth_access.add_feature_toggles_api import _write_toggle_evaluator
    import tempfile
    # Import the generated evaluator from any built project
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        creds = await _create_superuser(session)
        token = await _login(client, creds["email"], creds["password"])
        h = _auth(token)

        await client.post("/api/v1/feature-toggles/", json={
            "name": "deterministic_feat",
            "enabled": True,
            "rollout_percentage": 50,
        }, headers=h)

        results = []
        for _ in range(5):
            r = await client.post(
                "/api/v1/feature-toggles/deterministic_feat/evaluate",
                json={"user_id": "stable-user-001", "environment": "production"},
                headers=h,
            )
            assert r.status_code == 200
            results.append(r.json()["enabled"])

        # All evaluations for the same user must be identical (deterministic)
        assert len(set(results)) == 1, f"Non-deterministic results: {results}"
    finally:
        await _teardown(app, client, session, engine)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_beh_01_app_boots,
        test_beh_02_create_toggle,
        test_beh_03_list_toggles,
        test_beh_04_update_toggle,
        test_beh_05_delete_toggle,
        test_beh_06_evaluate_enabled_toggle,
        test_beh_07_evaluate_disabled_toggle,
        test_beh_08_evaluate_allowlist,
        test_beh_09_evaluate_environment_gate,
        test_beh_10_evaluate_missing_toggle_404,
        test_beh_11_create_duplicate_409,
        test_beh_12_openapi_has_toggle_paths,
        test_beh_13_rollout_deterministic,
    ]
    passed = failed = 0
    for t in tests:
        try:
            asyncio.run(t())
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)
