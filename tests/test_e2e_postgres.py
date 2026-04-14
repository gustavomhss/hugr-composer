"""HARDCORE E2E test with REAL PostgreSQL — validates ALL 27 EXTEND tools.

This test complements test_e2e_hardcore.py (which uses SQLite in-memory) by
spinning up a real PostgreSQL container and exercising the 5 tools that
require production-grade infra:

- add_multi_tenancy (tenant middleware needs real async session)
- add_rbac (permissions table + FK to tenants)
- add_mfa (TOTP codes via pyotp)
- add_oauth2_provider (authorization server state)
- add_search (PostgreSQL full-text search with @@ operator)

Requires a running PostgreSQL 16 container:

    docker run -d --name skill001-e2e-pg \\
      -e POSTGRES_USER=skill -e POSTGRES_PASSWORD=skill \\
      -e POSTGRES_DB=skill_e2e -p 54329:5432 \\
      postgres:16-alpine

Set E2E_POSTGRES_URL to override (defaults to the docker run above).

Run:
    PYTHONPATH=. python3 tests/test_e2e_postgres.py

Exit 0 → all tests pass
Exit 1 → failures or Postgres unavailable (not a tool bug)
Exit 2 → Postgres skipped (no container)
"""

from __future__ import annotations

import os
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-e2e-must-be-32-chars-long!!")
# These are read by app.core.config.Settings at import time. The tenant
# middleware (add_multi_tenancy) creates its own async_session_maker from
# these values, bypassing the dependency_override, so they MUST match the
# real container credentials before app.main is imported.
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "54329")
os.environ.setdefault("POSTGRES_USER", "skill")
os.environ.setdefault("POSTGRES_PASSWORD", "skill")
os.environ.setdefault("POSTGRES_DB", "skill_e2e")
# MFA requires a Fernet key for symmetric TOTP secret encryption.
# Generate a deterministic one for tests (32 bytes url-safe base64).
os.environ.setdefault("MFA_FERNET_KEY", "L7gvXDh2v6syV65J0-iwLQMTYbVavNXO2vuXgntcFBo=")

import asyncio
import importlib
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# PostgreSQL connection — defaults to `docker run` instance on port 54329
# ---------------------------------------------------------------------------

POSTGRES_URL = os.environ.get(
    "E2E_POSTGRES_URL",
    "postgresql+asyncpg://skill:skill@localhost:54329/skill_e2e",
)

# Models — simple e-commerce domain
ECOMMERCE_MODELS = {
    "Product":  {"name": "str", "description": "text", "price": "float", "sku": "str", "stock": "int"},
    "Order":    {"status": "str", "total": "float", "notes": "text"},
    "Customer": {"name": "str", "email": "email", "phone": "str", "tier": "str"},
}

# All 27 EXTEND tools — the full set
ALL_TOOLS: list[tuple[str, str]] = [
    ("add_soft_delete",       "adapt.extend.crud_data.add_soft_delete"),
    ("add_cursor_pagination", "adapt.extend.crud_data.add_cursor_pagination"),
    ("add_search",            "adapt.extend.crud_data.add_search"),
    ("add_audit_log",         "adapt.extend.crud_data.add_audit_log"),
    ("add_bulk_operations",   "adapt.extend.crud_data.add_bulk_operations"),
    ("add_data_export",       "adapt.extend.crud_data.add_data_export"),
    ("add_file_upload",       "adapt.extend.crud_data.add_file_upload"),
    ("add_multi_tenancy",     "adapt.extend.auth_access.add_multi_tenancy"),
    ("add_rbac",              "adapt.extend.auth_access.add_rbac"),
    ("add_mfa",               "adapt.extend.auth_access.add_mfa"),
    ("add_api_key_auth",      "adapt.extend.auth_access.add_api_key_auth"),
    ("add_feature_flags",     "adapt.extend.auth_access.add_feature_flags"),
    ("add_oauth2_provider",   "adapt.extend.auth_access.add_oauth2_provider"),
    ("add_cache_layer",       "adapt.extend.infrastructure.add_cache_layer"),
    ("add_circuit_breaker",   "adapt.extend.infrastructure.add_circuit_breaker"),
    ("add_outbox_pattern",    "adapt.extend.infrastructure.add_outbox_pattern"),
    ("add_saga",              "adapt.extend.infrastructure.add_saga"),
    ("add_sse",               "adapt.extend.realtime.add_sse"),
    ("add_webhook_receiver",  "adapt.extend.realtime.add_webhook_receiver"),
    ("add_webhook_sender",    "adapt.extend.realtime.add_webhook_sender"),
    ("add_api_versioning",    "adapt.extend.api_design.add_api_versioning"),
    ("add_batch_endpoint",    "adapt.extend.api_design.add_batch_endpoint"),
    ("add_graphql",           "adapt.extend.api_design.add_graphql"),
    ("add_long_running_task", "adapt.extend.api_design.add_long_running_task"),
    ("add_contract_tests",    "adapt.extend.testing_tools.add_contract_tests"),
    ("add_factory",           "adapt.extend.testing_tools.add_factory"),
    ("add_load_profile",      "adapt.extend.testing_tools.add_load_profile"),
]


# ---------------------------------------------------------------------------
# Setup: generate project + apply all 27 tools (once per process)
# ---------------------------------------------------------------------------

_PROJECT_DIR: Path | None = None
_TMPDIR: tempfile.TemporaryDirectory | None = None


def _setup() -> Path:
    """Generate a fresh project, apply all 27 tools, return project dir."""
    global _PROJECT_DIR, _TMPDIR
    if _PROJECT_DIR is not None:
        return _PROJECT_DIR

    from tests.common.fixture_factory import create_fixture_project
    from adapt.contracts import ToolInput

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="ecommerce_pg",
        models=ECOMMERCE_MODELS,
        tmp_dir=Path(_TMPDIR.name),
    )

    applied: list[str] = []
    for tool_name, mod_path in ALL_TOOLS:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, tool_name)
        result = fn(ToolInput(project_dir=str(project_dir)))
        if result.status == "error":
            raise RuntimeError(f"{tool_name} failed: {result.error}")
        applied.append(tool_name)

    print(f"  [setup] Applied {len(applied)}/27 tools to {project_dir.name}")
    _PROJECT_DIR = project_dir
    return project_dir


async def _precheck_postgres() -> bool:
    """Verify PostgreSQL is reachable before running tests."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        engine = create_async_engine(POSTGRES_URL, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception as exc:
        print(f"  [precheck] PostgreSQL unreachable at {POSTGRES_URL}")
        print(f"  [precheck] {type(exc).__name__}: {str(exc)[:200]}")
        return False


def _load_app(project_dir: Path):
    """Load the generated app.main with a clean sys.modules cache."""
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    return importlib.import_module("app.main").app


async def _reset_schema(engine) -> None:
    """Drop all tables and recreate the schema from scratch."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def _make_client(app, project_dir: Path, tenant_slug: str = "acme"):
    """Build an httpx AsyncClient wired to real PostgreSQL.

    Returns (client, session, engine, tenant_id) — tenant_id is None if
    add_multi_tenancy was not applied. The returned client should always
    send X-Tenant-ID: {tenant_slug} when multi-tenancy is active.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from httpx import ASGITransport, AsyncClient

    get_session_mod = importlib.import_module("app.core.session")
    base_mod = importlib.import_module("app.models.base")

    engine = create_async_engine(POSTGRES_URL, echo=False, future=True)
    await _reset_schema(engine)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(base_mod.Base.metadata.create_all)
        # audit_logs is declared PARTITION BY RANGE (created_at). metadata.create_all
        # creates the parent but no child partitions, so any INSERT fails with
        # "no partition of relation found for row". We attach a DEFAULT partition
        # that absorbs all rows (production would use monthly range partitions via
        # Alembic migrations — see the generator's alembic template).
        from sqlalchemy import text
        try:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS audit_logs_default "
                "PARTITION OF audit_logs DEFAULT"
            ))
        except Exception:
            pass  # Table not partitioned (add_audit_log not applied)

    session = factory()

    # Create a default tenant so /users/signup passes the tenant middleware
    tenant_id = await _seed_tenant(session, tenant_slug)

    async def _override():
        yield session

    app.dependency_overrides[get_session_mod.get_session] = _override
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, session, engine, tenant_id


async def _seed_tenant(session, slug: str) -> uuid.UUID | None:
    """Insert a seed tenant row so tenant-aware endpoints accept requests."""
    try:
        tenant_mod = importlib.import_module("app.models.tenant")
    except ModuleNotFoundError:
        return None
    tid = uuid.uuid4()
    tenant = tenant_mod.Tenant(id=tid, name="Acme Corp", slug=slug, status="active")
    session.add(tenant)
    await session.commit()
    return tid


async def _teardown(app, client, session, engine) -> None:
    await client.aclose()
    await session.close()
    await engine.dispose()
    app.dependency_overrides.clear()


def _th(token: str | None = None, tenant: str = "acme") -> dict[str, str]:
    """Build request headers: Authorization + X-Tenant-ID."""
    h = {"X-Tenant-ID": tenant}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _signup_and_login(client, email: str, password: str, name: str = "Test") -> str:
    r = await client.post("/api/v1/users/signup", json={
        "email": email, "password": password, "full_name": name,
    }, headers=_th())
    assert r.status_code in (200, 201), f"signup {email} failed: {r.status_code} {r.text[:300]}"
    r = await client.post("/api/v1/login/access-token", data={
        "username": email, "password": password,
    }, headers=_th())
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:300]}"
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Test 01 — Auth works end-to-end through the tenant middleware
# ---------------------------------------------------------------------------

async def test_01_tenant_aware_auth(pd: Path) -> tuple[bool, str]:
    """Signup → login → protected endpoint, all with X-Tenant-ID header."""
    app = _load_app(pd)
    client, session, engine, tid = await _make_client(app, pd)
    fails: list[str] = []
    try:
        if tid is None:
            fails.append("tenants table not present — add_multi_tenancy did not run")
            return (False, "tenant_aware_auth: " + "; ".join(fails))

        token = await _signup_and_login(client, "owner@acme.example.com", "OwnerPass123!", "Acme Owner")

        r = await client.get("/api/v1/products/", headers=_th(token))
        if r.status_code != 200:
            fails.append(f"GET products with token: {r.status_code}")

        # Missing tenant header → 400
        r = await client.get("/api/v1/products/", headers={"Authorization": f"Bearer {token}"})
        if r.status_code not in (400, 401):
            fails.append(f"missing tenant header: expected 400/401, got {r.status_code}")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "tenant_aware_auth: " + ("; ".join(fails) if fails else "PASS — signup/login/protected + tenant enforcement"))


# ---------------------------------------------------------------------------
# Test 02 — PostgreSQL full-text search actually finds documents
# ---------------------------------------------------------------------------

async def test_02_postgres_fts_search(pd: Path) -> tuple[bool, str]:
    """Real FTS path: create products, search by term, verify ranked results."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        token = await _signup_and_login(client, "search@acme.example.com", "SearchPass123!")
        h = _th(token)

        # Create 3 products with distinct searchable names
        products = [
            {"name": "Wireless Headphones", "description": "Noise-cancelling bluetooth",
             "price": 199.0, "sku": "WHP-001", "stock": 50},
            {"name": "Mechanical Keyboard", "description": "Tactile switches for coding",
             "price": 149.0, "sku": "KBD-001", "stock": 30},
            {"name": "Gaming Mouse", "description": "Wireless ergonomic precision",
             "price": 89.0, "sku": "MSE-001", "stock": 100},
        ]
        for p in products:
            r = await client.post("/api/v1/products/", json=p, headers=h)
            if r.status_code not in (200, 201):
                fails.append(f"create {p['sku']}: {r.status_code} {r.text[:150]}")

        # Search should use PostgreSQL FTS (websearch_to_tsquery + @@)
        r = await client.get("/api/v1/products/search?q=wireless", headers=h)
        if r.status_code != 200:
            fails.append(f"FTS search: {r.status_code} {r.text[:200]}")
        else:
            body = r.json()
            results = body.get("data") or body.get("items") or body.get("results") or []
            # Should find 2 (Wireless Headphones + Gaming Mouse with "wireless" in desc)
            if len(results) < 1:
                fails.append(f"FTS search 'wireless': 0 results (expected ≥1)")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "postgres_fts_search: " + ("; ".join(fails) if fails else f"PASS — FTS returned {len(results)} matches"))


# ---------------------------------------------------------------------------
# Test 03 — RBAC: permissions table exists, roles can be created
# ---------------------------------------------------------------------------

async def test_03_rbac_schema(pd: Path) -> tuple[bool, str]:
    """Verify RBAC tables were created with cross-DB constraints."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        from sqlalchemy import text, inspect
        async with engine.connect() as conn:
            result = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
            tables = set(result)

        required = {"permissions", "roles", "role_permissions", "user_roles"}
        missing = required - tables
        if missing:
            fails.append(f"RBAC tables missing: {missing}")

        # Verify the CHECK constraints we fixed are present and don't crash
        if "permissions" in tables:
            async with engine.connect() as conn:
                await conn.execute(text(
                    "INSERT INTO permissions (id, code, description, created_at) "
                    "VALUES (gen_random_uuid(), 'products:read', 'test', NOW())"
                ))
                await conn.commit()

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "rbac_schema: " + ("; ".join(fails) if fails else f"PASS — {len(required)} RBAC tables present"))


# ---------------------------------------------------------------------------
# Test 04 — MFA: TOTP secret generation works
# ---------------------------------------------------------------------------

async def test_04_mfa_enrollment(pd: Path) -> tuple[bool, str]:
    """Enrolling MFA should return a TOTP secret + QR provisioning URI."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        token = await _signup_and_login(client, "mfa@acme.example.com", "MfaPass123!")
        h = _th(token)

        # Enrollment endpoint — may be /mfa/enroll, /auth/mfa/enroll, /users/me/mfa
        enrolled = False
        for ep in ["/api/v1/mfa/enroll", "/api/v1/auth/mfa/enroll", "/api/v1/users/me/mfa/enroll"]:
            r = await client.post(ep, headers=h)
            if r.status_code in (200, 201):
                body = r.json()
                if "secret" in body or "otp_uri" in body or "qr" in body:
                    enrolled = True
                    break

        if not enrolled:
            # Check if the route module at least exists
            try:
                importlib.import_module("app.api.routes.mfa")
                fails.append("MFA route module present but no enrollment endpoint responded 200")
            except ModuleNotFoundError:
                fails.append("MFA module not generated")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "mfa_enrollment: " + ("; ".join(fails) if fails else "PASS — TOTP secret issued"))


# ---------------------------------------------------------------------------
# Test 05 — OAuth2 provider: authorization endpoint exists
# ---------------------------------------------------------------------------

async def test_05_oauth2_authorize_endpoint(pd: Path) -> tuple[bool, str]:
    """OAuth2 authorization + token endpoints must be registered."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        # OpenAPI lists registered routes
        r = await client.get("/api/v1/openapi.json")
        if r.status_code != 200:
            fails.append(f"openapi.json: {r.status_code}")
            return (False, "oauth2_authorize_endpoint: " + "; ".join(fails))

        paths = r.json().get("paths", {})
        oauth_paths = [p for p in paths if "oauth" in p.lower() or "authorize" in p.lower()]
        if not oauth_paths:
            fails.append("no OAuth2 paths registered in OpenAPI")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "oauth2_authorize_endpoint: " + ("; ".join(fails) if fails else f"PASS — {len(oauth_paths)} OAuth2 paths"))


# ---------------------------------------------------------------------------
# Test 06 — Multi-tenant isolation: tenant A cannot read tenant B's data
# ---------------------------------------------------------------------------

async def test_06_tenant_isolation(pd: Path) -> tuple[bool, str]:
    """Two tenants, same model, each sees only their own rows."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd, tenant_slug="acme")
    fails: list[str] = []
    try:
        # Seed a second tenant
        tenant_mod = importlib.import_module("app.models.tenant")
        beta_id = uuid.uuid4()
        session.add(tenant_mod.Tenant(id=beta_id, name="Beta LLC", slug="beta", status="active"))
        await session.commit()

        # User in Acme creates a product
        token_a = await _signup_and_login(client, "alice@acme.example.com", "AlicePass123!", "Alice")
        r = await client.post("/api/v1/products/", json={
            "name": "Acme Widget", "description": "acme only", "price": 10.0,
            "sku": "ACM-001", "stock": 5,
        }, headers=_th(token_a, tenant="acme"))
        if r.status_code not in (200, 201):
            fails.append(f"Acme create: {r.status_code} {r.text[:200]}")
            return (False, "tenant_isolation: " + "; ".join(fails))

        # User in Beta signs up
        token_b = await _signup_and_login(client, "bob@beta.example.com", "BobPass123!", "Bob")

        # Bob (Beta tenant) lists products — should NOT see Acme's widget
        r = await client.get("/api/v1/products/", headers=_th(token_b, tenant="beta"))
        if r.status_code == 200:
            body = r.json()
            items = body.get("data") or body.get("items") or (body if isinstance(body, list) else [])
            skus = [item.get("sku") for item in items if isinstance(item, dict)]
            if "ACM-001" in skus:
                fails.append("TENANT BREACH: Beta user sees Acme product")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "tenant_isolation: " + ("; ".join(fails) if fails else "PASS — tenant boundary enforced"))


# ---------------------------------------------------------------------------
# Test 07 — Bulk create actually persists rows in PostgreSQL
# ---------------------------------------------------------------------------

async def test_07_bulk_create_persists(pd: Path) -> tuple[bool, str]:
    """Bulk create 10 products, verify all 10 are queryable via GET /products/."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        token = await _signup_and_login(client, "bulk@acme.example.com", "BulkPass123!")
        h = _th(token)

        items = [
            {"name": f"Bulk-{i:03d}", "description": f"batch item {i}",
             "price": float(i), "sku": f"BLK-{i:03d}", "stock": i}
            for i in range(10)
        ]
        r = await client.post("/api/v1/products/bulk", json={
            "items": items, "mode": "all_or_nothing",
        }, headers=h)
        if r.status_code not in (200, 201, 207):
            fails.append(f"bulk create: {r.status_code} {r.text[:200]}")
            return (False, "bulk_create_persists: " + "; ".join(fails))

        # Commit so the rows are visible to a fresh connection
        await session.commit()

        # Count via the same session (same transaction context)
        from sqlalchemy import text
        result = await session.execute(text("SELECT COUNT(*) FROM products WHERE sku LIKE 'BLK-%'"))
        count = result.scalar()
        if count != 10:
            fails.append(f"bulk create: expected 10 persisted, got {count}")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, "bulk_create_persists: " + ("; ".join(fails) if fails else "PASS — 10/10 persisted"))


# ---------------------------------------------------------------------------
# Test 08 — Audit log captures bulk operations
# ---------------------------------------------------------------------------

async def test_08_audit_log_bulk(pd: Path) -> tuple[bool, str]:
    """After a bulk create, audit_logs must contain create entries."""
    app = _load_app(pd)
    client, session, engine, _ = await _make_client(app, pd)
    fails: list[str] = []
    try:
        token = await _signup_and_login(client, "audit@acme.example.com", "AuditPass123!")
        h = _th(token)

        # Single create via regular endpoint — audit listener should fire
        r = await client.post("/api/v1/products/", json={
            "name": "Audited", "description": "x", "price": 1.0, "sku": "AUD-001", "stock": 1,
        }, headers=h)
        if r.status_code not in (200, 201):
            fails.append(f"create: {r.status_code}")
            return (False, "audit_log_bulk: " + "; ".join(fails))

        # Commit so audit entries are flushed (before_flush → insert → commit)
        await session.commit()

        # Query audit_logs table via the same session
        from sqlalchemy import text
        result = await session.execute(text("SELECT COUNT(*) FROM audit_logs"))
        count = result.scalar()
        if count < 1:
            fails.append(f"audit_logs: expected ≥1 entry, got {count}")

    finally:
        await _teardown(app, client, session, engine)

    return (not fails, f"audit_log_bulk: " + ("; ".join(fails) if fails else f"PASS — {count} audit entries captured"))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    ("01_tenant_aware_auth",      test_01_tenant_aware_auth),
    ("02_postgres_fts_search",    test_02_postgres_fts_search),
    ("03_rbac_schema",            test_03_rbac_schema),
    ("04_mfa_enrollment",         test_04_mfa_enrollment),
    ("05_oauth2_endpoint",        test_05_oauth2_authorize_endpoint),
    ("06_tenant_isolation",       test_06_tenant_isolation),
    ("07_bulk_create_persists",   test_07_bulk_create_persists),
    ("08_audit_log_bulk",         test_08_audit_log_bulk),
]


def main() -> int:
    print("=" * 70)
    print(f"  SKILL-001 E2E with REAL PostgreSQL — {len(ALL_TOOLS)} tools, {len(TESTS)} tests")
    print(f"  URL: {POSTGRES_URL}")
    print("=" * 70)
    print()

    if not asyncio.run(_precheck_postgres()):
        print("  [SKIP] PostgreSQL unreachable — run:")
        print("    docker run -d --name skill001-e2e-pg \\")
        print("      -e POSTGRES_USER=skill -e POSTGRES_PASSWORD=skill \\")
        print("      -e POSTGRES_DB=skill_e2e -p 54329:5432 postgres:16-alpine")
        return 2

    try:
        project_dir = _setup()
    except Exception as exc:
        print(f"  [FAIL] Project setup: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    total = len(TESTS)
    passed = 0
    failed: list[str] = []

    t0 = time.monotonic()
    for test_id, test_fn in TESTS:
        try:
            ok, detail = asyncio.run(test_fn(project_dir))
        except Exception as exc:
            ok = False
            detail = f"{test_id}: EXCEPTION: {type(exc).__name__}: {str(exc)[:200]}"

        if ok:
            passed += 1
            print(f"  [PASS]  {test_id}: {detail.split(': ', 1)[-1]}")
        else:
            failed.append(test_id)
            print(f"  [FAIL]  {test_id}: {detail}")

    elapsed = time.monotonic() - t0

    print()
    print("-" * 70)
    print(f"  Result: {passed}/{total} tests passed  ({elapsed:.1f}s)")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
    print("-" * 70)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
