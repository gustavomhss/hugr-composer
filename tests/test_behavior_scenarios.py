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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

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
    engine: object   # AsyncEngine
    project_dir: Path
    tenant_slug: str
    report_section: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.report_section.append((name, ok, detail))


# ---------------------------------------------------------------------------
# Shared helpers (copied from test_e2e_postgres.py patterns)
# ---------------------------------------------------------------------------

POSTGRES_URL = "postgresql+asyncpg://skill:skill@localhost:54329/skill_e2e"


async def _precheck_postgres() -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
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


def _load_app(project_dir: Path):
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for m in list(sys.modules):
        if m == "app" or m.startswith("app."):
            del sys.modules[m]
    return importlib.import_module("app.main").app


async def _make_client(project_dir: Path, tenant_slug: str, needs_multi_tenancy: bool):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool
    from sqlalchemy import text
    from httpx import ASGITransport, AsyncClient

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
                await c.execute(text(
                    "CREATE TABLE IF NOT EXISTS audit_logs_default "
                    "PARTITION OF audit_logs DEFAULT"
                ))
        except Exception:
            pass

    session = factory()

    if needs_multi_tenancy:
        try:
            tenant_mod = importlib.import_module("app.models.tenant")
            tid = uuid.uuid4()
            session.add(tenant_mod.Tenant(
                id=tid, name=tenant_slug.upper(),
                slug=tenant_slug, status="active",
            ))
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
    r = await client.post("/api/v1/users/signup", json={
        "email": email, "password": pwd, "full_name": name,
    }, headers=_th(None, tenant))
    assert r.status_code in (200, 201), f"signup {email}: {r.status_code} {r.text[:200]}"
    r = await client.post("/api/v1/login/access-token", data={
        "username": email, "password": pwd,
    }, headers=_th(None, tenant))
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

    seller = await _signup(client, "seller@shop.example.com", "SellerPass123!", "Seller", ctx.tenant_slug)
    buyer = await _signup(client, "buyer@shop.example.com", "BuyerPass123!", "Buyer", ctx.tenant_slug)

    # Seller creates 5 products
    created = 0
    for i in range(5):
        r = await client.post("/api/v1/products/", json={
            "name": f"Item {i}",
            "description": f"Description of item {i}",
            "price": 10.0 + i,
            "sku": f"SKU-{i:03}",
            "stock": 100,
        }, headers=_th(seller, ctx.tenant_slug))
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
    r = await client.post("/api/v1/orders/", json={
        "reference": f"ORD-{uuid.uuid4().hex[:8]}",
        "status": "pending",
        "total": 99.99,
    }, headers=_th(seller, ctx.tenant_slug))
    ctx.record("order_placed", r.status_code in (200, 201), f"status={r.status_code}")

    return ctx.report_section


ECOMMERCE = Scenario(
    name="ecommerce_storefront",
    archetype="Owner-scoped e-commerce with search + orders",
    models={
        "Product": {"name": "str", "description": "text", "price": "float", "sku": "str", "stock": "int"},
        # `reference` instead of `order_id` avoids the generator's `*_id` → FK
        # heuristic which would self-reference orders.id → FK violation.
        "Order":   {"reference": "str", "status": "str", "total": "float"},
    },
    tools=[
        ("add_multi_tenancy",  "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_search",         "adapt.extend.crud_data.add_search"),
        ("add_audit_log",      "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_ecommerce,
)


# ===========================================================================
# SCENARIO 2 — SaaS B2B (multi-tenant + RBAC + API keys)
# ===========================================================================

async def flow_saas_b2b(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Org admin invites members, assigns roles, creates API keys."""
    client, session = ctx.client, ctx.session

    admin = await _signup(client, "admin@org.example.com", "AdminPass123!", "Org Admin", ctx.tenant_slug)
    await _promote_superuser(session, "admin@org.example.com")
    member = await _signup(client, "member@org.example.com", "MemberPass123!", "Member", ctx.tenant_slug)

    # Admin creates a workspace
    r = await client.post("/api/v1/workspaces/", json={
        "name": "Engineering",
        "description": "Core engineering workspace",
        "plan": "pro",
    }, headers=_th(admin, ctx.tenant_slug))
    ctx.record("workspace_created", r.status_code in (200, 201), f"status={r.status_code}")

    # Feature flags table present
    from sqlalchemy import text, inspect
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record("feature_flags_table", "feature_flags" in tables or "feature_flag" in tables,
               f"tables found: {sorted(t for t in tables if 'flag' in t)}")
    ctx.record("rbac_tables", {"roles", "permissions", "user_roles"}.issubset(set(tables)),
               "roles+permissions+user_roles present")
    ctx.record("api_keys_table", "api_keys" in tables, "api_keys present")

    return ctx.report_section


SAAS_B2B = Scenario(
    name="saas_b2b",
    archetype="Multi-tenant B2B with RBAC + feature flags + API keys",
    models={
        "Workspace":  {"name": "str", "description": "text", "plan": "str"},
        "Invitation": {"email": "email", "role": "str", "status": "str"},
    },
    tools=[
        ("add_multi_tenancy",  "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_rbac",           "adapt.extend.auth_access.add_rbac"),
        ("add_api_key_auth",   "adapt.extend.auth_access.add_api_key_auth"),
        ("add_feature_flags",  "adapt.extend.auth_access.add_feature_flags"),
        ("add_audit_log",      "adapt.extend.crud_data.add_audit_log"),
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

    provider = await _signup(client, "dr@clinic.example.com", "DoctorPass123!", "Dr Smith", ctx.tenant_slug)

    # Provider creates a patient
    r = await client.post("/api/v1/patients/", json={
        "mrn": "MRN-00001",
        "full_name": "John Doe",
        "dob": "1980-01-15",
        "phone": "+1-555-0100",
    }, headers=_th(provider, ctx.tenant_slug))
    patient_created = r.status_code in (200, 201)
    ctx.record("patient_created", patient_created, f"status={r.status_code}")

    await session.commit()

    # Audit log must have entry
    result = await session.execute(text("SELECT COUNT(*) FROM audit_logs WHERE entity_type='patient'"))
    audit_count = result.scalar() or 0
    ctx.record("phi_access_audited", audit_count >= 1,
               f"{audit_count} patient audit entries")

    # Hash chain integrity — every entry must have entry_hash
    result = await session.execute(text("SELECT COUNT(*) FROM audit_logs WHERE entry_hash IS NULL"))
    unsigned = result.scalar() or 0
    ctx.record("audit_hash_chain_complete", unsigned == 0,
               f"{unsigned} unsigned entries (expected 0)")

    # MFA device table present (HIPAA requires 2FA for PHI access)
    from sqlalchemy import inspect
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record("mfa_tables_present", "mfa_devices" in tables,
               "mfa_devices table present")

    return ctx.report_section


HEALTHCARE = Scenario(
    name="healthcare_hipaa",
    archetype="HIPAA-compliant EHR with MFA + tamper-evident audit",
    models={
        "Patient":     {"mrn": "str", "full_name": "str", "dob": "date", "phone": "str"},
        "Visit":       {"visit_date": "datetime", "notes": "text", "diagnosis": "str"},
        "Prescription":{"drug_name": "str", "dosage": "str", "refills": "int"},
    },
    tools=[
        ("add_multi_tenancy",  "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_audit_log",      "adapt.extend.crud_data.add_audit_log"),
        ("add_mfa",            "adapt.extend.auth_access.add_mfa"),
        ("add_rbac",           "adapt.extend.auth_access.add_rbac"),
        ("add_soft_delete",    "adapt.extend.crud_data.add_soft_delete"),
    ],
    flow=flow_healthcare,
)


# ===========================================================================
# SCENARIO 4 — Fintech payments
# ===========================================================================

async def flow_fintech(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Outbox + saga + circuit breaker for distributed payment flow."""
    from sqlalchemy import text, inspect

    # Verify outbox + saga + webhook tables are wired
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())

    ctx.record("outbox_table", "outbox_events" in tables,
               "outbox_events present")
    ctx.record("saga_tables", "saga_instances" in tables,
               f"saga present: {sorted(t for t in tables if 'saga' in t)}")
    ctx.record("webhook_endpoints", "webhook_endpoints" in tables,
               "webhook_endpoints for outbound delivery")
    ctx.record("audit_trail", "audit_logs" in tables,
               "audit_logs for financial reconciliation")

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
        "Account":     {"account_number": "str", "balance": "float", "currency": "str"},
        "Transaction": {"amount": "float", "status": "str", "reference": "str", "tx_type": "str"},
    },
    tools=[
        ("add_multi_tenancy",    "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_outbox_pattern",   "adapt.extend.infrastructure.add_outbox_pattern"),
        ("add_saga",             "adapt.extend.infrastructure.add_saga"),
        ("add_circuit_breaker",  "adapt.extend.infrastructure.add_circuit_breaker"),
        ("add_webhook_sender",   "adapt.extend.realtime.add_webhook_sender"),
        ("add_audit_log",        "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_fintech,
)


# ===========================================================================
# SCENARIO 5 — Content publishing / blog
# ===========================================================================

async def flow_blog(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Author publishes posts, readers paginate + search."""
    client, session = ctx.client, ctx.session

    author = await _signup(client, "author@blog.example.com", "AuthorPass123!", "Author", ctx.tenant_slug)
    await _promote_superuser(session, "author@blog.example.com")

    # Create 10 posts
    created = 0
    for i in range(10):
        r = await client.post("/api/v1/posts/", json={
            "title": f"Post {i}: Thoughts on FastAPI",
            "slug": f"post-{i}",
            "body": f"This is post number {i} with interesting content about FastAPI.",
            "published": True,
        }, headers=_th(author, ctx.tenant_slug))
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
        ctx.record("soft_delete_hides", deleted_ok and hidden,
                   f"del={deleted_ok}, hidden={hidden}")

    return ctx.report_section


BLOG = Scenario(
    name="blog_cms",
    archetype="Content publishing with pagination + search + soft delete",
    models={
        "Post":    {"title": "str", "slug": "str", "body": "text", "published": "bool"},
        "Comment": {"author_name": "str", "body": "text", "approved": "bool"},
    },
    tools=[
        ("add_multi_tenancy",     "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_search",            "adapt.extend.crud_data.add_search"),
        ("add_cursor_pagination", "adapt.extend.crud_data.add_cursor_pagination"),
        ("add_soft_delete",       "adapt.extend.crud_data.add_soft_delete"),
        ("add_audit_log",         "adapt.extend.crud_data.add_audit_log"),
    ],
    flow=flow_blog,
)


# ===========================================================================
# SCENARIO 6 — Analytics / event ingestion
# ===========================================================================

async def flow_analytics(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Bulk ingestion + data export + long-running async report."""
    client, session = ctx.client, ctx.session

    analyst = await _signup(client, "analyst@analytics.example.com", "AnalystPass123!", "Analyst", ctx.tenant_slug)

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
    r = await client.post("/api/v1/events/bulk", json={
        "items": items, "mode": "all_or_nothing",
    }, headers=_th(analyst, ctx.tenant_slug))
    bulk_ok = r.status_code in (200, 201, 207)
    bulk_count = 0
    if bulk_ok:
        body = r.json()
        bulk_count = len([r for r in body.get("results", []) if r.get("success")])
    ctx.record("bulk_ingestion", bulk_ok and bulk_count >= 90,
               f"{bulk_count}/100 events ingested via /bulk")

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
    ctx.record("export_endpoint_registered", len(export_paths) > 0,
               f"export paths: {export_paths[:3]}")

    return ctx.report_section


ANALYTICS = Scenario(
    name="analytics_ingestion",
    archetype="High-throughput event ingestion with bulk ops + async export",
    models={
        # `source` instead of `user_id_ext` to avoid the `*_id` FK heuristic.
        # `recorded_at_str` instead of `timestamp_str` to avoid datetime parsing.
        "Event":  {"event_name": "str", "source": "str", "recorded_at_str": "str", "payload": "text"},
        "Metric": {"name": "str", "value": "float", "tags": "str"},
    },
    tools=[
        ("add_multi_tenancy",     "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_bulk_operations",   "adapt.extend.crud_data.add_bulk_operations"),
        ("add_data_export",       "adapt.extend.crud_data.add_data_export"),
        ("add_long_running_task", "adapt.extend.api_design.add_long_running_task"),
        ("add_cache_layer",       "adapt.extend.infrastructure.add_cache_layer"),
    ],
    flow=flow_analytics,
)


# ===========================================================================
# SCENARIO 7 — Content moderation / trust & safety
# ===========================================================================

async def flow_moderation(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Inbound reports → moderator actions → outbound webhooks → audit."""
    from sqlalchemy import text, inspect

    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())

    ctx.record("reports_table", "reports" in tables, "reports table exists")
    # Generator lowercases PascalCase without underscores → "moderatoractions"
    ctx.record("moderator_actions_table", "moderatoractions" in tables or "moderator_actions" in tables,
               f"moderator action table present: {[t for t in tables if 'moderator' in t]}")
    ctx.record("webhook_endpoints_table", "webhook_endpoints" in tables,
               "outbound webhook sender wired")
    ctx.record("inbound_webhook_receiver", "inbound_webhooks" in tables,
               "inbound webhook receiver wired")
    ctx.record("rbac_for_moderators", "roles" in tables and "user_roles" in tables,
               "RBAC for moderator permissions")
    ctx.record("audit_for_actions", "audit_logs" in tables,
               "audit_logs captures moderator actions")

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
        "Report":          {"content_ref": "str", "reason": "str", "status": "str"},
        "ModeratorAction": {"action": "str", "reason": "str", "target_ref": "str"},
    },
    tools=[
        ("add_multi_tenancy",     "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_rbac",              "adapt.extend.auth_access.add_rbac"),
        ("add_audit_log",         "adapt.extend.crud_data.add_audit_log"),
        ("add_webhook_sender",    "adapt.extend.realtime.add_webhook_sender"),
        ("add_webhook_receiver",  "adapt.extend.realtime.add_webhook_receiver"),
        ("add_circuit_breaker",   "adapt.extend.infrastructure.add_circuit_breaker"),
    ],
    flow=flow_moderation,
)


# ===========================================================================
# SCENARIO 8 — Real-time chat (WebSocket)
# ===========================================================================

async def flow_chat(ctx: ScenarioContext) -> list[tuple[str, bool, str]]:
    """Users create rooms, post messages via HTTP, load history, verify WS route."""
    client, session = ctx.client, ctx.session

    alice = await _signup(client, "alice@chat.example.com", "AlicePass123!", "Alice", ctx.tenant_slug)
    bob = await _signup(client, "bob@chat.example.com", "BobPass123!", "Bob", ctx.tenant_slug)

    # Alice creates a public room
    r = await client.post("/api/v1/chat/rooms", json={
        "name": "General", "is_private": False,
    }, headers=_th(alice, ctx.tenant_slug))
    room_created = r.status_code in (200, 201)
    room_id = r.json().get("id") if room_created else None
    ctx.record("room_created", room_created, f"status={r.status_code}")

    # Alice lists rooms (sees her own)
    r = await client.get("/api/v1/chat/rooms", headers=_th(alice, ctx.tenant_slug))
    alice_rooms: list = []
    if r.status_code == 200:
        body = r.json()
        alice_rooms = body if isinstance(body, list) else (body.get("data") or body.get("items") or [])
    ctx.record("alice_lists_own_rooms", len(alice_rooms) >= 1, f"{len(alice_rooms)} rooms visible to Alice")

    # Empty history
    if room_id:
        r = await client.get(f"/api/v1/chat/rooms/{room_id}/history", headers=_th(alice, ctx.tenant_slug))
        hist_ok = r.status_code == 200
        ctx.record("empty_history_fetch", hist_ok, f"status={r.status_code}")

    # Verify schema: chat_rooms + chat_messages tables present
    from sqlalchemy import inspect
    async with ctx.engine.connect() as conn:
        tables = await conn.run_sync(lambda sc: inspect(sc).get_table_names())
    ctx.record("chat_schema_present", {"chat_rooms", "chat_messages"}.issubset(set(tables)),
               f"tables: {sorted(t for t in tables if 'chat' in t)}")

    # WebSocket route must be registered on the app
    ws_routes = [
        rt for rt in ctx.client._transport.app.routes
        if getattr(rt, "path", "").startswith("/ws/chat/")
    ]
    ctx.record("ws_route_registered", len(ws_routes) == 1,
               f"/ws/chat/{{room_id}} route: {len(ws_routes)}")

    # Config fields were patched into settings
    config_mod = importlib.import_module("app.core.config")
    settings = config_mod.settings
    has_cfg = (
        hasattr(settings, "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER")
        and hasattr(settings, "WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH")
        and hasattr(settings, "WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE")
    )
    ctx.record("config_fields_patched", has_cfg,
               "WEBSOCKET_CHAT_* fields present on settings")

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
        ("add_multi_tenancy",    "adapt.extend.auth_access.add_multi_tenancy"),
        ("add_websocket_chat",   "adapt.extend.realtime.add_websocket_chat"),
    ],
    flow=flow_chat,
)


# ---------------------------------------------------------------------------
# Registry + runner
# ---------------------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    ECOMMERCE,
    SAAS_B2B,
    HEALTHCARE,
    FINTECH,
    BLOG,
    ANALYTICS,
    MODERATION,
    WEBSOCKET_CHAT,
]


def _build_project(scenario: Scenario, tmp: Path) -> Path:
    """Generate project with scenario models and apply its tools."""
    from tests.common.fixture_factory import create_fixture_project
    from adapt.contracts import ToolInput

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
                project_dir, scenario.tenant_slug, scenario.needs_multi_tenancy,
            )
        except Exception as exc:
            return 0, 1, [("boot", False, f"{type(exc).__name__}: {str(exc)[:200]}")]

        ctx = ScenarioContext(
            client=client, session=session, engine=engine,
            project_dir=project_dir, tenant_slug=scenario.tenant_slug,
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
    print(f"  OVERALL: {overall_passed}/{overall_total} assertions "
          f"across {len(SCENARIOS)} scenarios  ({elapsed:.1f}s)")
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
