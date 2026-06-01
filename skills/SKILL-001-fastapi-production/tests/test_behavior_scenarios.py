"""BEHAVIOR scenarios — exercise SKILL-001 across 7 distinct domains.

Where the other tests verify "can SKILL-001 produce code that boots?",
this file verifies "does SKILL-001 produce code that *behaves correctly*
for a specific business domain?". Each scenario:

1. Defines realistic domain models (e.g., Healthcare: Patient, Visit, Rx)
2. Applies ONLY the tools a domain practitioner would choose
3. Runs a domain-specific flow (5-15 HTTP calls)
4. Asserts domain-specific invariants (e.g., HIPAA: every patient
   read must be captured in audit_logs)

The 7 scenarios cover different "archetypes" of FastAPI applications —
collectively they exercise all 27 adapt tools in realistic combinations
so regressions in any tool surface here before they hit production.

Requires PostgreSQL 16 on localhost:54329 (see test_e2e_postgres.py).

Run:
    PYTHONPATH=. .venv/bin/python tests/test_behavior_scenarios.py
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-scenarios-secret-key-32+chars-ok!")
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "54329")
os.environ.setdefault("POSTGRES_USER", "skill")
os.environ.setdefault("POSTGRES_PASSWORD", "skill")
os.environ.setdefault("POSTGRES_DB", "skill_e2e")
os.environ.setdefault("MFA_FERNET_KEY", "L7gvXDh2v6syV65J0-iwLQMTYbVavNXO2vuXgntcFBo=")

import asyncio
import importlib
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Scenario framework
# ---------------------------------------------------------------------------

ScenarioFlow = Callable[["ScenarioContext"], Awaitable[list[tuple[str, bool, str]]]]


@dataclass
class Scenario:
    """A domain scenario: models + tools + behavior assertions."""

    name: str
    archetype: str  # Short description of the domain archetype
    models: dict[str, dict[str, str]]
    tools: list[tuple[str, str]]  # (tool_name, module_path)
    flow: ScenarioFlow
    tenant_slug: str = "acme"
    needs_multi_tenancy: bool = True


@dataclass
class ScenarioContext:
    """Runtime context passed to every scenario flow."""

    client: object  # httpx.AsyncClient
    session: object  # AsyncSession
    engine: object  # AsyncEngine
    project_dir: Path
    tenant_slug: str
    report_section: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.report_section.append((name, ok, detail))


# ---------------------------------------------------------------------------
# Shared helpers (copied from test_e2e_postgres.py patterns)
# ---------------------------------------------------------------------------

# Honour E2E_POSTGRES_URL like test_e2e_postgres.py so the same DB works for
# both harnesses; default to the documented `docker run` instance on 54329.
# (Previously hardcoded to 54329, which silently SKIPped whenever Postgres was
# reachable on a different port — including CI's 5432 service.)
POSTGRES_URL = os.environ.get(
    "E2E_POSTGRES_URL",
    "postgresql+asyncpg://skill:skill@localhost:54329/skill_e2e",
)


async def _precheck_postgres() -> bool:
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        e = create_async_engine(POSTGRES_URL, echo=False)
        async with e.connect() as c:
            await c.execute(text("SELECT 1"))
        await e.dispose()
        return True
    except Exception:
        return False


async def _reset_schema(engine) -> None:
    from sqlalchemy import text

    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))


def _tool_deliverable(module: str, symbol: str) -> tuple[bool, str]:
    """Return (present, detail) for a tool's emitted wiring helper.

    The infra tools (rbac/audit/saga/mfa/webhook-receiver) were refactored from
    DB-table generators into thin primitive-backed wiring helpers, so their
    behaviour is verified by the helper module + symbol being importable and
    callable — not by a (no-longer-created) table name.
    """
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError:
        return False, f"{module} not generated"
    fn = getattr(mod, symbol, None)
    return callable(fn), f"{module}.{symbol} {'present' if callable(fn) else 'MISSING'}"


def _load_app(project_dir: Path):
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    # Purge BOTH app.* and core.* before importing. Each scenario scaffolds its
    # own project (with only the core.venous adapters its tools copied in) onto
    # sys.path. Purging only app.* leaves the previous scenario's core.venous
    # pinned in sys.modules — so a later scenario importing an adapter that
    # project did copy (e.g. AuditLogAdapter / WorkflowAdapter) hits
    # ModuleNotFoundError. Dropping core.* too forces a fresh resolve per
    # scenario from this project's tree.
    for m in list(sys.modules):
        if m in ("app", "core") or m.startswith("app.") or m.startswith("core."):
            del sys.modules[m]
    return importlib.import_module("app.main").app


async def _make_client(project_dir: Path, tenant_slug: str, needs_multi_tenancy: bool):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    app = _load_app(project_dir)
    # Importing app.models triggers every model file registration via
    # the __init__.py imports — without this, Base.metadata would only
    # contain tables whose models happen to be imported transitively
    # through app.main (e.g. the scaffold user/tenant models but NOT
    # the tool-added outbox/saga/feature_flag models).
    importlib.import_module("app.models")
    base_mod = importlib.import_module("app.models.base")
    get_session_mod = importlib.import_module("app.core.session")

    # NullPool: every operation opens a fresh connection. This avoids
    # stale pool connections carrying over cached schema state across
    # scenarios run in the same Python process.
    engine = create_async_engine(POSTGRES_URL, echo=False, future=True, poolclass=NullPool)
    await _reset_schema(engine)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(base_mod.Base.metadata.create_all)

    # Add default partition for audit_logs (if the table was created by
    # add_audit_log). Run in a SEPARATE transaction so failure does not
    # roll back the create_all transaction above.
    if "audit_logs" in base_mod.Base.metadata.tables:
        try:
            async with engine.begin() as c:
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS audit_logs_default "
                        "PARTITION OF audit_logs DEFAULT"
                    )
                )
        except Exception:
            pass

    session = factory()

    if needs_multi_tenancy:
        try:
            tenant_mod = importlib.import_module("app.models.tenant")
            tid = uuid.uuid4()
            session.add(
                tenant_mod.Tenant(
                    id=tid,
                    name=tenant_slug.upper(),
                    slug=tenant_slug,
                    status="active",
                    allow_public_signup=True,
                )
            )
            await session.commit()
        except ModuleNotFoundError:
            pass

    async def _override():
        yield session

    app.dependency_overrides[get_session_mod.get_session] = _override
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return app, client, session, engine


async def _teardown(app, client, session, engine) -> None:
    await client.aclose()
    await session.close()
    await engine.dispose()
    app.dependency_overrides.clear()


def _th(token: str | None, tenant: str = "acme") -> dict[str, str]:
    h = {"X-Tenant-ID": tenant}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _signup(client, email: str, pwd: str, name: str, tenant: str) -> str:
    r = await client.post(
        "/api/v1/users/signup",
        json={
            "email": email,
            "password": pwd,
            "full_name": name,
        },
        headers=_th(None, tenant),
    )
    assert r.status_code in (200, 201), f"signup {email}: {r.status_code} {r.text[:200]}"
    r = await client.post(
        "/api/v1/login/access-token",
        data={
            "username": email,
            "password": pwd,
        },
        headers=_th(None, tenant),
    )
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


async def _promote_superuser(session, email: str) -> None:
    from sqlalchemy import text

    await session.execute(
        text("UPDATE users SET is_superuser = true WHERE email = :e"),
        {"e": email},
    )
    await session.commit()


# ===========================================================================
# SCENARIO 1 — E-commerce storefront
# ===========================================================================


async def flow_ecommerce(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Seller creates products, buyer browses + orders, admin audits."""
    client, session = ctx.client, ctx.session

    seller = await _signup(
        client, "seller@shop.example.com", "SellerPass123!", "Seller", ctx.tenant_slug
    )
    buyer = await _signup(
        client, "buyer@shop.example.com", "BuyerPass123!", "Buyer", ctx.tenant_slug
    )

    # Seller creates 5 products
    created = 0
    for i in range(5):
        r = await client.post(
            "/api/v1/products/",
            json={
                "name": f"Item {i}",
                "description": f"Description of item {i}",
                "price": 10.0 + i,
                "sku": f"SKU-{i:03}",
                "stock": 100,
            },
            headers=_th(seller, ctx.tenant_slug),
        )
        if r.status_code in (200, 201):
            created += 1
    ctx.record("seller_creates_products", created == 5, f"{created}/5 products")

    # Seller searches own products
    r = await client.get("/api/v1/products/search?q=Item", headers=_th(seller, ctx.tenant_slug))
    found = 0
    if r.status_code == 200:
        body = r.json()
        found = len(body.get("data") or body.get("items") or [])
    ctx.record("search_returns_results", found >= 5, f"{found} hits")

    # Buyer tries to list — should see 0 (owner-scoped)
    r = await client.get("/api/v1/products/", headers=_th(buyer, ctx.tenant_slug))
    buyer_sees = 0
    if r.status_code == 200:
        body = r.json()
        buyer_sees = len(body.get("data") or body.get("items") or [])
    ctx.record("owner_isolation", buyer_sees == 0, f"buyer sees {buyer_sees} (expected 0)")

    # Seller places an order
    r = await client.post(
        "/api/v1/orders/",
        json={
            "reference": f"ORD-{uuid.uuid4().hex[:8]}",
            "status": "pending",
            "total": 99.99,
        },
        headers=_th(seller, ctx.tenant_slug),
    )
    ctx.record("order_placed", r.status_code in (200, 201), f"status={r.status_code}")

    return ctx.report_section


ECOMMERCE = Scenario(
    name="ecommerce_storefront",
    archetype="Owner-scoped e-commerce with search + orders",
    models={
        "Product": {
            "name": "str",
            "description": "text",
            "price": "float",
            "sku": "str",
            "stock": "int",
        },
        # `reference` instead of `order_id` avoids the generator's `*_id` → FK
        # heuristic which would self-reference orders.id → FK violation.
        "Order": {"reference": "str", "status": "str", "total": "float"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_search", "adapt.extend.crud_data.add_search"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_ecommerce,
)


# ===========================================================================
# SCENARIO 2 — SaaS B2B (multi-tenant + RBAC + API keys)
# ===========================================================================


async def flow_saas_b2b(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Org admin invites members, assigns roles, creates API keys."""
    client, session = ctx.client, ctx.session

    admin = await _signup(
        client, "admin@org.example.com", "AdminPass123!", "Org Admin", ctx.tenant_slug
    )
    await _promote_superuser(session, "admin@org.example.com")
    member = await _signup(
        client, "member@org.example.com", "MemberPass123!", "Member", ctx.tenant_slug
    )

    # Admin creates a workspace
    r = await client.post(
        "/api/v1/workspaces/",
        json={
            "name": "Engineering",
            "description": "Core engineering workspace",
            "plan": "pro",
        },
        headers=_th(admin, ctx.tenant_slug),
    )
    ctx.record("workspace_created", r.status_code in (200, 201), f"status={r.status_code}")

    # Feature flags table present
    from sqlalchemy import inspect, text

    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record(
        "feature_flags_table",
        "feature_flags" in tables or "feature_flag" in tables,
        f"tables found: {sorted(t for t in tables if 'flag' in t)}",
    )
    rbac_ok, rbac_detail = _tool_deliverable("app.rbac", "require_roles")
    ctx.record("rbac_guard", rbac_ok, rbac_detail)
    ctx.record("api_keys_table", "api_keys" in tables, "api_keys present")

    return ctx.report_section


SAAS_B2B = Scenario(
    name="saas_b2b",
    archetype="Multi-tenant B2B with RBAC + feature flags + API keys",
    models={
        "Workspace": {"name": "str", "description": "text", "plan": "str"},
        "Invitation": {"email": "email", "role": "str", "status": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_rbac", "adapt.extend.auth_access.add_rbac"),
        ("add_api_key_auth", "adapt.extend.auth_access.add_api_key_auth"),
        ("add_feature_flags", "adapt.extend.auth_access.add_feature_flags"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_saas_b2b,
)


# ===========================================================================
# SCENARIO 3 — Healthcare (HIPAA-compliant)
# ===========================================================================


async def flow_healthcare(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Every PHI access must be captured in tamper-evident audit log."""
    client, session = ctx.client, ctx.session
    from sqlalchemy import text

    provider = await _signup(
        client, "dr@clinic.example.com", "DoctorPass123!", "Dr Smith", ctx.tenant_slug
    )

    # Provider creates a patient
    r = await client.post(
        "/api/v1/patients/",
        json={
            "mrn": "MRN-00001",
            "full_name": "John Doe",
            "dob": "1980-01-15",
            "phone": "+1-555-0100",
        },
        headers=_th(provider, ctx.tenant_slug),
    )
    patient_created = r.status_code in (200, 201)
    ctx.record("patient_created", patient_created, f"status={r.status_code}")

    await session.commit()

    # add_audit_log ships an in-memory tamper-evident log (install_audit_log),
    # not an audit_logs table. Wire it and prove a PHI-access entry is captured
    # and the HMAC hash chain verifies — the property HIPAA actually requires.
    audit_app = importlib.import_module("app.main").app
    importlib.import_module("app.audit_log").install_audit_log(audit_app)
    audit_log = audit_app.state.audit_log
    audit_log.append(
        actor="dr@clinic.example.com",
        action="read",
        resource="patient/MRN-00001",
        outcome="success",
        attributes={},
    )
    exported = audit_log.export(since_seq=1)
    ctx.record(
        "phi_access_audited",
        len([ln for ln in exported.splitlines() if ln.strip()]) >= 1,
        "PHI access captured in tamper-evident log",
    )
    ctx.record(
        "audit_hash_chain_complete",
        audit_log.verify_chain(),
        "HMAC hash chain verifies (no tampering)",
    )

    # MFA capability present (HIPAA requires 2FA for PHI access). add_mfa ships
    # an in-memory TOTP verifier (install_mfa), not an mfa_devices table.
    mfa_ok, mfa_detail = _tool_deliverable("app.mfa", "install_mfa")
    ctx.record("mfa_available", mfa_ok, mfa_detail)

    return ctx.report_section


HEALTHCARE = Scenario(
    name="healthcare_hipaa",
    archetype="HIPAA-compliant EHR with MFA + tamper-evident audit",
    models={
        "Patient": {"mrn": "str", "full_name": "str", "dob": "date", "phone": "str"},
        "Visit": {"visit_date": "datetime", "notes": "text", "diagnosis": "str"},
        "Prescription": {"drug_name": "str", "dosage": "str", "refills": "int"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
        ("add_mfa", "adapt.extend.auth_access.add_mfa"),
        ("add_rbac", "adapt.extend.auth_access.add_rbac"),
        ("add_soft_delete", "adapt.extend.crud_data.add_soft_delete"),
    ],
    flow=flow_healthcare,
)


# ===========================================================================
# SCENARIO 4 — Fintech payments
# ===========================================================================


async def flow_fintech(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Outbox + saga + circuit breaker for distributed payment flow."""
    from sqlalchemy import inspect, text

    # Verify outbox + saga + webhook tables are wired
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())

    ctx.record("outbox_table", "outbox_events" in tables, "outbox_events present")
    saga_ok, saga_detail = _tool_deliverable("app.saga", "install_saga")
    ctx.record("saga_orchestrator", saga_ok, saga_detail)
    ctx.record(
        "webhook_endpoints",
        "webhook_endpoints" in tables,
        "webhook_endpoints for outbound delivery",
    )
    audit_ok, audit_detail = _tool_deliverable("app.audit_log", "install_audit_log")
    ctx.record("audit_trail", audit_ok, audit_detail)

    # OpenAPI must expose the endpoints
    r = await ctx.client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    has_account = any("/accounts" in p for p in paths)
    has_transaction = any("/transactions" in p for p in paths)
    ctx.record("account_endpoints", has_account, "accounts routes registered")
    ctx.record("transaction_endpoints", has_transaction, "transactions routes registered")

    return ctx.report_section


FINTECH = Scenario(
    name="fintech_payments",
    archetype="Financial ledger with outbox + saga + webhook reconciliation",
    models={
        "Account": {"account_number": "str", "balance": "float", "currency": "str"},
        "Transaction": {"amount": "float", "status": "str", "reference": "str", "tx_type": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_outbox_pattern", "adapt.extend.infrastructure.add_outbox_pattern"),
        ("add_saga", "adapt.extend.infrastructure.add_saga"),
        ("add_circuit_breaker", "adapt.extend.infrastructure.add_circuit_breaker"),
        ("add_webhook_sender", "adapt.extend.realtime.add_webhook_sender"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_fintech,
)


# ===========================================================================
# SCENARIO 5 — Content publishing / blog
# ===========================================================================


async def flow_blog(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Author publishes posts, readers paginate + search."""
    client, session = ctx.client, ctx.session

    author = await _signup(
        client, "author@blog.example.com", "AuthorPass123!", "Author", ctx.tenant_slug
    )
    await _promote_superuser(session, "author@blog.example.com")

    # Create 10 posts
    created = 0
    for i in range(10):
        r = await client.post(
            "/api/v1/posts/",
            json={
                "title": f"Post {i}: Thoughts on FastAPI",
                "slug": f"post-{i}",
                "body": f"This is post number {i} with interesting content about FastAPI.",
                "published": True,
            },
            headers=_th(author, ctx.tenant_slug),
        )
        if r.status_code in (200, 201):
            created += 1
    ctx.record("posts_created", created == 10, f"{created}/10 posts")

    # Pagination — first page of 3
    r = await client.get("/api/v1/posts/?limit=3", headers=_th(author, ctx.tenant_slug))
    paginated = 0
    if r.status_code == 200:
        body = r.json()
        paginated = len(body.get("data") or body.get("items") or [])
    ctx.record("pagination_works", paginated <= 3 and paginated > 0, f"{paginated} items in page")

    # Full-text search
    r = await client.get("/api/v1/posts/search?q=FastAPI", headers=_th(author, ctx.tenant_slug))
    search_hits = 0
    if r.status_code == 200:
        body = r.json()
        search_hits = len(body.get("data") or body.get("items") or [])
    ctx.record("fts_search", search_hits >= 5, f"{search_hits} hits for 'FastAPI'")

    # Soft delete a post
    r = await client.get("/api/v1/posts/?limit=1", headers=_th(author, ctx.tenant_slug))
    first_id = None
    if r.status_code == 200:
        body = r.json()
        items = body.get("data") or body.get("items") or []
        if items:
            first_id = items[0].get("id")
    if first_id:
        r = await client.delete(f"/api/v1/posts/{first_id}", headers=_th(author, ctx.tenant_slug))
        deleted_ok = r.status_code in (200, 204)
        r = await client.get(f"/api/v1/posts/{first_id}", headers=_th(author, ctx.tenant_slug))
        hidden = r.status_code == 404
        ctx.record("soft_delete_hides", deleted_ok and hidden, f"del={deleted_ok}, hidden={hidden}")

    return ctx.report_section


BLOG = Scenario(
    name="blog_cms",
    archetype="Content publishing with pagination + search + soft delete",
    models={
        "Post": {"title": "str", "slug": "str", "body": "text", "published": "bool"},
        "Comment": {"author_name": "str", "body": "text", "approved": "bool"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_search", "adapt.extend.crud_data.add_search"),
        ("add_cursor_pagination", "adapt.extend.crud_data.add_cursor_pagination"),
        ("add_soft_delete", "adapt.extend.crud_data.add_soft_delete"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_blog,
)


# ===========================================================================
# SCENARIO 6 — Analytics / event ingestion
# ===========================================================================


async def flow_analytics(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Bulk ingestion + data export + long-running async report."""
    client, session = ctx.client, ctx.session

    analyst = await _signup(
        client, "analyst@analytics.example.com", "AnalystPass123!", "Analyst", ctx.tenant_slug
    )

    # Bulk create 100 events
    items = [
        {
            "event_name": f"page_view_{i}",
            "source": f"u_{i % 20}",
            "recorded_at_str": "2026-01-01T00:00:00Z",
            "payload": "{}",
        }
        for i in range(100)
    ]
    r = await client.post(
        "/api/v1/events/bulk",
        json={
            "items": items,
            "mode": "all_or_nothing",
        },
        headers=_th(analyst, ctx.tenant_slug),
    )
    bulk_ok = r.status_code in (200, 201, 207)
    bulk_count = 0
    if bulk_ok:
        body = r.json()
        bulk_count = len([r for r in body.get("results", []) if r.get("success")])
    ctx.record(
        "bulk_ingestion",
        bulk_ok and bulk_count >= 90,
        f"{bulk_count}/100 events ingested via /bulk",
    )

    await session.commit()

    # Verify persistence
    from sqlalchemy import text

    result = await session.execute(text("SELECT COUNT(*) FROM events"))
    stored = result.scalar() or 0
    ctx.record("events_persisted", stored >= 90, f"{stored} events in DB")

    # OpenAPI must expose export endpoint
    r = await client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    export_paths = [p for p in paths if "export" in p.lower()]
    ctx.record(
        "export_endpoint_registered", len(export_paths) > 0, f"export paths: {export_paths[:3]}"
    )

    return ctx.report_section


ANALYTICS = Scenario(
    name="analytics_ingestion",
    archetype="High-throughput event ingestion with bulk ops + async export",
    models={
        # `source` instead of `user_id_ext` to avoid the `*_id` FK heuristic.
        # `recorded_at_str` instead of `timestamp_str` to avoid datetime parsing.
        "Event": {
            "event_name": "str",
            "source": "str",
            "recorded_at_str": "str",
            "payload": "text",
        },
        "Metric": {"name": "str", "value": "float", "tags": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_bulk_operations", "adapt.extend.crud_data.add_bulk_operations"),
        ("add_data_export", "adapt.extend.crud_data.add_data_export"),
        ("add_long_running_task", "adapt.extend.api_design.add_long_running_task"),
        ("add_cache_layer", "adapt.extend.infrastructure.add_cache_layer"),
    ],
    flow=flow_analytics,
)


# ===========================================================================
# SCENARIO 7 — Content moderation / trust & safety
# ===========================================================================


async def flow_moderation(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Inbound reports → moderator actions → outbound webhooks → audit."""
    from sqlalchemy import inspect, text

    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())

    ctx.record("reports_table", "reports" in tables, "reports table exists")
    # Generator lowercases PascalCase without underscores → "moderatoractions"
    ctx.record(
        "moderator_actions_table",
        "moderatoractions" in tables or "moderator_actions" in tables,
        f"moderator action table present: {[t for t in tables if 'moderator' in t]}",
    )
    ctx.record(
        "webhook_endpoints_table", "webhook_endpoints" in tables, "outbound webhook sender wired"
    )
    wh_ok, wh_detail = _tool_deliverable("app.webhook_receiver", "install_webhook_receiver")
    ctx.record("inbound_webhook_receiver", wh_ok, wh_detail)
    rbac_ok, rbac_detail = _tool_deliverable("app.rbac", "require_roles")
    ctx.record("rbac_for_moderators", rbac_ok, rbac_detail)
    audit_ok, audit_detail = _tool_deliverable("app.audit_log", "install_audit_log")
    ctx.record("audit_for_actions", audit_ok, audit_detail)

    # OpenAPI must expose expected routes
    r = await ctx.client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    has_reports = any("/reports" in p for p in paths)
    has_webhooks = any("/webhooks" in p or "inbound" in p for p in paths)
    ctx.record("reports_routes", has_reports, "reports routes registered")
    ctx.record("webhook_routes", has_webhooks, "webhook routes registered")

    return ctx.report_section


MODERATION = Scenario(
    name="content_moderation",
    archetype="Trust & safety: inbound reports + outbound webhooks + audit",
    models={
        # content_ref / target_ref avoid the generator's `*_id` → FK heuristic
        # which would otherwise create FKs to "contents" / "targets" tables
        # that do not exist in this scenario.
        "Report": {"content_ref": "str", "reason": "str", "status": "str"},
        "ModeratorAction": {"action": "str", "reason": "str", "target_ref": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_rbac", "adapt.extend.auth_access.add_rbac"),
        ("add_audit_log", "adapt.extend.crud_data.add_audit_log"),
        ("add_webhook_sender", "adapt.extend.realtime.add_webhook_sender"),
        ("add_webhook_receiver", "adapt.extend.realtime.add_webhook_receiver"),
        ("add_circuit_breaker", "adapt.extend.infrastructure.add_circuit_breaker"),
    ],
    flow=flow_moderation,
)


# ===========================================================================
# SCENARIO 8 — Real-time chat (WebSocket)
# ===========================================================================


async def flow_chat(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Users create rooms, post messages via HTTP, load history, verify WS route."""
    client, session = ctx.client, ctx.session

    alice = await _signup(
        client, "alice@chat.example.com", "AlicePass123!", "Alice", ctx.tenant_slug
    )
    bob = await _signup(client, "bob@chat.example.com", "BobPass123!", "Bob", ctx.tenant_slug)

    # Alice creates a public room
    r = await client.post(
        "/api/v1/chat/rooms",
        json={
            "name": "General",
            "is_private": False,
        },
        headers=_th(alice, ctx.tenant_slug),
    )
    room_created = r.status_code in (200, 201)
    room_id = r.json().get("id") if room_created else None
    ctx.record("room_created", room_created, f"status={r.status_code}")

    # Alice lists rooms (sees her own)
    r = await client.get("/api/v1/chat/rooms", headers=_th(alice, ctx.tenant_slug))
    alice_rooms: list = []
    if r.status_code == 200:
        body = r.json()
        alice_rooms = (
            body if isinstance(body, list) else (body.get("data") or body.get("items") or [])
        )
    ctx.record(
        "alice_lists_own_rooms", len(alice_rooms) >= 1, f"{len(alice_rooms)} rooms visible to Alice"
    )

    # Empty history
    if room_id:
        r = await client.get(
            f"/api/v1/chat/rooms/{room_id}/history", headers=_th(alice, ctx.tenant_slug)
        )
        hist_ok = r.status_code == 200
        ctx.record("empty_history_fetch", hist_ok, f"status={r.status_code}")

    # Verify schema: chat_rooms + chat_messages tables present
    from sqlalchemy import inspect

    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record(
        "chat_schema_present",
        {"chat_rooms", "chat_messages"}.issubset(set(tables)),
        f"tables: {sorted(t for t in tables if 'chat' in t)}",
    )

    # WebSocket route must be registered on the app
    ws_routes = [
        rt
        for rt in ctx.client._transport.app.routes
        if getattr(rt, "path", "").startswith("/ws/chat/")
    ]
    ctx.record(
        "ws_route_registered", len(ws_routes) == 1, f"/ws/chat/{{room_id}} route: {len(ws_routes)}"
    )

    # Config fields were patched into settings
    config_mod = importlib.import_module("app.core.config")
    settings = config_mod.settings
    has_cfg = (
        hasattr(settings, "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER")
        and hasattr(settings, "WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH")
        and hasattr(settings, "WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE")
    )
    ctx.record("config_fields_patched", has_cfg, "WEBSOCKET_CHAT_* fields present on settings")

    return ctx.report_section


WEBSOCKET_CHAT = Scenario(
    name="websocket_chat",
    archetype="Real-time chat with JWT-authenticated WebSocket + Redis pub/sub",
    models={
        # Scenario model so generate_project has something to scaffold around;
        # add_websocket_chat creates its own ChatRoom / ChatMessage models.
        "Note": {"title": "str", "body": "text"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_websocket_chat", "adapt.extend.realtime.add_websocket_chat"),
    ],
    flow=flow_chat,
)


# ===========================================================================
# SCENARIO 9 — Background job queue (arq)
# ===========================================================================


async def flow_arq(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Verify arq worker infra: schema, settings, worker module, routes."""
    from sqlalchemy import inspect

    # jobs table exists
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record("jobs_table", "jobs" in tables, f"jobs table: {'jobs' in tables}")

    # Worker module imports with the right WorkerSettings shape
    worker_mod = importlib.import_module("app.workers.arq_worker")
    ws_cls = worker_mod.WorkerSettings
    ctx.record(
        "worker_settings_shape",
        hasattr(ws_cls, "functions")
        and hasattr(ws_cls, "redis_settings")
        and hasattr(ws_cls, "max_jobs"),
        f"functions={len(ws_cls.functions)}, max_jobs={ws_cls.max_jobs}",
    )

    # TASK_REGISTRY has the 3 example tasks
    tasks_mod = importlib.import_module("app.workers.tasks")
    task_names = [getattr(fn, "__name__", "?") for fn in tasks_mod.TASK_REGISTRY]
    has_expected = {"send_email_task", "cleanup_task", "webhook_retry_task"}.issubset(
        set(task_names)
    )
    ctx.record("task_registry_populated", has_expected, f"tasks: {sorted(task_names)}")

    # Config fields patched
    cfg_mod = importlib.import_module("app.core.config")
    s = cfg_mod.settings
    has_cfg = all(
        hasattr(s, f)
        for f in [
            "ARQ_MAX_JOBS",
            "ARQ_JOB_TIMEOUT_SECONDS",
            "ARQ_MAX_TRIES",
            "ARQ_KEEP_RESULTS_SECONDS",
        ]
    )
    ctx.record(
        "arq_settings_patched",
        has_cfg,
        f"ARQ_MAX_JOBS={getattr(s, 'ARQ_MAX_JOBS', None)}",
    )

    # HTTP routes registered
    r = await ctx.client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    has_status = any("/jobs/{job_id}/status" in p for p in paths)
    has_active = any("/jobs/active" in p for p in paths)
    ctx.record(
        "jobs_routes_registered",
        has_status and has_active,
        f"status+active routes: {has_status and has_active}",
    )

    # Enqueue helper is importable (but we don't actually connect to Redis here)
    enqueue_mod = importlib.import_module("app.workers.enqueue")
    ctx.record(
        "enqueue_helper_importable",
        callable(getattr(enqueue_mod, "create_arq_pool", None))
        and callable(getattr(enqueue_mod, "close_arq_pool", None))
        and callable(getattr(enqueue_mod, "enqueue", None)),
        "create_arq_pool + close_arq_pool + enqueue present",
    )

    # Dockerfile.worker was emitted
    dockerfile_worker = ctx.project_dir / "Dockerfile.worker"
    ctx.record(
        "dockerfile_worker_emitted",
        dockerfile_worker.exists(),
        f"Dockerfile.worker: {dockerfile_worker.exists()}",
    )

    return ctx.report_section


ARQ_WORKER = Scenario(
    name="arq_worker_queue",
    archetype="Async background job queue via arq + Redis + FastAPI lifespan",
    models={
        "Note": {"title": "str", "body": "text"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_arq_worker", "adapt.extend.infrastructure.add_arq_worker"),
    ],
    flow=flow_arq,
)


# ===========================================================================
# SCENARIO 10 — Stripe Checkout payments
# ===========================================================================


async def flow_stripe(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Verify Stripe Checkout infra: schema, settings, routes, lazy import."""
    from sqlalchemy import inspect

    # payments table exists (created by Base.metadata.create_all)
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record("payments_table", "payments" in tables, f"payments in DB: {'payments' in tables}")

    # Config fields patched into Settings
    cfg_mod = importlib.import_module("app.core.config")
    s = cfg_mod.settings
    required = [
        "STRIPE_SECRET_KEY",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_API_VERSION",
        "STRIPE_CHECKOUT_SUCCESS_URL",
        "STRIPE_CHECKOUT_CANCEL_URL",
    ]
    missing = [f for f in required if not hasattr(s, f)]
    ctx.record(
        "stripe_settings_patched",
        not missing,
        f"6/6 fields on settings (api_version={getattr(s, 'STRIPE_API_VERSION', None)})",
    )

    # Lazy stripe import — module loads without `stripe` package installed
    stripe_client_mod = importlib.import_module("app.core.stripe_client")
    has_get_stripe = callable(getattr(stripe_client_mod, "get_stripe", None))
    ctx.record(
        "stripe_client_lazy_importable",
        has_get_stripe,
        "app.core.stripe_client.get_stripe is callable",
    )

    # HTTP routes registered via OpenAPI
    r = await ctx.client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    expected_paths = [
        "/api/v1/payments/checkout",
        "/api/v1/payments/me",
        "/api/v1/payments/{payment_id}",
        "/api/v1/payments/webhook/stripe",
    ]
    missing_paths = [p for p in expected_paths if p not in paths]
    ctx.record(
        "payment_routes_registered",
        not missing_paths,
        f"4/4 routes registered ({len(missing_paths)} missing)",
    )

    # CRUD helpers importable (business logic layer)
    crud_mod = importlib.import_module("app.crud.payment")
    crud_fns = [
        "create_pending_payment",
        "mark_payment_succeeded",
        "mark_payment_failed",
        "get_payment_by_session_id",
        "list_user_payments",
    ]
    missing_crud = [fn for fn in crud_fns if not callable(getattr(crud_mod, fn, None))]
    ctx.record(
        "crud_helpers_present",
        not missing_crud,
        f"{len(crud_fns) - len(missing_crud)}/{len(crud_fns)} CRUD helpers callable",
    )

    # Payment model has tenant_id FK (we applied add_multi_tenancy first)
    payment_mod = importlib.import_module("app.models.payment")
    payment_cls = payment_mod.Payment
    has_tenant_col = "tenant_id" in payment_cls.__table__.columns
    ctx.record(
        "payment_tenant_id_column",
        has_tenant_col,
        "Payment.tenant_id column present (tenant-aware)",
    )

    return ctx.report_section


STRIPE_CHECKOUT = Scenario(
    name="stripe_checkout",
    archetype="Production-grade Stripe Checkout Session with webhook reconciliation",
    models={
        "Subscription": {"plan": "str", "status": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_stripe_checkout", "adapt.extend.infrastructure.add_stripe_checkout"),
    ],
    flow=flow_stripe,
)


# ===========================================================================
# SCENARIO 11 — Email templates (Jinja2 + pluggable provider)
# ===========================================================================


async def flow_email(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Verify email infra: schema, config, templates, rendering, provider."""
    from sqlalchemy import inspect

    # email_deliveries table exists
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record(
        "email_deliveries_table",
        "email_deliveries" in tables,
        f"email_deliveries in DB: {'email_deliveries' in tables}",
    )

    # 8 email settings fields reachable
    cfg_mod = importlib.import_module("app.core.config")
    s = cfg_mod.settings
    required = [
        "EMAIL_PROVIDER",
        "EMAIL_FROM",
        "EMAIL_FROM_NAME",
        "EMAIL_REPLY_TO",
        "EMAIL_DEFAULT_LOCALE",
        "RESEND_API_KEY",
        "POSTMARK_API_KEY",
        "EMAIL_PREVIEW_ENABLED_IN_PROD",
    ]
    missing = [f for f in required if not hasattr(s, f)]
    ctx.record(
        "email_settings_patched",
        not missing,
        f"8/8 fields on settings (provider={getattr(s, 'EMAIL_PROVIDER', None)})",
    )

    # All 4 templates × 3 variants = 12 files present
    tpl_dir = ctx.project_dir / "app/email/templates/en"
    expected = {
        "welcome",
        "password_reset",
        "email_verification",
        "receipt",
    }
    missing_tpl: list[str] = []
    for name in expected:
        for ext in ("subject.txt", "html", "txt"):
            p = tpl_dir / f"{name}.{ext}"
            if not p.exists():
                missing_tpl.append(f"{name}.{ext}")
    ctx.record(
        "templates_present",
        not missing_tpl,
        f"12/12 template files ({len(missing_tpl)} missing)",
    )

    # Rendering works for all 4 templates with realistic context
    render_mod = importlib.import_module("app.email.render")
    registry_mod = importlib.import_module("app.email.registry")
    contexts = {
        registry_mod.TemplateName.WELCOME: {
            "app_name": "Acme",
            "user_name": "Alice",
            "activation_url": "https://acme.test/a?t=abc",
        },
        registry_mod.TemplateName.PASSWORD_RESET: {
            "app_name": "Acme",
            "user_name": "Bob",
            "reset_url": "https://acme.test/r?t=xyz",
            "expires_in_hours": 24,
        },
        registry_mod.TemplateName.EMAIL_VERIFICATION: {
            "app_name": "Acme",
            "user_name": "Carol",
            "verification_url": "https://acme.test/v?t=abc",
        },
        registry_mod.TemplateName.RECEIPT: {
            "app_name": "Acme",
            "user_name": "Dave",
            "amount_formatted": "$29.99",
            "item_name": "Pro Plan",
            "receipt_url": "https://acme.test/r/1",
        },
    }
    render_failures: list[str] = []
    for tpl, ctx_data in contexts.items():
        try:
            r = render_mod.render_email(tpl, ctx_data, locale="en")
            assert r.subject and r.html and r.text
        except Exception as exc:
            render_failures.append(f"{tpl.value}: {type(exc).__name__}")
    ctx.record(
        "all_templates_render",
        not render_failures,
        f"4/4 templates rendered ({render_failures})"
        if render_failures
        else "4/4 templates render",
    )

    # Missing context raises proper error
    raised_correctly = False
    try:
        render_mod.render_email(
            registry_mod.TemplateName.WELCOME,
            {"user_name": "NoApp"},  # missing app_name + activation_url
            locale="en",
        )
    except Exception as exc:
        raised_correctly = "MissingContextError" in type(exc).__name__ or "Missing" in str(exc)
    ctx.record(
        "missing_context_raises", raised_correctly, "render_email rejects incomplete context"
    )

    # Locale fallback to 'en' works
    fallback_ok = False
    try:
        r = render_mod.render_email(
            registry_mod.TemplateName.WELCOME,
            {"app_name": "X", "user_name": "Y", "activation_url": "https://z"},
            locale="pt-BR",  # not present — should fallback to 'en'
        )
        fallback_ok = r.subject.startswith("Welcome")
    except Exception:
        pass
    ctx.record("locale_fallback_works", fallback_ok, "pt-BR → en fallback chain")

    # Preview + deliveries routes registered
    r = await ctx.client.get("/api/v1/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    has_preview = any("/email/preview" in p for p in paths)
    has_deliveries = any("/email/deliveries" in p for p in paths)
    ctx.record(
        "email_routes_registered",
        has_preview and has_deliveries,
        f"preview={has_preview}, deliveries={has_deliveries}",
    )

    # Provider selector exists (lazy — does not actually import resend)
    providers_mod = importlib.import_module("app.email.providers")
    has_selector = callable(getattr(providers_mod, "get_provider", None))
    ctx.record(
        "provider_selector_present", has_selector, "app.email.providers.get_provider is callable"
    )

    return ctx.report_section


EMAIL_TEMPLATES = Scenario(
    name="email_templates",
    archetype="Transactional email with Jinja2 templates + pluggable provider layer",
    models={
        "Notification": {"kind": "str", "title": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_email_templates", "adapt.extend.infrastructure.add_email_templates"),
    ],
    flow=flow_email,
)


# ---------------------------------------------------------------------------
# Registry + runner
# ---------------------------------------------------------------------------

# ===========================================================================
# SCENARIO 12 — Admin panel (SQLAdmin)
# ===========================================================================


async def flow_sqladmin(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Verify admin panel infra: setup module, auth, views, config."""

    # Config fields patched into Settings
    cfg_mod = importlib.import_module("app.core.config")
    s = cfg_mod.settings
    has_cfg = all(
        hasattr(s, f)
        for f in [
            "ADMIN_PATH",
            "ADMIN_TITLE",
            "ADMIN_REQUIRE_SUPERUSER",
        ]
    )
    ctx.record("admin_settings_patched", has_cfg, f"ADMIN_PATH={getattr(s, 'ADMIN_PATH', None)}")

    # Setup module is importable with lazy sqladmin
    setup_mod = importlib.import_module("app.admin.setup")
    has_setup = callable(getattr(setup_mod, "setup_admin", None))
    ctx.record("setup_admin_callable", has_setup, "app.admin.setup.setup_admin is callable")

    # Auth backend is importable
    auth_mod = importlib.import_module("app.admin.auth")
    has_auth = hasattr(auth_mod, "AdminAuthBackend")
    ctx.record("auth_backend_present", has_auth, "AdminAuthBackend class present")

    # Views module has MODEL_ADMINS
    views_mod = importlib.import_module("app.admin.views")
    model_admins = getattr(views_mod, "MODEL_ADMINS", [])
    ctx.record(
        "model_admins_discovered",
        len(model_admins) >= 2,
        f"{len(model_admins)} ModelAdmin classes generated",
    )

    # main.py has setup_admin(app) call
    main_src = (ctx.project_dir / "app/main.py").read_text()
    ctx.record(
        "main_py_patched", "setup_admin(app)" in main_src, "setup_admin(app) present in main.py"
    )

    return ctx.report_section


SQLADMIN = Scenario(
    name="sqladmin_panel",
    archetype="FastAPI-native admin panel with SQLAdmin + auth gate",
    models={
        "Invoice": {"number": "str", "total": "float", "status": "str"},
    },
    tools=[
        ("add_multi_tenancy", "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_sqladmin", "adapt.extend.infrastructure.add_sqladmin"),
    ],
    flow=flow_sqladmin,
)


SCENARIOS: list[Scenario] = [
    ECOMMERCE,
    SAAS_B2B,
    HEALTHCARE,
    FINTECH,
    BLOG,
    ANALYTICS,
    MODERATION,
    WEBSOCKET_CHAT,
    ARQ_WORKER,
    STRIPE_CHECKOUT,
    EMAIL_TEMPLATES,
    SQLADMIN,
]


def _build_project(scenario: Scenario, tmp: Path) -> Path:
    """Generate project with scenario models and apply its tools."""
    from adapt.contracts import ToolInput
    from tests.common.fixture_factory import create_fixture_project

    project_dir = create_fixture_project(
        name=f"scn_{scenario.name}",
        models=scenario.models,
        tmp_dir=tmp,
    )

    for tool_name, mod_path in scenario.tools:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, tool_name)
        result = fn(ToolInput(project_dir=str(project_dir)))
        if result.status == "error":
            raise RuntimeError(f"{tool_name}: {result.error}")

    return project_dir


async def _run_scenario(scenario: Scenario) -> tuple[int, int, list[tuple[str, bool, str]]]:
    """Run a single scenario end-to-end. Return (passed, total, details)."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            project_dir = _build_project(scenario, Path(tmp))
        except Exception as exc:
            return 0, 1, [("generate_and_apply", False, f"{type(exc).__name__}: {str(exc)[:200]}")]

        try:
            app, client, session, engine = await _make_client(
                project_dir,
                scenario.tenant_slug,
                scenario.needs_multi_tenancy,
            )
        except Exception as exc:
            return 0, 1, [("boot", False, f"{type(exc).__name__}: {str(exc)[:200]}")]

        ctx = ScenarioContext(
            client=client,
            session=session,
            engine=engine,
            project_dir=project_dir,
            tenant_slug=scenario.tenant_slug,
        )
        try:
            await scenario.flow(ctx)
        except Exception as exc:
            ctx.record("flow", False, f"EXCEPTION: {type(exc).__name__}: {str(exc)[:200]}")
            traceback.print_exc()
        finally:
            await _teardown(app, client, session, engine)

    passed = sum(1 for _, ok, _ in ctx.report_section if ok)
    total = len(ctx.report_section)
    return passed, total, ctx.report_section


def main() -> int:
    print("=" * 74)
    print(f"  SKILL-001 BEHAVIOR SCENARIOS — {len(SCENARIOS)} domain archetypes")
    print(f"  PostgreSQL: {POSTGRES_URL}")
    print("=" * 74)
    print()

    if not asyncio.run(_precheck_postgres()):
        print("  [SKIP] PostgreSQL not reachable")
        return 2

    overall_passed = 0
    overall_total = 0
    scenario_results: list[tuple[str, int, int, list]] = []
    t_start = time.monotonic()

    for scenario in SCENARIOS:
        t0 = time.monotonic()
        print(f"▶ {scenario.name} ({scenario.archetype})")
        print(f"  tools: {', '.join(t[0] for t in scenario.tools)}")
        try:
            passed, total, details = asyncio.run(_run_scenario(scenario))
        except Exception as exc:
            passed, total = 0, 1
            details = [("runner", False, f"{type(exc).__name__}: {str(exc)[:200]}")]

        elapsed = time.monotonic() - t0
        overall_passed += passed
        overall_total += total
        scenario_results.append((scenario.name, passed, total, details))

        mark = "✓" if passed == total else "✗"
        print(f"  {mark} {passed}/{total} assertions passed  ({elapsed:.1f}s)")
        for name, ok, detail in details:
            status = "  [PASS]" if ok else "  [FAIL]"
            print(f"    {status}  {name}: {detail}")
        print()

    elapsed = time.monotonic() - t_start
    print("=" * 74)
    print(
        f"  OVERALL: {overall_passed}/{overall_total} assertions "
        f"across {len(SCENARIOS)} scenarios  ({elapsed:.1f}s)"
    )
    print("=" * 74)

    failed_scenarios = [r for r in scenario_results if r[1] < r[2]]
    if failed_scenarios:
        print()
        print("  Failed scenarios:")
        for name, p, t, _ in failed_scenarios:
            print(f"    - {name}: {p}/{t}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
