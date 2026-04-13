# TOOL-008: add_multi_tenancy

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_multi_tenancy` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User model), Alembic, at least 1 business model |
| Signature | `add_multi_tenancy(project_dir: str, models: list[str] \| None = None, strategy: Literal["shared_db", "schema_per_tenant", "db_per_tenant"] = "shared_db", resolver: Literal["header", "subdomain", "jwt"] = "header", default_tenant_slug: str = "default") -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: model names to make tenant-scoped (None = all business models, excluding User and Tenant)<br>`strategy`: tenant isolation strategy<br>`resolver`: how to extract tenant from request<br>`default_tenant_slug`: slug used to backfill existing rows during migration |

---

## 2. Purpose

The `fastapi_add_multi_tenancy` tool adds hard tenant isolation to a FastAPI application so that multiple customers (tenants) share the same deployment without ever seeing each other's data, and turns "multi-tenant" from a hope into a verified invariant. Multi-tenancy is the single most expensive property to retrofit because it touches every model, every query, every migration, every admin tool, and every log line — a single missing `WHERE tenant_id = ?` clause on a list endpoint leaks one customer's records to another and destroys the product in a single incident. Teams that bolt tenancy on by hand inevitably ship subtle leaks because the correctness of their tenant filter depends on every developer remembering a convention on every new query, and that convention fails under pressure.

The tool introduces a `Tenant` model with a stable slug, a `tenant_id` column on every business model (added via a reversible Alembic migration with a backfill for the default tenant), request-scoped tenant context propagated through FastAPI dependencies, and an **automatic SQLAlchemy global filter** that appends `WHERE tenant_id = :current_tenant_id` to every SELECT against a tenant-scoped model unless the code explicitly opts out via a documented escape hatch. Cross-tenant data access is treated as a CRITICAL invariant violation and blocked at three independent layers: middleware that rejects requests with missing or mismatched `X-Tenant-ID`, ORM event listeners that raise on queries without a tenant filter, and an optional database-level Row-Level Security policy for PostgreSQL deployments that want defense-in-depth. Key design decisions: deny-by-default on missing context, explicit escape hatches for superadmin operations (audited), a hash-based tenant resolution strategy so tenant context is cryptographically bound to the authenticated user's JWT claims, and integration with TOOL-005 audit_log so every cross-tenant attempt is recorded even when the middleware catches it before the query runs.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s for up to 10 models | Dev waits in CLI |
| Files modified | ≤ 5 per model + 6 global files | Predictability |
| Files created | 1 migration + 1 tenant model + 1 middleware + 1 context module + N test files | Predictability |
| Tenant resolution overhead | < 1 ms per request | contextvars + cached lookup; no extra DB hit when tenant is cached |
| Query overhead with auto-filter | < 5% vs unfiltered | Composite index `(tenant_id, created_at)` ensures O(log n) |
| Migration runtime | < 60s on 10M rows | Online `ALTER TABLE ADD COLUMN` + batched UPDATE for backfill |
| Memory overhead | < 1 MB per worker | Tenant cache bounded to 10k entries via LRU |
| Cross-tenant leak detection | 0 false negatives | `with_loader_criteria` runs on EVERY select; mismatch raises immediately |

---

## 4. Code Examples (Before / After)

### 4.1 Model: BEFORE
```python
# app/models/item.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### 4.2 Model: AFTER
```python
# app/models/item.py
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
from app.models.mixins import TenantScopedMixin
import uuid


class Item(TenantScopedMixin, Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_items_tenant_created", "tenant_id", "created_at"),
    )
```

```python
# app/models/mixins.py
from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
import uuid


class TenantScopedMixin:
    """Adds tenant_id FK to a model, NOT NULL, indexed."""

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            Uuid,
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
```

### 4.3 Tenant model (NEW)
```python
# app/models/tenant.py
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_tenants_status",
        ),
        CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'",
            name="ck_tenants_slug_format",
        ),
    )
```

### 4.4 Tenant context (NEW)
```python
# app/core/tenant_context.py
from contextvars import ContextVar
from uuid import UUID

# None = no tenant resolved (system context, e.g. background jobs without tenant scope)
_current_tenant_id: ContextVar[UUID | None] = ContextVar("current_tenant_id", default=None)


def set_current_tenant(tenant_id: UUID | None) -> None:
    _current_tenant_id.set(tenant_id)


def get_current_tenant() -> UUID | None:
    return _current_tenant_id.get()


def require_current_tenant() -> UUID:
    tid = _current_tenant_id.get()
    if tid is None:
        raise RuntimeError(
            "TenantContextMissing: no tenant in context. "
            "Either the request did not pass through TenantMiddleware, "
            "or this code path runs outside a tenant scope."
        )
    return tid
```

### 4.5 Middleware (NEW)
```python
# app/api/middleware/tenant.py
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.db import async_session_maker
from app.core.tenant_context import set_current_tenant
from app.models.tenant import Tenant


# Routes that do NOT require a tenant context (login, public docs, healthcheck)
TENANT_FREE_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register", "/health", "/docs", "/openapi.json"}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolve tenant from request and set it in contextvar before view runs.
    Resolver is configured in app.core.config (RESOLVER=header|subdomain|jwt).
    """

    def __init__(self, app, resolver: str = "header"):
        super().__init__(app)
        self.resolver = resolver

    async def dispatch(self, request: Request, call_next):
        if request.url.path in TENANT_FREE_PATHS:
            set_current_tenant(None)
            return await call_next(request)

        slug = self._extract_slug(request)
        if not slug:
            return JSONResponse(
                {"detail": "Tenant not specified"},
                status_code=400,
            )

        async with async_session_maker() as session:
            stmt = select(Tenant).where(Tenant.slug == slug)
            tenant = (await session.execute(stmt)).scalar_one_or_none()

        if tenant is None:
            return JSONResponse({"detail": "Unknown tenant"}, status_code=404)
        if tenant.status != "active":
            return JSONResponse({"detail": "Tenant is not active"}, status_code=403)

        set_current_tenant(tenant.id)
        try:
            return await call_next(request)
        finally:
            set_current_tenant(None)

    def _extract_slug(self, request: Request) -> str | None:
        if self.resolver == "header":
            return request.headers.get("X-Tenant-ID")
        if self.resolver == "subdomain":
            host = request.headers.get("host", "")
            return host.split(".")[0] if "." in host else None
        if self.resolver == "jwt":
            # Parsed by auth dep; middleware reads it from request.state
            return getattr(request.state, "tenant_slug", None)
        return None
```

### 4.6 Auto-filter listener (NEW)
```python
# app/core/tenant_filter.py
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.tenant_context import get_current_tenant
from app.models.mixins import TenantScopedMixin


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_filter(execute_state) -> None:
    """
    For every SELECT against a TenantScopedMixin model, inject
    `WHERE tenant_id = :current_tenant`. If no tenant is set, the
    query MUST opt-in via execution option `skip_tenant_filter=True`.
    """
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_tenant_filter"):
        return

    tenant_id = get_current_tenant()
    if tenant_id is None:
        # No tenant in context: refuse to query tenant-scoped models silently.
        # The query must explicitly opt out (e.g. background jobs scanning all tenants).
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScopedMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )
```

### 4.7 CRUD: BEFORE
```python
# app/crud/item.py (fragment)
async def create(session: AsyncSession, *, item_in: ItemCreate, owner_id: UUID) -> Item:
    item = Item(**item_in.model_dump(), owner_id=owner_id)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item
```

### 4.8 CRUD: AFTER
```python
# app/crud/item.py (fragment)
from app.core.tenant_context import require_current_tenant


async def create(session: AsyncSession, *, item_in: ItemCreate, owner_id: UUID) -> Item:
    tenant_id = require_current_tenant()
    item = Item(**item_in.model_dump(), owner_id=owner_id, tenant_id=tenant_id)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item
```

### 4.9 Migration
```python
# alembic/versions/0008_add_multi_tenancy.py
"""add multi tenancy

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active','suspended','archived')", name="ck_tenants_status"),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'", name="ck_tenants_slug_format"),
    )

    # 2. Insert default tenant for backfill
    op.execute(
        "INSERT INTO tenants (id, slug, name) VALUES "
        "(gen_random_uuid(), 'default', 'Default Tenant')"
    )

    # 3. Add tenant_id column to each business model — initially NULL-able
    for table in ("items", "orders", "products"):
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))

    # 4. Backfill: assign every existing row to default tenant
    op.execute(
        "UPDATE items   SET tenant_id = (SELECT id FROM tenants WHERE slug='default') WHERE tenant_id IS NULL;"
    )
    op.execute(
        "UPDATE orders  SET tenant_id = (SELECT id FROM tenants WHERE slug='default') WHERE tenant_id IS NULL;"
    )
    op.execute(
        "UPDATE products SET tenant_id = (SELECT id FROM tenants WHERE slug='default') WHERE tenant_id IS NULL;"
    )

    # 5. Promote to NOT NULL + add FK + composite index
    for table in ("items", "orders", "products"):
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_tenant_created", table, ["tenant_id", "created_at"])


def downgrade() -> None:
    for table in ("items", "orders", "products"):
        op.drop_index(f"ix_{table}_tenant_created", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    op.drop_table("tenants")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Cross-tenant leakage is impossible at runtime** | `do_orm_execute` listener injects `tenant_id` filter on EVERY select against `TenantScopedMixin`. Bypass requires explicit `skip_tenant_filter=True` execution option. |
| QS-2 | **Tenant resolution is single-source** | Exactly one middleware sets the contextvar. CRUD reads via `require_current_tenant()`. No code path may set the contextvar from inside a request handler. |
| QS-3 | **Migration is online and reversible** | Backfill uses default tenant; column added nullable, backfilled, then promoted to NOT NULL. `downgrade()` drops in reverse. |
| QS-4 | **Tenant context is per-request, never global** | `contextvars.ContextVar` ensures isolation across concurrent async requests in the same worker. Verified by T-19. |
| QS-5 | **CREATE always stamps current tenant** | CRUD `create()` calls `require_current_tenant()` and sets `tenant_id` explicitly. Forgetting raises `TenantContextMissing` at runtime. |
| QS-6 | **Background jobs must opt-in to a tenant** | A background worker that touches tenant-scoped models MUST call `set_current_tenant(tid)` at the start of each task; otherwise queries return empty (or fail loudly when CREATE is attempted). |
| QS-7 | **The User model is NOT tenant-scoped by default** | A user may belong to a tenant via `users.tenant_id`, but the User table itself is global; this is intentional to allow superadmins. The tool warns if `User` is passed in `models`. |
| QS-8 | **Tenant slug is URL-safe and predictable** | DB CheckConstraint `^[a-z0-9][a-z0-9-]{0,62}$` rejects invalid slugs at insert time. |
| QS-9 | **Foreign keys to tenants use ON DELETE RESTRICT** | A tenant cannot be deleted if it owns any rows. Forces explicit data lifecycle. |
| QS-10 | **Auto-filter is opt-out, never opt-in** | `with_loader_criteria` is added by default. Skipping requires the explicit `skip_tenant_filter=True` execution option, which is grep-able and reviewable. |
| QS-11 | **Middleware short-circuits on missing/invalid tenant** | 400 if header missing, 404 if slug unknown, 403 if tenant suspended. No request reaches the route. |
| QS-12 | **All write operations pass input validation before touching storage** | Enforced by Pydantic v2 schema validation in `app/schemas/` — every request body is parsed and rejected with 422 on malformed data, verified by `tests/test_schemas.py::test_validation` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `Tenant` model exists at `app/models/tenant.py` | File exists, parses |
| CC-02 | `TenantScopedMixin` exists at `app/models/mixins.py` | File exists, contains `tenant_id` declared_attr |
| CC-03 | All target business models inherit from `TenantScopedMixin` | grep `class .*\(TenantScopedMixin` |
| CC-04 | Each tenant-scoped table has composite index `(tenant_id, created_at)` | Inspect `__table_args__` |
| CC-05 | `tenant_context.py` module exists with `get/set/require_current_tenant` | File exists, exports verified |
| CC-06 | `tenant_filter.py` registers `do_orm_execute` listener | grep `@event.listens_for(Session, "do_orm_execute")` |
| CC-07 | `TenantMiddleware` registered in `main.py` after auth middleware | grep `app.add_middleware(TenantMiddleware` |
| CC-08 | Resolver value (`header`/`subdomain`/`jwt`) is configurable via `settings.TENANT_RESOLVER` | Found in `core/config.py` |
| CC-09 | Migration creates tenants table + inserts default tenant + backfills + promotes NOT NULL | Inspect upgrade() |
| CC-10 | Migration `downgrade()` drops in correct reverse order | Inspect downgrade() |
| CC-11 | Migration uses `ON DELETE RESTRICT` on FK | grep `ondelete="RESTRICT"` |
| CC-12 | Default tenant slug is configurable via `default_tenant_slug` param | Slug appears in migration |
| CC-13 | CRUD `create()` for every tenant-scoped model calls `require_current_tenant()` | grep `require_current_tenant\(\)` in each crud file |
| CC-14 | Tenant slug CheckConstraint matches regex | Inspect Tenant model |
| CC-15 | Tenant status CheckConstraint matches enum | Inspect Tenant model |
| CC-16 | New endpoints `POST /tenants`, `GET /tenants/{slug}`, `PATCH /tenants/{slug}` exist (admin-only) | Routes file inspected |
| CC-17 | TENANT_FREE_PATHS list contains login/register/health/docs | grep TENANT_FREE_PATHS |
| CC-18 | OpenAPI exposes new tenant endpoints | Curl `/openapi.json`, paths present |
| CC-19 | Existing test suite passes | pytest 0 failures |
| CC-20 | New file `tests/test_multi_tenancy.py` created with 30 tests | File exists |
| CC-21 | All target models verified with `ast.parse` after edit | Tool internal step |
| CC-22 | Tool execution time < 5s | Time measurement |
| CC-23 | Per-request tenant overhead < 1ms | Benchmark T-29 |
| CC-24 | Cross-tenant query returns empty for the wrong tenant | T-01, T-02 |
| CC-25 | `skip_tenant_filter=True` execution option works for system queries | T-22 |
| CC-26 | Idempotent: re-run leaves no extra columns | T-26 |
| CC-27 | Schemas (`Public/Create/Update`) do NOT expose `tenant_id` | grep absent in schemas |
| CC-28 | Foreign key `fk_<table>_tenant` exists in DB | psql `\d+ items` shows it |
| CC-29 | Existing benchmark unchanged after modification | Run analyzer |
| CC-30 | Backfill query is batched (`UPDATE ... LIMIT`) for tables > 1M rows | Migration uses batched UPDATE |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 30 Completeness Criteria verified
- [ ] All 11 Quality Standards enforced
- [ ] All 8 Invariants enforced (see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (see §10)
- [ ] Tool is idempotent: run twice, identical state
- [ ] Tool is reversible: rollback procedure documented and tested (see §12)
- [ ] Migration safety: tested on simulated 10M-row table
- [ ] Performance budget met: filter overhead < 5%, resolution < 1 ms
- [ ] Interaction with other tools verified (see §11)
- [ ] All 15 edge cases handled
- [ ] Documentation updated (KNOWLEDGE.md, manifest.yaml, SKILL.md)
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-MT-01 | A query against a tenant-scoped model **never** returns rows from another tenant | `do_orm_execute` listener adds `WHERE tenant_id = current_tenant` unconditionally | T-01, T-02, T-19 |
| INV-MT-02 | A row **never** exists with `tenant_id IS NULL` after migration is complete | DB column `NOT NULL` + FK to `tenants(id)` | T-13 |
| INV-MT-03 | Tenant context is **never** shared across concurrent requests | `contextvars.ContextVar` is per-task | T-19 |
| INV-MT-04 | A `CREATE` against a tenant-scoped model with no tenant context **always** raises | `require_current_tenant()` raises `RuntimeError` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-07 |
| INV-MT-05 | A tenant in `suspended` or `archived` status **never** receives request handlers | Middleware returns 403 before `call_next` | T-14 |
| INV-MT-06 | Deleting a tenant with rows referencing it **always** fails with FK violation | FK uses `ON DELETE RESTRICT` | T-15 |
| INV-MT-07 | The `User` model is **never** silently made tenant-scoped | Tool emits warning + skips `User` unless `--include-user` is explicitly passed | T-26 |
| INV-MT-08 | `tenant_id` is **never** exposed in public API responses | Schemas exclude `tenant_id` from `*Public` classes | T-23 |

---

## 9. User Stories

### 9.1 Tenant provisioning & lifecycle (US-01 .. US-05)

**US-01: Onboard a new SaaS customer as an isolated tenant**
- **As a** backend developer launching a B2B SaaS product
- **I want** to call `add_multi_tenancy(project_dir, models=["Item", "Order", "Product"])` once
- **So that** every new customer I provision gets hard data isolation without me touching any CRUD code
- **Given:** A project with `Item`, `Order`, `Product` models, Alembic configured, auth enabled
- **When:** I call `add_multi_tenancy(project_dir, models=["Item", "Order", "Product"])`
- **Then:**
  - All three models inherit `TenantScopedMixin` and gain a `tenant_id` FK column (CC-02, CC-03)
  - `app/models/tenant.py` is created with the `Tenant` model and slug CheckConstraint (CC-01, CC-14)
  - `TenantMiddleware` is registered in `main.py` after the auth middleware (CC-07)
  - A reversible Alembic migration `0008_add_multi_tenancy.py` is generated (CC-09)
  - Tool returns `{files_created: [...], files_modified: [...], notes: [...]}` in < 5s (CC-22)

**US-02: Provision a new tenant with a stable URL-safe slug**
- **As an** ops engineer creating a customer account for "Acme Corp"
- **I want** to `POST /tenants/` with `{slug: "acme", name: "Acme Corp"}`
- **So that** Acme's users can reach their workspace via a predictable URL slug that never changes
- **Given:** No tenant with slug `acme` exists, request carries a superadmin JWT
- **When:** `POST /tenants/ {slug: "acme", name: "Acme Corp"}`
- **Then:**
  - 201 Created; response body contains `{id: <uuid>, slug: "acme", name: "Acme Corp", status: "active"}` (CC-16)
  - Database row has `status = 'active'` from `server_default` (CC-15)
  - Attempting `POST /tenants/ {slug: "acme!!", name: "Bad"}` is rejected by DB CheckConstraint with 422 (CC-14)
  - The slug `acme` is immutable — no PATCH endpoint allows changing it (INV-MT-02)

**US-03: Suspend a tenant that violates terms of service**
- **As an** ops engineer responding to a fraud report for tenant `bad-actor`
- **I want** to `PATCH /tenants/bad-actor {status: "suspended"}`
- **So that** all of `bad-actor`'s API traffic is blocked immediately without dropping their data
- **Given:** Tenant `bad-actor` has `status = 'active'` and 500 rows in `items`
- **When:** I call `PATCH /tenants/bad-actor {status: "suspended"}`
- **Then:**
  - Next request bearing `X-Tenant-ID: bad-actor` receives 403 before `call_next` runs (INV-MT-05)
  - `bad-actor`'s 500 rows remain intact in the DB — no data deletion (CC-10)
  - Active tenants' traffic is completely unaffected (INV-MT-03)
  - Status can be set back to `active` to unblock the tenant (CC-15)

**US-04: Archive and delete a churned customer's tenant**
- **As a** DBA offboarding a customer whose contract expired
- **I want** to `PATCH /tenants/churned-co {status: "archived"}` then delete their data before `DELETE FROM tenants WHERE slug='churned-co'`
- **So that** GDPR right-to-erasure obligations are met and no orphan rows remain
- **Given:** Tenant `churned-co` still has rows in `items` and `orders`
- **When:** I attempt `DELETE FROM tenants WHERE slug='churned-co'` with rows still present
- **Then:**
  - The DB raises a FK violation (`fk_items_tenant` with `ON DELETE RESTRICT`) — tenant cannot be deleted while rows exist (INV-MT-06, CC-11)
  - After deleting all `churned-co` rows from business tables, the tenant row can be deleted cleanly
  - `downgrade()` migration code does NOT cascade-delete tenant rows automatically (CC-10)

**US-05: Rename a tenant's display name without breaking existing URLs**
- **As an** ops engineer whose customer "Startup Inc" rebranded to "Enterprise Co"
- **I want** to update the tenant's `name` field without touching the `slug`
- **So that** the customer's API URLs (which embed the slug) remain stable
- **Given:** Tenant with `slug = 'startup-inc'`, `name = 'Startup Inc'`
- **When:** `PATCH /tenants/startup-inc {name: "Enterprise Co"}`
- **Then:**
  - Response returns `{slug: "startup-inc", name: "Enterprise Co", status: "active"}` (CC-16)
  - All rows in `items`, `orders` still reference the same `tenant_id` UUID — no migration needed
  - `GET /tenants/startup-inc` still works (slug unchanged)
  - The `slug` field is absent from the PATCH schema to prevent accidental slug mutation (INV-MT-08)

### 9.2 Cross-tenant isolation enforcement (US-06 .. US-10)

**US-06: ORM auto-filter blocks cross-tenant list access**
- **As a** security auditor verifying data isolation between tenants
- **I want** to confirm that `GET /items/` for tenant B never returns tenant A's items
- **So that** a customer can never see a competitor's data even if they guess the right URL
- **Given:** Tenant A has 3 items with IDs `[aa-1, aa-2, aa-3]`; Tenant B has 2 items `[bb-1, bb-2]`; request authenticated as Tenant B with `X-Tenant-ID: tenant-b`
- **When:** `GET /items/` is called
- **Then:**
  - Response body contains exactly 2 items belonging to Tenant B (INV-MT-01)
  - `aa-1`, `aa-2`, `aa-3` are absent from the response — the `do_orm_execute` listener injected `WHERE tenant_id = tenant_b.id` (CC-06)
  - SQL query log shows a single `WHERE items.tenant_id = $1` predicate (T-01, T-02)

**US-07: ORM auto-filter returns 404 on cross-tenant GET by ID**
- **As a** penetration tester probing for IDOR (Insecure Direct Object Reference) vulnerabilities
- **I want** to confirm that `GET /items/aa-1` as Tenant B returns 404, not Tenant A's data
- **So that** UUID enumeration attacks cannot extract other tenants' records
- **Given:** Item `id=aa-1` belongs to Tenant A; request uses `X-Tenant-ID: tenant-b`
- **When:** `GET /items/aa-1` is called
- **Then:**
  - Response is 404 Not Found — the ORM query returns no row because the `with_loader_criteria` filter excludes `aa-1` (INV-MT-01, T-03)
  - No `aa-1` data is present anywhere in the response body or headers
  - The route handler never receives the item — the CRUD layer raises `not found` before returning (CC-06, CC-13)

**US-08: Middleware blocks requests with missing tenant header before query runs**
- **As a** backend developer debugging a misconfigured API client that omits `X-Tenant-ID`
- **I want** a clear 400 error before any DB query runs
- **So that** missing context fails loudly and I can diagnose the misconfiguration immediately
- **Given:** `resolver=header` configured; request has no `X-Tenant-ID` header; path is `/api/v1/items/`
- **When:** `GET /api/v1/items/` is called without the header
- **Then:**
  - Response is `400 {"detail": "Tenant not specified"}` — returned by `TenantMiddleware.dispatch` before `call_next` (CC-07, CC-17)
  - Zero DB queries are executed
  - Auth and business route handlers are never invoked
  - Health check at `/health` is excluded from this enforcement (CC-17)

**US-09: Superadmin bypass reads all tenants' data for cross-tenant analytics**
- **As a** superadmin building an internal dashboard that aggregates data across all tenants
- **I want** to run a query with `execution_options={"skip_tenant_filter": True}` to bypass the auto-filter
- **So that** I can generate platform-level metrics without touching per-tenant scoped endpoints
- **Given:** 5 tenants each with 100 items (500 total); superadmin code calls `crud.get_multi(session, execution_options={"skip_tenant_filter": True})`
- **When:** The query executes
- **Then:**
  - All 500 rows are returned regardless of current tenant context (CC-25, T-22)
  - The bypass is explicit — grep for `skip_tenant_filter` in code review is straightforward (CC-10)
  - The action is recorded in the audit log tagged as `SYSTEM_QUERY` (INV-MT-01 escape hatch)
  - Normal requests through `TenantMiddleware` are NOT affected by the system query

**US-10: RLS database layer provides defense-in-depth on direct DB connections**
- **As a** security auditor reviewing the three-layer isolation model
- **I want** to verify that a PostgreSQL session connecting directly (bypassing the app) still cannot read another tenant's rows
- **So that** a compromised application credential cannot exfiltrate cross-tenant data
- **Given:** `strategy="shared_db"` with RLS enabled; psql session connects as app DB user `appuser`; tenant A's data exists
- **When:** `SET app.current_tenant_id = '<tenant_b_uuid>'; SELECT * FROM items;` runs via psql
- **Then:**
  - Only Tenant B's rows are returned — the RLS policy `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)` filters at the DB layer (INV-MT-01)
  - A psql session with no `SET app.current_tenant_id` returns zero rows, not all rows
  - The RLS policy is generated by the tool in the migration's `upgrade()` function (CC-09)

### 9.3 Tenant context propagation (US-11 .. US-15)

**US-11: JWT claim resolver binds tenant to authenticated user cryptographically**
- **As a** backend developer implementing a zero-trust tenant architecture
- **I want** to use `resolver=jwt` so that the tenant is read from the user's signed JWT, not from a header the client can forge
- **So that** a user cannot escalate to a different tenant by spoofing `X-Tenant-ID`
- **Given:** `resolver=jwt` configured; user logs in and receives a JWT with claim `{"tenant_slug": "acme", "sub": "user-123"}`
- **When:** The user makes `GET /items/` with the JWT in the `Authorization: Bearer` header
- **Then:**
  - `TenantMiddleware` reads `request.state.tenant_slug` set by the auth middleware (CC-08)
  - Tenant is resolved to `acme` and context set — no `X-Tenant-ID` header is consulted (CC-08, T-10)
  - A request with a valid JWT for `acme` but `X-Tenant-ID: evil-corp` in headers is unaffected — JWT resolver ignores the header (INV-MT-03)
  - Switching to `resolver=header` is a one-line config change in `settings.TENANT_RESOLVER` (CC-08)

**US-12: Subdomain resolver extracts tenant from Host header for white-label deployments**
- **As a** developer building a white-label SaaS where each customer gets `acme.example.com`
- **I want** `resolver=subdomain` to automatically resolve the tenant from the `Host` header
- **So that** customers do not need to set a separate `X-Tenant-ID` header
- **Given:** `resolver=subdomain` configured; request arrives at `acme.example.com/api/v1/items/`
- **When:** The `Host: acme.example.com` header is present
- **Then:**
  - Middleware splits on `.` and resolves slug `acme` to the Tenant DB record (T-09)
  - If the app sits behind an nginx proxy that sets `X-Forwarded-Host`, middleware falls back to that header (EC-8)
  - A bare domain request `example.com` with no subdomain returns 400 `{"detail": "Tenant not specified"}` (CC-07)
  - The resolved tenant's ID is set in `_current_tenant_id` via `set_current_tenant(tenant.id)` (CC-05)

**US-13: Background Celery job sets tenant context before touching tenant-scoped models**
- **As a** backend developer writing a nightly invoice-generation job that runs per tenant
- **I want** to call `set_current_tenant(tenant_id)` at the start of each task so the ORM filter is active
- **So that** the job cannot accidentally generate invoices mixing two tenants' data
- **Given:** A Celery task `generate_invoices(tenant_id: UUID)` that calls `crud.item.get_multi(session)`
- **When:** The task runs `set_current_tenant(tenant_id)` then queries items
- **Then:**
  - Only items belonging to `tenant_id` are returned — the contextvar propagates into the ORM listener (CC-05, CC-06)
  - A second concurrent task for a different tenant has its own `ContextVar` token — no bleed between tasks (INV-MT-03, T-19)
  - If `set_current_tenant` is NOT called, `crud.item.get_multi` returns an empty list (not all tenants' data) because `tenant_id = NULL` matches nothing (QS-6)

**US-14: Webhook handler routes inbound events to the correct tenant context**
- **As a** backend developer processing inbound Stripe webhooks that arrive on a single endpoint
- **I want** to extract the tenant ID from the webhook payload metadata before any DB work
- **So that** the `Invoice` record created from the webhook is stamped with the correct tenant
- **Given:** Stripe sends `POST /webhooks/stripe` with `{metadata: {tenant_id: "<uuid>"}}`; the endpoint is in `TENANT_FREE_PATHS` (no middleware resolution needed)
- **When:** The handler calls `set_current_tenant(UUID(payload["metadata"]["tenant_id"]))` then `await crud.invoice.create(session, ...)`
- **Then:**
  - The new `Invoice` row has `tenant_id = <uuid>` set by `require_current_tenant()` in the CRUD layer (CC-13, INV-MT-04)
  - If `metadata.tenant_id` is absent, `require_current_tenant()` raises `TenantContextMissing` and the webhook returns 500 (INV-MT-04)
  - `TENANT_FREE_PATHS` includes `/webhooks/` so the middleware does not reject the request (CC-17)

**US-15: FastAPI dependency injects tenant object into route handlers**
- **As a** backend developer writing a route handler that needs the full `Tenant` object (not just the ID)
- **I want** a `Depends(get_current_tenant_obj)` injection so I can access `tenant.name` and `tenant.status` without an extra DB query
- **So that** I can render a tenant-personalized response without coupling route code to tenant resolution logic
- **Given:** `TenantMiddleware` has already set `_current_tenant_id` to Acme's UUID; the handler signature is `async def list_items(tenant: Tenant = Depends(get_current_tenant_obj))`
- **When:** `GET /items/` is called for Acme
- **Then:**
  - The dependency resolves `Tenant` from the contextvar (no additional DB query if cached) (CC-05, CC-23)
  - `tenant.name == "Acme Corp"` and `tenant.status == "active"` are accessible inside the handler
  - If the tenant is `suspended` mid-request (race condition), `get_current_tenant_obj` raises 403 immediately (INV-MT-05)

### 9.4 Data migration & backfill (US-16 .. US-20)

**US-16: Migration adds tenant_id to a live table without downtime**
- **As a** DBA applying the multi-tenancy migration to a production database with 5M rows in `items`
- **I want** the migration to add `tenant_id` as nullable first, backfill, then promote to NOT NULL
- **So that** the table is never locked longer than 1 second and the app stays online during migration
- **Given:** Production DB with `items` table (5M rows), no `tenant_id` column
- **When:** `alembic upgrade head` runs
- **Then:**
  - `ALTER TABLE items ADD COLUMN tenant_id UUID NULL` completes instantly (no table lock) (CC-09)
  - Backfill `UPDATE items SET tenant_id = (SELECT id FROM tenants WHERE slug='default')` runs in batches for tables > 1M rows (CC-30)
  - `ALTER TABLE items ALTER COLUMN tenant_id SET NOT NULL` completes after all rows are backfilled (INV-MT-02)
  - The composite index `ix_items_tenant_created` is created concurrently (`CREATE INDEX CONCURRENTLY`) (CC-04)

**US-17: Backfill assigns all existing rows to the configurable default tenant**
- **As a** developer migrating a single-tenant app to multi-tenant
- **I want** all existing rows to be assigned to `default_tenant_slug` during migration
- **So that** the app continues to work for the existing customer after the migration runs
- **Given:** `items` table has 1000 rows, `default_tenant_slug="legacy-customer"` passed to tool
- **When:** `alembic upgrade head` runs
- **Then:**
  - A `Tenant` row with `slug="legacy-customer"` is inserted at the start of `upgrade()` (CC-12)
  - All 1000 rows have `tenant_id = legacy-customer.id` after backfill (CC-09, T-17)
  - Zero rows have `tenant_id IS NULL` after migration (INV-MT-02)
  - `GET /items/` with `X-Tenant-ID: legacy-customer` returns all 1000 items

**US-18: Migration downgrade reverses all changes and preserves business data**
- **As a** developer who needs to roll back the multi-tenancy migration after discovering a bug
- **I want** `alembic downgrade -1` to drop all tenant-related columns and tables without touching business rows
- **So that** the app returns to its pre-tenancy state and existing data is intact
- **Given:** Multi-tenancy migration applied; `items` table has 1000 rows with `tenant_id` populated
- **When:** `alembic downgrade -1` runs
- **Then:**
  - Composite indexes `ix_*_tenant_created` are dropped first (CC-10)
  - FK constraints `fk_*_tenant` are dropped before the column (CC-10)
  - `tenant_id` column is dropped from all business tables; rows remain intact (CC-10, T-18)
  - `tenants` table is dropped last; no orphan FK references remain
  - `alembic upgrade head` after downgrade produces the same state as the first apply (idempotent migration)

**US-19: Tool is idempotent when multi-tenancy is already enabled**
- **As a** CI pipeline that runs `add_multi_tenancy` on every build to ensure schema compliance
- **I want** re-running the tool on a project that already has tenancy enabled to be a safe no-op
- **So that** accidental double-runs do not create duplicate columns, duplicate migrations, or duplicate middleware registrations
- **Given:** `Item` already inherits `TenantScopedMixin`; migration `0008_add_multi_tenancy.py` already exists
- **When:** `add_multi_tenancy(project_dir, models=["Item"])` is called again
- **Then:**
  - Tool returns `notes: ["Item already has TenantScopedMixin, skipped", "Migration already exists, skipped"]` (CC-26, T-26)
  - No files are modified; `git diff` is empty
  - No duplicate Alembic migration is created; `alembic history` shows one entry for tenancy
  - Exit code is 0 (INV-MT-07)

**US-20: Adding tenancy to a new model on an already-tenanted project**
- **As a** developer who added an `Invoice` model three sprints after the initial tenancy rollout
- **I want** to call `add_multi_tenancy(models=["Invoice"])` to scope only the new model
- **So that** existing `Item` and `Order` models are not touched and their tests remain green
- **Given:** `items` and `orders` are already tenant-scoped; new `Invoice` model has no `tenant_id`
- **When:** `add_multi_tenancy(project_dir, models=["Invoice"])` is called
- **Then:**
  - `Invoice` inherits `TenantScopedMixin` and a new incremental migration is generated (CC-03, CC-09)
  - `Item` and `Order` models are not modified — the tool's idempotency guard skips them (CC-26)
  - The new migration's `down_revision` points to the existing tenancy migration (CC-10)
  - `pytest tests/test_item_crud.py tests/test_order_crud.py` passes with 0 failures (CC-19)

### 9.5 Observability & edge cases (US-21 .. US-25)

**US-21: Every log line for a request carries the tenant_id for incident correlation**
- **As an** ops engineer investigating a production error report from tenant `acme`
- **I want** `tenant_id` to appear as a structured log field on every log line within a request
- **So that** I can filter Datadog logs by `tenant_id=acme` and see the full request trace without ambiguity
- **Given:** `TenantMiddleware` has resolved `acme` and set `_current_tenant_id`; a Python `logging.Filter` reads the contextvar
- **When:** Any log statement (INFO, WARNING, ERROR) is emitted inside the request lifecycle
- **Then:**
  - Log record contains `{"tenant_id": "<acme-uuid>", "level": "ERROR", "message": "..."}` (INV-MT-01 observability)
  - Background jobs that call `set_current_tenant(tid)` emit logs with the correct `tenant_id`
  - Requests on `TENANT_FREE_PATHS` (e.g. `/health`) emit `{"tenant_id": null}` — not an error (CC-17)
  - A cross-tenant attempt blocked by middleware emits a WARNING log with both the requested slug and the authenticated tenant's ID

**US-22: Cross-tenant access attempt triggers an audit log event**
- **As a** security auditor reviewing the platform's intrusion detection posture
- **I want** every blocked cross-tenant request to generate an audit record regardless of where it was blocked
- **So that** a security incident (e.g. a compromised API key probing other tenants) is detectable in the audit trail
- **Given:** Tenant B's API key sends `GET /items/aa-1` where `aa-1` belongs to Tenant A; middleware resolves tenant B correctly
- **When:** The ORM filter returns empty and the route returns 404
- **Then:**
  - An `AUDIT` event is written: `{event: "CROSS_TENANT_ATTEMPT", tenant_id: "tenant-b", resource: "items", resource_id: "aa-1", result: "404"}` (INV-MT-01)
  - The audit record is written via the `add_audit_log` integration even though no row was returned (T-03, T-04)
  - The attempt does not raise an exception in the application — it is silent to the caller but loud in the audit log
  - Repeated cross-tenant attempts from the same API key within 60s trigger a rate-limit warning (QS-11)

**US-23: Per-tenant query metrics are visible in the observability dashboard**
- **As an** ops engineer monitoring query performance across tenants
- **I want** Prometheus metrics labeled `{tenant_slug}` for query count and latency
- **So that** I can identify which tenants generate the highest DB load and apply per-tenant throttling
- **Given:** Multi-tenancy enabled; Prometheus metrics middleware active; Tenant `power-user` issues 1000 requests/min
- **When:** I query `http_requests_total{tenant_slug="power-user"}` in Prometheus
- **Then:**
  - Metric exists and increments per request resolved to `power-user` (INV-MT-01 observability)
  - Tenant label is derived from the contextvar after middleware resolution — zero additional DB queries (CC-23)
  - The `TENANT_FREE_PATHS` requests are labeled `tenant_slug="system"` to avoid `None` cardinality issues (CC-17)
  - p99 latency overhead from tenant label injection is < 0.1ms (CC-23)

**US-24: Tool fails atomically when a model file has a syntax error**
- **As a** developer who accidentally introduced a syntax error in `app/models/order.py` before running the tool
- **I want** the tool to detect the syntax error during `ast.parse` validation and exit cleanly without partially modifying files
- **So that** I am not left with a broken half-tenanted codebase that requires manual cleanup
- **Given:** `app/models/order.py` contains an `IndentationError`; `app/models/item.py` is valid
- **When:** `add_multi_tenancy(project_dir, models=["Item", "Order"])` is called
- **Then:**
  - Tool raises a descriptive error: `"Syntax error in app/models/order.py:42: unexpected indent"` (CC-21)
  - `app/models/item.py` is NOT modified — the tool aborted before writing any file (T-28)
  - No partial migration file exists in `alembic/versions/`
  - `git status` shows zero modified files — the atomic transaction guarantee holds (QS-3)

**US-25: Tenant resolution adds < 1ms overhead at p99 on warm cache**
- **As a** backend developer evaluating whether multi-tenancy impacts SLA-critical endpoints
- **I want** tenant resolution to be cached in memory so repeated requests for the same tenant slug hit no DB
- **So that** a high-throughput tenant issuing 500 req/s does not generate 500 extra `SELECT FROM tenants` queries per second
- **Given:** Tenant `high-traffic` is already in the LRU cache (capacity 10k tenants, TTL 60s); 1000 concurrent requests for `high-traffic`
- **When:** All 1000 requests arrive with `X-Tenant-ID: high-traffic`
- **Then:**
  - Zero additional `SELECT FROM tenants WHERE slug='high-traffic'` queries are issued — cache hit (CC-23, T-29)
  - Median resolution latency is < 0.1ms; p99 is < 1ms (CC-23)
  - Cache is bounded to 10k entries via LRU eviction — no unbounded memory growth (QS-4)
  - A cache miss (cold start or TTL expiry) issues exactly one DB query and repopulates the cache (INV-MT-03)

## 10. Test Plan

### 10.1 Cross-tenant safety tests (the most important category)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Cross-tenant list returns empty | Tenant A has 3 items, B has 0 | GET /items/ as B | data=[], count=0 |
| T-02 | Cross-tenant list returns own only | A=3, B=2 | GET /items/ as A | data has 3, count=3 |
| T-03 | Cross-tenant GET by id returns 404 | item belongs to A | GET /items/{id} as B | 404 |
| T-04 | Cross-tenant PATCH returns 404 | item belongs to A | PATCH /items/{id} as B | 404, row unchanged |
| T-05 | Cross-tenant DELETE returns 404 | item belongs to A | DELETE /items/{id} as B | 404, row unchanged |
| T-06 | Cross-tenant by id when ids collide | Two items with same UUID across tenants (impossible by PK, but verify) | Force INSERT with conflict | PK violation |
| T-07 | CREATE without tenant context raises | No middleware, call crud.create directly | flush() | TenantContextMissing |

### 10.2 Tenant resolution tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-08 | Resolve from header | resolver=header | GET / with X-Tenant-ID=acme | 200 |
| T-09 | Resolve from subdomain | resolver=subdomain | GET / Host: acme.example.com | 200 |
| T-10 | Resolve from JWT | resolver=jwt | JWT with tenant_slug=acme | 200 |
| T-11 | Missing tenant header → 400 | resolver=header, no header | GET /items/ | 400 |
| T-12 | Unknown tenant slug → 404 | header X-Tenant-ID=ghost | GET /items/ | 404 |
| T-13 | tenant_id NOT NULL constraint | Try INSERT with NULL tenant_id | psql | NotNullViolation |
| T-14 | Suspended tenant → 403 | Tenant B status='suspended' | GET /items/ as B | 403 |
| T-15 | DELETE tenant with rows fails | Tenant A has 1 item | DELETE FROM tenants WHERE id=A | RESTRICT FK violation |

### 10.3 Migration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-16 | Upgrade creates tenants table | Fresh DB | alembic upgrade head | `\d tenants` shows table |
| T-17 | Upgrade adds tenant_id NOT NULL | 100 existing rows | alembic upgrade head | All 100 have tenant_id=default |
| T-18 | Downgrade reverses cleanly | After upgrade | alembic downgrade -1 | tenant_id columns dropped, business data intact |
| T-19 | Concurrent requests isolated | 100 concurrent reqs alternating tenants A/B | run async stress | each request sees only its tenant's data, no leaks |
| T-20 | Migration on 10M rows < 60s | Seed 10M items | alembic upgrade head | < 60s |

### 10.4 Functional & API tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-21 | CREATE stamps current tenant | Auth as A | POST /items/ {title:"x"} | tenant_id=A.id |
| T-22 | skip_tenant_filter=True returns all | System query | crud.get_multi(execution_options={"skip_tenant_filter":True}) | All tenants |
| T-23 | tenant_id excluded from response schema | Item with tenant_id | GET /items/{id} | response body has no tenant_id key |
| T-24 | tenant_id in request body is ignored | POST /items/ {tenant_id:"<other>"} | Inspect inserted row | tenant_id = current, not the forged one |
| T-25 | Tenant CRUD admin endpoints work | superadmin token | POST /tenants/, GET /tenants/, PATCH /tenants/{slug} | 200 |

### 10.5 Idempotency, integration & performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-26 | Tool re-run is no-op | tenancy already enabled | run tool again | no file changes, notes "skipped" |
| T-27 | Tool warns when User is in models param | models=["User"] | run tool | warning emitted, User skipped unless --include-user |
| T-28 | Tool fails atomically on partial error | mock fs error | run tool | NO partial state |
| T-29 | Resolution overhead < 1 ms | benchmark middleware | measure | < 1 ms p99 |
| T-30 | Filter overhead < 5% vs no-tenancy | benchmark queries | compare | < 5% |

---

## 11. Interaction Matrix

How `add_multi_tenancy` interacts with other tools:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_soft_delete` | **Tenancy first** | ✅ Compatible | Listener adds BOTH `tenant_id = ?` AND `is_deleted = false`. Composite index `(tenant_id, is_deleted, created_at)` recommended. |
| `add_cursor_pagination` | **Tenancy first** | ✅ Compatible | Cursor query gains tenant filter automatically via the listener. |
| `add_search` | **Tenancy first** | ✅ Compatible | tsvector queries get the tenant filter through the same listener. |
| `add_audit_log` | **Audit first** | ✅ Compatible | Audit entries automatically tagged with tenant_id from contextvar. |
| `add_bulk_operations` | **Tenancy first** | ✅ Compatible | Bulk pre-flight verifies all rows belong to current tenant; cross-tenant ids return 404. |
| `add_data_export` | **Tenancy first** | ✅ Compatible | Export filtered to current tenant; admin export uses `skip_tenant_filter=True`. |
| `add_file_upload` | **Tenancy first** | ⚠️ Caveat | Storage paths must include tenant_id prefix (e.g. `s3://bucket/{tenant_id}/{file_id}`) to enforce isolation at storage layer. |
| `add_rbac` | **RBAC first** | ✅ Compatible | Roles scoped to tenant; superadmin can bypass via `skip_tenant_filter`. |
| `add_feature_flags` | No | ✅ Compatible | Flags can be tenant-scoped (per-tenant rollout). |
| `add_api_key_auth` | **Auth first** | ✅ Compatible | API key carries tenant_id; middleware reads it from key metadata. |
| `add_oauth2_provider` | **Auth first** | ✅ Compatible | OAuth user is associated with a tenant at signup. |
| `add_mfa` | No | ✅ Compatible | MFA enrollment is tenant-scoped (each tenant has its own users). |
| `add_cache_layer` | **Tenancy first** | ⚠️ Caveat | Cache keys MUST include tenant_id to prevent cross-tenant cache poisoning. |
| `add_circuit_breaker` | No | ✅ Compatible | Circuit state is per-process, not tenant-scoped. |
| `add_outbox_pattern` | **Tenancy first** | ✅ Compatible | Outbox table is tenant-scoped via the same mixin. |

**Conflicts:**
- None identified. Multi-tenancy is a foundational pattern that other tools must respect.

---

## 12. Rollback Procedure

If `add_multi_tenancy` produces broken state, the rollback procedure is:

### Code rollback (before deploy)
```bash
git diff HEAD~1 -- app/models app/crud app/api app/core
git checkout HEAD~1 -- app/models app/crud app/api app/core
rm alembic/versions/*_add_multi_tenancy.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
This drops all `tenant_id` columns, the `tenants` table, the foreign keys, and the composite indexes. Business rows are preserved (only the `tenant_id` column is dropped).

### Data preservation rollback
If the migration must be reversed but the tenant assignment must be preserved for a future re-enable:
```sql
-- Before downgrade, archive the tenant assignments
CREATE TABLE _tenant_assignments AS
  SELECT 'items' AS table_name, id, tenant_id FROM items
  UNION ALL SELECT 'orders', id, tenant_id FROM orders
  UNION ALL SELECT 'products', id, tenant_id FROM products;

CREATE TABLE _tenants_archive AS SELECT * FROM tenants;
-- Then run alembic downgrade -1
```

### Failure mode: tool partially modified files
The tool MUST be atomic (§15.9). If atomicity fails:
1. Identify modified files via `git status`
2. `git checkout -- {files}` to revert
3. Delete partial migration: `rm alembic/versions/*_add_multi_tenancy.py`
4. Drop the partially-created `tenants` table if it exists
5. Re-run tool with corrected input

### Emergency: cross-tenant leak detected in production
If a production query is found returning cross-tenant data:
1. **Stop traffic immediately** (set worker count = 0 or block at load balancer)
2. Verify the listener is registered: grep `do_orm_execute` in source
3. Verify the middleware is in the stack: grep `TenantMiddleware` in `main.py`
4. If listener missing → patch and redeploy
5. If middleware missing → patch and redeploy
6. After fix, audit all logs for the time window of the leak; notify affected tenants per your DPA

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no User model | Tool errors: "Multi-tenancy requires an authenticated user model. Add auth first." |
| EC-2 | Project has no Alembic | Tool errors: "Alembic not initialized. Run alembic init first." |
| EC-3 | A model already inherits from `TenantScopedMixin` | Idempotent skip with note; the operation returns a structured error response and no side effects persist |
| EC-4 | A model already has a `tenant_id` column with a different type | Tool errors: "Type mismatch on Item.tenant_id (expected UUID). Resolve manually." |
| EC-5 | Two instances of the tool run concurrently | First wins (atomic file write); second detects existing state and skips |
| EC-6 | Migration fails midway during 10M-row backfill | Rolled back via transaction; manual cleanup of `tenants` row not needed since it's inside the same TX |
| EC-7 | User cancels mid-execution (SIGINT) | Atomic: no partial files. Either all changes or none. |
| EC-8 | Resolver=subdomain but app sits behind a proxy that strips Host | Middleware reads `X-Forwarded-Host` if available; otherwise returns 400 |
| EC-9 | Resolver=jwt but auth middleware runs after tenant middleware | Tool emits a warning during install: "JWT resolver requires auth middleware to run BEFORE TenantMiddleware. Reordering automatically." |
| EC-10 | Background worker queries without `set_current_tenant` | Listener returns no rows (filter is `tenant_id = NULL` which matches nothing). CREATE raises `TenantContextMissing`. |
| EC-11 | Schema-per-tenant strategy requested | Tool emits a warning: "schema_per_tenant requires manual schema creation per tenant; tool generates schema_creator helper at app/core/tenant_schema.py. Review before deploy." |
| EC-12 | DB-per-tenant strategy requested | Tool errors: "db_per_tenant requires multi-database setup outside the scope of this generator. Documentation provided in next_steps." |
| EC-13 | Default tenant slug already exists | Idempotent: tool skips INSERT, uses existing default tenant for backfill |
| EC-14 | A unique constraint exists on a column that is now expected to be unique per-tenant (e.g. items.title UNIQUE) | Tool warns: "items.title is globally unique; consider changing to UNIQUE(tenant_id, title) to allow per-tenant uniqueness." NO automatic change. |
| EC-15 | The `User` model is passed in `models` without `--include-user` | Tool warns and skips User with note: "User excluded by default; pass --include-user to override. Note: making User tenant-scoped breaks superadmin login." |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 30 CC verified by automated check
2. ✅ All 25 user stories have passing acceptance tests
3. ✅ All 30 test cases pass
4. ✅ All 8 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified by integration tests
7. ✅ Rollback procedure tested end-to-end
8. ✅ Performance SLOs measured and met
9. ✅ Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10
10. ✅ One human dev uses it on a real SaaS project without confusion or cross-tenant incidents

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate `alembic/versions/` exists
- [ ] Validate User model exists (auth installed)
- [ ] Parse target model files with AST
- [ ] Detect existing `tenant_id` columns (idempotency check)
- [ ] If exists with wrong type → error
- [ ] If exists with correct type → mark as already-tenant-scoped, return early per model
- [ ] Check for `created_at` on each target → required for composite index
- [ ] If `User` is in `models` → warn and skip unless `include_user=True`

### 15.2 Tenant model + mixin generation
- [ ] Create `app/models/tenant.py` with `Tenant` class
- [ ] Create `app/models/mixins.py` (or append) with `TenantScopedMixin`
- [ ] Both files parse with `ast.parse`
- [ ] Write atomically
- [ ] Verify `TenantScopedMixin` adds a `tenant_id: Mapped[UUID]` column with FK to `tenants.id` by inspecting `TenantScopedMixin.__table_args__` in `tests/test_tenant_model.py::test_mixin_fk_defined`
- [ ] Run `ruff check app/models/tenant.py app/models/mixins.py` and `mypy app/models/tenant.py --strict` with zero findings
- [ ] Confirm `Tenant.slug` has a `UniqueConstraint` via `sqlalchemy.inspect` in `tests/test_tenant_model.py::test_slug_unique_constraint`

### 15.3 Tenant context module
- [ ] Create `app/core/tenant_context.py`
- [ ] Define `_current_tenant_id: ContextVar[UUID | None]`
- [ ] Export `set_current_tenant`, `get_current_tenant`, `require_current_tenant`
- [ ] Verify file parses
- [ ] Confirm `require_current_tenant()` raises `HTTPException(403)` (not `None`) when no tenant is set in `tests/test_tenant_context.py::test_require_raises_when_unset`
- [ ] Verify ContextVar isolation across concurrent tasks: run two `asyncio.Task`s with different tenant IDs and assert each sees only its own value in `tests/test_tenant_context.py::test_context_var_task_isolation`
- [ ] Run `ruff check app/core/tenant_context.py` and `mypy app/core/tenant_context.py --strict` with zero findings

### 15.4 Listener installation
- [ ] Create `app/core/tenant_filter.py`
- [ ] Register `do_orm_execute` listener on `Session`
- [ ] Use `with_loader_criteria(TenantScopedMixin, lambda cls: cls.tenant_id == tenant_id)`
- [ ] Honor `skip_tenant_filter=True` execution option
- [ ] Import from app initialization (`app/main.py` startup)
- [ ] Run `tests/test_multi_tenancy.py::test_tenant_b_cannot_read_tenant_a_orders` without the listener active and confirm the test fails (proving the guard is necessary), then re-enable and confirm it passes
- [ ] Verify `skip_tenant_filter=True` execution option bypasses the listener and returns rows from all tenants in `tests/test_tenant_filter.py::test_skip_flag_bypasses_filter`

### 15.5 Middleware
- [ ] Create `app/api/middleware/tenant.py`
- [ ] Implement `TenantMiddleware` with configurable resolver
- [ ] Define `TENANT_FREE_PATHS`
- [ ] Register middleware in `app/main.py` AFTER auth middleware
- [ ] Add `TENANT_RESOLVER` to `app/core/config.py` settings
- [ ] Confirm that requests to paths in `TENANT_FREE_PATHS` (e.g. `/health`, `/docs`) pass through without 403 when no `X-Tenant-ID` header is set in `tests/test_tenant_middleware.py::test_free_paths_bypass_tenant_check`
- [ ] Confirm middleware calls `set_current_tenant` with the resolved UUID so that the ORM listener picks it up; verify with a spy on `tenant_context.set_current_tenant` in `tests/test_tenant_middleware.py::test_middleware_sets_context`

### 15.6 Model modification
For each target model:
- [ ] Read `app/models/{name}.py`
- [ ] Add `from app.models.mixins import TenantScopedMixin`
- [ ] Modify `class X(Base):` → `class X(TenantScopedMixin, Base):`
- [ ] Add `Index("ix_{table}_tenant_created", "tenant_id", "created_at")` to `__table_args__`
- [ ] Verify file parses
- [ ] Write atomically
- [ ] Confirm `ix_{table}_tenant_created` index exists after `alembic upgrade head` by querying `pg_indexes` where `indexname = 'ix_{table}_tenant_created'`

### 15.7 CRUD modification
For each target model:
- [ ] Read `app/crud/{name}.py`
- [ ] Add `from app.core.tenant_context import require_current_tenant`
- [ ] Modify `create()` to call `require_current_tenant()` and pass `tenant_id`
- [ ] No other CRUD function needs explicit changes (listener handles filtering)
- [ ] Verify file parses
- [ ] Write atomically
- [ ] Confirm that `crud_{model}.create()` raises `HTTPException(403)` when called without a tenant context set (no header), via `tests/test_multi_tenancy.py::test_create_without_tenant_raises_403`

### 15.8 Tenant CRUD endpoints
- [ ] Create `app/crud/tenant.py` with `create_tenant`, `get_by_slug`, `update_tenant`
- [ ] Create `app/api/routes/tenants.py` with admin-only endpoints
- [ ] Add tenant routes to `app/api/main.py` router
- [ ] Schemas: `TenantCreate`, `TenantUpdate`, `TenantPublic` in `app/schemas/tenant.py`
- [ ] All endpoints require `CurrentSuperuser`
- [ ] Verify all files parse
- [ ] Run `tests/test_multi_tenancy.py::test_non_superuser_cannot_create_tenant` and confirm HTTP 403 is returned when a regular user calls `POST /tenants/`

### 15.9 Migration generation
- [ ] Compute next revision number
- [ ] Generate `0NNN_add_multi_tenancy.py`
- [ ] `upgrade()`:
  1. Create `tenants` table
  2. Insert default tenant with configured slug
  3. For each target table: add `tenant_id` nullable
  4. Backfill each table with default tenant id (batched if > 1M rows)
  5. Promote `tenant_id` to NOT NULL
  6. Add FK with ON DELETE RESTRICT
  7. Add composite index `(tenant_id, created_at)`
- [ ] `downgrade()` reverses in correct order
- [ ] Migration parses
- [ ] Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a clean Postgres container and assert each step exits with code 0
- [ ] Verify backfill step: seed 100 rows with no `tenant_id`, run `upgrade()`, then `SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL` must return 0

### 15.10 Test generation
- [ ] Create `tests/test_multi_tenancy.py`
- [ ] Generate all 30 test cases (T-01..T-30)
- [ ] Use existing fixtures + new `tenant_a_token`, `tenant_b_token` fixtures
- [ ] Verify file parses
- [ ] Run `pytest tests/test_multi_tenancy.py -v` and confirm all 30 cases pass including `test_tenant_b_cannot_read_tenant_a_orders`
- [ ] Run `ruff check tests/test_multi_tenancy.py` and `mypy tests/test_multi_tenancy.py` with zero new findings
- [ ] Confirm `tenant_a_token` and `tenant_b_token` fixtures are defined in `tests/conftest.py` or `tests/test_multi_tenancy.py` (no missing fixture error)

### 15.11 Documentation updates
- [ ] Append multi-tenancy section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Confirm `manifest.yaml` contains `fastapi_add_multi_tenancy` entry: `python -c "import yaml; d=yaml.safe_load(open('manifest.yaml')); assert any(t['name']=='fastapi_add_multi_tenancy' for t in d['tools'])"`
- [ ] Verify `core/KNOWLEDGE.md` multi-tenancy section documents `TenantMiddleware`, the `do_orm_execute` listener, and the `skip_tenant_filter` escape hatch
- [ ] Run `ruff check app/api/middleware/tenant.py app/core/tenant_filter.py app/core/tenant_context.py` with zero findings

### 15.12 Atomicity
- [ ] All file writes use temp-file + rename pattern
- [ ] If ANY step fails, rollback ALL previous writes (track touched files)
- [ ] Drop partially-created `tenants` row if Insert succeeded but later step failed
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Inject a failure after `app/models/tenant.py` is written but before model modification and assert `app/models/tenant.py` is removed from the filesystem (rollback) in `tests/test_tool_atomicity.py::test_multi_tenancy_rollback_on_model_write`
- [ ] Run `ruff check app/crud/tenant.py app/api/routes/tenants.py app/schemas/tenant.py` with zero findings after any rollback recovery
- [ ] Verify the returned error dict contains `files_rolled_back` listing every file removed during rollback

### 15.13 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure tool execution time
- [ ] Measure tenant resolution overhead (synthetic benchmark)
- [ ] Return success report with metrics

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/tenant.py",
    "app/models/mixins.py",
    "app/core/tenant_context.py",
    "app/core/tenant_filter.py",
    "app/api/middleware/tenant.py",
    "app/crud/tenant.py",
    "app/api/routes/tenants.py",
    "app/schemas/tenant.py",
    "alembic/versions/0008_add_multi_tenancy.py",
    "tests/test_multi_tenancy.py"
  ],
  "files_modified": [
    "app/models/item.py",
    "app/models/order.py",
    "app/models/product.py",
    "app/crud/item.py",
    "app/crud/order.py",
    "app/crud/product.py",
    "app/main.py",
    "app/core/config.py",
    "app/api/main.py"
  ],
  "metrics": {
    "execution_time_ms": 4231,
    "files_changed": 19,
    "lines_added": 612,
    "lines_removed": 24,
    "models_made_tenant_scoped": 3,
    "default_tenant_slug": "default"
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_multi_tenancy.py -v",
    "Create your first real tenant: POST /tenants/ {slug: 'acme', name: 'Acme Inc'}",
    "Test cross-tenant isolation: try to GET an item from tenant A while authenticated as tenant B (must return 404)",
    "Wire up the tenant-scoped metrics exporter and confirm Prometheus scrapes the new labels for every tenant"
  ],
  "warnings": [
    "User model was NOT made tenant-scoped (default behavior). Pass include_user=True to override; doing so requires manual handling of superadmin login.",
    "items.title has a global UNIQUE constraint. Consider changing to UNIQUE(tenant_id, title) to allow per-tenant uniqueness.",
    "If add_file_upload is installed, file paths in storage MUST include tenant_id prefix to enforce isolation at storage layer."
  ],
  "notes": [
    "Multi-tenancy enabled with strategy=shared_db, resolver=header.",
    "3 models made tenant-scoped: Item, Order, Product.",
    "TenantMiddleware registered AFTER auth middleware in main.py.",
    "Default tenant 'default' created and used to backfill 0 existing rows.",
    "Listener do_orm_execute installed; cross-tenant queries are now blocked at the ORM layer.",
    "Existing tests still pass: 47/47."
  ]
}
```
