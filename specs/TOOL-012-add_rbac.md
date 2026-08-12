---
spec_id: "TOOL-012"
tool_name: "add_rbac"
primitive: "auth/RequestGuard"
primitive_path: "core.venous.auth.RequestGuard"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-RB-01"
  - "INV-RB-02"
  - "INV-RB-03"
  - "INV-RB-04"
  - "INV-RB-05"
  - "INV-RB-06"
  - "INV-RB-07"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-012: add_rbac

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_rbac` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User), Alembic, optional multi-tenancy |
| Signature | `add_rbac(project_dir: str, default_roles: list[str] | None = None, with_admin_ui: bool = True, cache_ttl_seconds: int = 300) -> dict` |
| Parameters | `project_dir`: project root path<br>`default_roles`: roles auto-created on install (default `["viewer","editor","admin"]`)<br>`with_admin_ui`: also generate admin endpoints<br>`cache_ttl_seconds`: per-user effective-permission cache TTL |

---

## 2. Purpose

Add production-grade role-based access control (RBAC) with first-class permissions, roles, role-permission bindings, and user-role bindings so routes can be gated by a single FastAPI dependency rather than hand-rolled `if user.is_admin` checks scattered across handlers. Permissions use the canonical `resource:action` format (e.g. `items:read`, `items:write`, `orders:refund`, `*:*` for superadmin) and roles support inheritance so operational hierarchies (`admin → editor → viewer`) collapse into a single DAG evaluated once per user.

Route protection is a one-liner: `Depends(require_permission("items:write"))`. Effective permissions per user are computed once (resolving role inheritance, merging direct grants, applying tenant scoping) and cached in-process with a TTL plus a Redis pub/sub invalidation channel so multi-worker deployments stay consistent. When TOOL-008 multi-tenancy is installed every role binding is automatically tenant-scoped — Tenant A's admins cannot act on Tenant B's resources even if the same user exists in both. All role, permission, and binding mutations are written to an audit trail via TOOL-005 so compliance auditors can trace exactly who granted which privilege to whom and when. Design decisions: deny-by-default for missing permissions, deterministic evaluation order, atomic cache invalidation, and strict separation between "who you are" (identity) and "what you can do" (authorization).

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Dev waits in CLI |
| Files modified | ≤ 5 global files | Predictability |
| Files created | ≥ 10 (3 models, 1 evaluator, 1 cache, 1 deps, 1 crud, 2 schemas, routes, migration, tests) | Predictability |
| Permission check latency p99 | < 0.5 ms (cached) / < 5 ms (cold) | Cached set lookup is O(1) |
| Effective-permission compute | < 20 ms for user with 10 roles | Recursive role inheritance + dedupe |
| Cache invalidation propagation | < 1s across workers | Redis pubsub on role/binding change |
| Migration runtime | < 10s on existing DB | 4 new tables + seed defaults |
| Memory overhead | < 5 MB per worker | LRU cache bounded to 10k user permission sets |

---

## 4. Code Examples (Before / After)

### 4.1 Models (NEW)
```python
# app/models/rbac.py
from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            r"code ~ '^([a-z][a-z0-9_-]{0,62}|\*):([a-z][a-z0-9_-]{0,62}|\*)$'",
            name="ck_permissions_code_format",
        ),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    parent: Mapped["Role | None"] = relationship(remote_side="Role.id")
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "name ~ '^[a-z][a-z0-9_-]{0,62}$'",
            name="ck_roles_name_format",
        ),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[Role] = relationship(back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_roles"),
    )
```

### 4.2 Evaluator (NEW)
```python
# app/core/rbac/evaluator.py
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.rbac import Permission, Role, RolePermission, UserRole


async def compute_effective_permissions(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID | None = None,
) -> set[str]:
    """
    Returns the set of permission codes (e.g. {"items:read","items:write"})
    that the user has, considering role inheritance and tenant scope.
    """
    stmt = (
        select(UserRole)
        .where(UserRole.user_id == user_id)
        .options(selectinload(UserRole.role))
    )
    if tenant_id is not None:
        stmt = stmt.where((UserRole.tenant_id == tenant_id) | (UserRole.tenant_id.is_(None)))

    user_roles = (await session.execute(stmt)).scalars().all()
    if not user_roles:
        return set()

    # Walk role inheritance chain (BFS), collect role IDs
    role_ids: set[UUID] = set()
    queue = [ur.role_id for ur in user_roles]
    while queue:
        rid = queue.pop()
        if rid in role_ids:
            continue
        role_ids.add(rid)
        role = (await session.execute(select(Role).where(Role.id == rid))).scalar_one_or_none()
        if role and role.parent_id:
            queue.append(role.parent_id)

    if not role_ids:
        return set()

    # Fetch all permissions for those roles
    stmt2 = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id.in_(role_ids))
    )
    rows = (await session.execute(stmt2)).scalars().all()
    return set(rows)


def has_permission(effective: set[str], required: str) -> bool:
    """
    Wildcard-aware check. `required` is `resource:action` (no wildcards).
    `effective` may contain `*:*`, `resource:*`, `*:action`, or exact match.
    """
    if required in effective:
        return True
    if "*:*" in effective:
        return True
    resource, action = required.split(":", 1)
    if f"{resource}:*" in effective:
        return True
    if f"*:{action}" in effective:
        return True
    return False
```

### 4.3 Cache (NEW)
```python
# app/core/rbac/cache.py
import asyncio
import json
import time
from collections import OrderedDict
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings

TTL = settings.RBAC_CACHE_TTL
MAX_SIZE = 10_000
CHANNEL = "rbac:invalidate"


class PermCache:
    def __init__(self) -> None:
        self._store: OrderedDict[tuple[UUID, UUID | None], tuple[float, set[str]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def get(self, user_id: UUID, tenant_id: UUID | None) -> set[str] | None:
        async with self._lock:
            entry = self._store.get((user_id, tenant_id))
            if entry is None:
                return None
            ts, perms = entry
            if time.monotonic() - ts > TTL:
                del self._store[(user_id, tenant_id)]
                return None
            self._store.move_to_end((user_id, tenant_id))
            return set(perms)

    async def set(self, user_id: UUID, tenant_id: UUID | None, perms: set[str]) -> None:
        async with self._lock:
            self._store[(user_id, tenant_id)] = (time.monotonic(), set(perms))
            self._store.move_to_end((user_id, tenant_id))
            while len(self._store) > MAX_SIZE:
                self._store.popitem(last=False)

    async def invalidate_user(self, user_id: UUID) -> None:
        async with self._lock:
            for k in list(self._store):
                if k[0] == user_id:
                    del self._store[k]

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def listen(self, redis: Redis) -> None:
        async def _run():
            ps = redis.pubsub()
            await ps.subscribe(CHANNEL)
            async for msg in ps.listen():
                if msg["type"] != "message":
                    continue
                payload = json.loads(msg["data"])
                if payload.get("user_id") == "*":
                    await self.clear()
                else:
                    await self.invalidate_user(UUID(payload["user_id"]))

        self._task = asyncio.create_task(_run())


_cache: PermCache | None = None


def get_perm_cache() -> PermCache:
    global _cache
    if _cache is None:
        _cache = PermCache()
    return _cache


async def publish_user_invalidation(redis: Redis, user_id: UUID | str) -> None:
    await redis.publish(CHANNEL, json.dumps({"user_id": str(user_id)}))
```

### 4.4 Dependency (NEW)
```python
# app/core/rbac/deps.py
from fastapi import Depends, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.core.rbac.cache import get_perm_cache
from app.core.rbac.evaluator import compute_effective_permissions, has_permission
from app.core.tenant_context import get_current_tenant


async def get_effective_permissions(
    current_user: CurrentUser,
    session: SessionDep,
) -> set[str]:
    tenant_id = get_current_tenant()  # None if multi-tenancy not installed
    cache = get_perm_cache()
    cached = await cache.get(current_user.id, tenant_id)
    if cached is not None:
        return cached
    perms = await compute_effective_permissions(session, current_user.id, tenant_id)
    await cache.set(current_user.id, tenant_id, perms)
    return perms


def require_permission(code: str):
    """
    FastAPI dependency that 403s if the current user does not have `code`.

    Usage:
        @router.post("/items/", dependencies=[Depends(require_permission("items:write"))])
    """

    async def dep(perms: set[str] = Depends(get_effective_permissions)) -> None:
        if not has_permission(perms, code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )

    return dep
```

### 4.5 Migration (with seed)
```python
# alembic/versions/0012_add_rbac.py
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(127), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            r"code ~ '^([a-z][a-z0-9_-]{0,62}|\*):([a-z][a-z0-9_-]{0,62}|\*)$'",
            name="ck_permissions_code_format",
        ),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(63), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("name ~ '^[a-z][a-z0-9_-]{0,62}$'", name="ck_roles_name_format"),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Uuid(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_roles"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    # Seed default roles
    op.execute(
        "INSERT INTO roles (id, name, description, is_system) VALUES "
        "(gen_random_uuid(), 'viewer', 'Read-only access', true),"
        "(gen_random_uuid(), 'editor', 'Read and write access', true),"
        "(gen_random_uuid(), 'admin', 'Full access (inherits editor)', true);"
    )
    op.execute(
        "UPDATE roles SET parent_id = (SELECT id FROM roles WHERE name='editor') WHERE name='admin';"
    )
    op.execute(
        "INSERT INTO permissions (id, code, description) VALUES "
        "(gen_random_uuid(), '*:*', 'All permissions on all resources');"
    )
    op.execute(
        "INSERT INTO role_permissions (id, role_id, permission_id) VALUES "
        "(gen_random_uuid(), "
        " (SELECT id FROM roles WHERE name='admin'), "
        " (SELECT id FROM permissions WHERE code='*:*'));"
    )


def downgrade() -> None:
    op.drop_index("ix_user_roles_user_id", "user_roles")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_name", "roles")
    op.drop_table("roles")
    op.drop_index("ix_permissions_code", "permissions")
    op.drop_table("permissions")
```

### 4.6 Routes (NEW)
```python
# app/api/routes/rbac.py
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentSuperuser, SessionDep
from app.core.rbac.cache import publish_user_invalidation
from app.core.redis import get_redis
from app.crud import rbac as crud_rbac
from app.schemas.rbac import (
    PermissionCreate,
    PermissionPublic,
    RoleAssignment,
    RoleCreate,
    RolePublic,
)

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.post("/permissions", response_model=PermissionPublic, status_code=201)
async def create_permission(p_in: PermissionCreate, session: SessionDep, _: CurrentSuperuser):
    return await crud_rbac.create_permission(session, p_in=p_in)


@router.post("/roles", response_model=RolePublic, status_code=201)
async def create_role(r_in: RoleCreate, session: SessionDep, _: CurrentSuperuser):
    return await crud_rbac.create_role(session, r_in=r_in)


@router.post("/users/{user_id}/roles")
async def assign_role(
    user_id: str,
    binding: RoleAssignment,
    session: SessionDep,
    current_user: CurrentSuperuser,
):
    await crud_rbac.assign_user_role(
        session,
        user_id=user_id,
        role_id=binding.role_id,
        tenant_id=binding.tenant_id,
        granted_by=current_user.id,
    )
    redis = await get_redis()
    await publish_user_invalidation(redis, user_id)
    return {"status": "ok"}


@router.delete("/users/{user_id}/roles/{role_id}")
async def revoke_role(
    user_id: str,
    role_id: str,
    session: SessionDep,
    _: CurrentSuperuser,
):
    await crud_rbac.revoke_user_role(session, user_id=user_id, role_id=role_id)
    redis = await get_redis()
    await publish_user_invalidation(redis, user_id)
    return {"status": "ok"}
```

---

### 4.10 Role inheritance resolver
```python
# app/rbac/inheritance.py
"""Resolve effective permissions for a user by walking the role DAG.

Roles form a directed acyclic graph (DAG): `admin → editor → viewer`.
A user with role `admin` inherits every permission granted to `editor`
and `viewer`. The resolver walks the DAG once per user per request,
detects cycles as a safety net, and memoizes the result in the per-
request cache so a 40-route request only resolves once.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    name: str
    direct_permissions: frozenset[str]
    parent_role_names: frozenset[str] = field(default_factory=frozenset)


class CyclicRoleError(Exception):
    pass


def effective_permissions(
    role_name: str,
    registry: dict[str, Role],
    _visited: frozenset[str] | None = None,
) -> frozenset[str]:
    """Return the merged set of permissions for a role, walking inheritance."""
    if role_name not in registry:
        raise ValueError(f"unknown role: {role_name!r}")
    visited = _visited or frozenset()
    if role_name in visited:
        raise CyclicRoleError(f"cycle detected at role {role_name!r}")
    visited = visited | {role_name}
    role = registry[role_name]
    result: set[str] = set(role.direct_permissions)
    for parent in role.parent_role_names:
        result |= effective_permissions(parent, registry, visited)
    return frozenset(result)


def permission_allows(granted: str, required: str) -> bool:
    """Resource:action match with `*` wildcard on either segment."""
    g_r, _, g_a = granted.partition(":")
    r_r, _, r_a = required.partition(":")
    return (g_r in ("*", r_r)) and (g_a in ("*", r_a))
```

### 4.11 Permission cache with Redis invalidation
```python
# app/rbac/permission_cache.py
"""Per-user permission cache with TTL and Redis pubsub invalidation.

The effective permissions for a user can be expensive to compute
(role DAG walk + tenant scoping + direct grants). This cache stores
the result for up to 5 minutes and listens for invalidation events
published by the admin API whenever a role/grant/binding changes.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import redis.asyncio as redis

PERMISSION_INVALIDATION_CHANNEL = "rbac:invalidate"
DEFAULT_TTL_SECONDS = 300


@dataclass
class CacheEntry:
    permissions: frozenset[str]
    expires_at: float


class PermissionCache:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[tuple[str, str], CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get_or_compute(
        self,
        user_id: str,
        tenant_id: str,
        compute: Callable[[], Awaitable[frozenset[str]]],
    ) -> frozenset[str]:
        key = (user_id, tenant_id)
        now = time.monotonic()
        async with self._lock:
            entry = self._store.get(key)
            if entry and entry.expires_at > now:
                return entry.permissions
        fresh = await compute()
        async with self._lock:
            self._store[key] = CacheEntry(permissions=fresh, expires_at=now + self._ttl)
        return fresh

    async def invalidate_user(self, user_id: str, tenant_id: str) -> None:
        async with self._lock:
            self._store.pop((user_id, tenant_id), None)

    async def listen_for_invalidations(self, client: redis.Redis) -> None:
        pubsub = client.pubsub()
        await pubsub.subscribe(PERMISSION_INVALIDATION_CHANNEL)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                payload = json.loads(msg["data"])
                await self.invalidate_user(payload["user_id"], payload["tenant_id"])
            except (json.JSONDecodeError, KeyError):
                continue
```



## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Permission check is deny-by-default** | `has_permission` returns False unless an exact, wildcard, or `*:*` match exists. |
| QS-2 | **Wildcards are explicit** | `*:*`, `resource:*`, `*:action` are the only wildcard forms. No regex. |
| QS-3 | **Role inheritance is acyclic** | CRUD `assign_role_parent` rejects cycles (BFS ancestor check). |
| QS-4 | **Effective permissions cached per (user, tenant)** | LRU cache, TTL configurable, invalidated on role/binding change. |
| QS-5 | **Cache invalidation propagates via Redis pubsub** | `publish_user_invalidation` after every binding change; all workers clear. |
| QS-6 | **Tenant-scoped bindings respected** | When tenant context is set, only bindings with `tenant_id == current_tenant OR tenant_id IS NULL` apply. |
| QS-7 | **System roles cannot be deleted** | Roles with `is_system=true` are protected; CRUD raises 409 on delete. |
| QS-8 | **Seed roles auto-created in migration** | Default `viewer/editor/admin` + admin's `*:*` permission. Idempotent via name uniqueness. |
| QS-9 | **Permission codes are validated by DB** | CheckConstraint on `permissions.code` regex. |
| QS-10 | **Audit on every mutation** | Reuses `add_audit_log` if installed; otherwise logs to a dedicated `rbac_audit` table created by this tool. |
| QS-11 | **Decorator returns 403, not 404** | `require_permission` raises 403 to clearly signal authorization failure (vs 404 which signals "not found"). |
| QS-12 | **Effective permission computation is bounded** | Recursive role walk has max depth 32 (safety limit); raises if exceeded. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `Permission`, `Role`, `RolePermission`, `UserRole` models exist | File `app/models/rbac.py` |
| CC-02 | `app/core/rbac/evaluator.py` exists with `compute_effective_permissions` + `has_permission` | File exists |
| CC-03 | `app/core/rbac/cache.py` exists with `PermCache` | File exists |
| CC-04 | `app/core/rbac/deps.py` exists with `require_permission` | File exists |
| CC-05 | `app/crud/rbac.py` exists | File exists |
| CC-06 | `app/api/routes/rbac.py` exists when `with_admin_ui=True` | File exists |
| CC-07 | `app/schemas/rbac.py` exists with all schemas | File exists |
| CC-08 | Migration `0012_add_rbac.py` exists | File exists |
| CC-09 | Migration creates 4 tables + seeds default roles | Inspect upgrade() |
| CC-10 | Permission code CheckConstraint matches regex | grep |
| CC-11 | Role name CheckConstraint matches regex | grep |
| CC-12 | UserRole has `(user_id, role_id, tenant_id)` unique constraint | grep |
| CC-13 | Role hierarchy via `parent_id` FK to self | grep |
| CC-14 | Cycles in role parents rejected by CRUD | T-09 |
| CC-15 | Wildcard permission `*:*` matches anything | T-04 |
| CC-16 | `RBAC_CACHE_TTL` settings configurable | grep config.py |
| CC-17 | Cache invalidation pubsub channel constant | grep |
| CC-18 | App startup wires `start_invalidation_listener` | grep main.py |
| CC-19 | Routes registered in `app/api/main.py` (when admin UI on) | grep |
| CC-20 | OpenAPI exposes new endpoints | curl /openapi.json |
| CC-21 | New file `tests/test_rbac.py` with 30 tests | File exists |
| CC-22 | Existing tests pass | pytest 0 failures |
| CC-23 | All files parse | Tool internal |
| CC-24 | Tool execution time < 5s | Time measurement |
| CC-25 | Permission check p99 < 0.5 ms cached | Benchmark T-29 |
| CC-26 | Effective compute < 20 ms for 10 roles | Benchmark T-30 |
| CC-27 | Idempotent re-run | T-26 |
| CC-28 | System roles protected from deletion | T-15 |
| CC-29 | Tenant-scoped bindings respected | T-12 |
| CC-30 | Default roles seeded with correct hierarchy | T-19 |

---

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 7 Invariants enforced
- [ ] All 25 User Stories pass acceptance tests
- [ ] All 30 Test Cases pass
- [ ] Tool is idempotent
- [ ] Tool is reversible: rollback procedure documented and tested
- [ ] Performance budget met
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RB-01 | Permission check is deny-by-default | `has_permission` only returns True on explicit match | T-01, T-02 |
| INV-RB-02 | A wildcard `*:*` ALWAYS grants any check | first check in `has_permission` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-04 |
| INV-RB-03 | A role NEVER inherits from itself directly or transitively | BFS cycle check on `assign_role_parent` | T-09 |
| INV-RB-04 | A system role NEVER deletes | CRUD checks `is_system` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-15 |
| INV-RB-05 | A binding mutation ALWAYS invalidates the user's cache | Routes call `publish_user_invalidation` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-21 |
| INV-RB-06 | A tenant-scoped binding NEVER applies in another tenant | Evaluator filter `tenant_id == current_tenant OR NULL` | T-12 |
| INV-RB-07 | The recursive role walk NEVER exceeds depth 32 | Hard limit in evaluator — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-25 |

---

## 9. User Stories

### 9.1 Permission primitives (US-01 .. US-05)

**US-01: Deny access when user holds no matching permission**
- **As a** backend developer protecting a `POST /orders/` route
- **I want** `require_permission("orders:create")` to return HTTP 403 for a user whose effective permission set is empty
- **So that** unauthenticated or under-privileged callers never mutate order state by default
- **Given:** a fresh user with no role bindings and no direct permission grants, and a route decorated with `Depends(require_permission("orders:create"))`
- **When:** the user sends a valid JWT to `POST /orders/`
- **Then:**
  - the response status is `403 Forbidden` with body `{"detail": "Permission denied"}`
  - `has_permission(set(), "orders:create")` returns `False` (INV-RB-01)
  - no order row is inserted into the database
  - the cold-path DB query still completes within 5 ms (CC-25)

**US-02: Grant access when user holds the exact matching permission code**
- **As a** backend developer
- **I want** `require_permission("items:write")` to return HTTP 200 when the user's effective set contains exactly `"items:write"`
- **So that** fine-grained permission codes map 1-to-1 to protected actions without role overhead
- **Given:** a `Permission` row with `code="items:write"` is bound to the user via a `RolePermission` + `UserRole` chain
- **When:** the user sends a valid JWT to `POST /items/`
- **Then:**
  - the response status is `200 OK`
  - `has_permission({"items:write"}, "items:write")` returns `True`
  - the permission code passes the DB `CheckConstraint` regex `^([a-z][a-z0-9_-]{0,62}|\*):([a-z][a-z0-9_-]{0,62}|\*)$` (CC-10)

**US-03: Reject permission code that violates the resource:action format**
- **As a** backend developer seeding custom permissions
- **I want** the DB `CheckConstraint` on `permissions.code` to block malformed codes at insert time
- **So that** no permission with an ambiguous or injectable code can ever be created
- **Given:** an attempt to `INSERT INTO permissions (code) VALUES ('Items Write')` (uppercase + space)
- **When:** the SQL executes against PostgreSQL
- **Then:**
  - PostgreSQL raises `IntegrityError` citing `ck_permissions_code_format`
  - the `create_permission` CRUD function surfaces this as HTTP `422 Unprocessable Entity`
  - no row is written (CC-10, INV-RB-01)

**US-04: Universal wildcard `*:*` grants every permission check**
- **As a** platform operator assigning a superadmin service account
- **I want** a single `*:*` permission grant to satisfy any `require_permission(...)` check anywhere in the API
- **So that** internal automation tools can operate across all domains without maintaining an exhaustive permission list
- **Given:** a user's effective permission set is `{"*:*"}`
- **When:** `has_permission({"*:*"}, "invoices:delete")` is called — and then called with `"telemetry:export"`, `"settings:write"`, and `"users:impersonate"`
- **Then:**
  - all four calls return `True`
  - the wildcard check short-circuits before any database round-trip (INV-RB-02, CC-15, T-04)

**US-05: Resource-level wildcard `reports:*` covers all actions on that resource**
- **As a** backend developer building a reporting module
- **I want** `reports:*` to cover `reports:read`, `reports:export`, `reports:share`, and any future `reports:X` action
- **So that** I can grant broad access to a resource without enumerating every action
- **Given:** a role `analyst` has `RolePermission` with `code="reports:*"`, and a user is bound to `analyst`
- **When:** `require_permission("reports:read")`, `require_permission("reports:export")`, and `require_permission("reports:share")` are each evaluated for this user
- **Then:**
  - all three checks return `True` and the corresponding routes return `200 OK`
  - `require_permission("billing:read")` still returns `403` (deny-by-default, INV-RB-01, T-03)

---

### 9.2 Role inheritance (US-06 .. US-10)

**US-06: Inherited permissions flow transitively through a role DAG**
- **As a** platform engineer defining `admin → editor → viewer` hierarchy
- **I want** a user bound only to `admin` to automatically possess every permission granted to `editor` and `viewer`
- **So that** I don't need to duplicate permission grants across roles
- **Given:** `viewer` has `items:read`; `editor` inherits `viewer` and adds `items:write`; `admin` inherits `editor`; a user has only the `admin` role binding
- **When:** `compute_effective_permissions(user_id, db)` is called
- **Then:**
  - the returned set contains `{"items:read", "items:write"}` plus any permissions granted directly to `admin`
  - the BFS walk visits roles in topological order without duplicates (CC-13, T-08)
  - computation completes in < 20 ms even with 10 roles in the chain (CC-26)

**US-07: Adding a role cycle is rejected with HTTP 400**
- **As a** platform engineer
- **I want** `PATCH /rbac/roles/{b_id}/parent` with `parent_id = a.id` to fail if role A already has role B as an ancestor
- **So that** the role DAG never becomes cyclic, preventing infinite recursion in `compute_effective_permissions`
- **Given:** role A's `parent_id` is already role B (A → B), meaning B is an ancestor of A
- **When:** a superadmin POSTs `{"parent_id": a.id}` to set B's parent to A
- **Then:**
  - the API returns `400 Bad Request` with body `{"detail": "Role cycle detected"}`
  - neither role's `parent_id` is modified in the database (INV-RB-03, CC-14, T-09)

**US-08: Role inheritance walk stops at depth-32 hard limit**
- **As a** platform security engineer
- **I want** `compute_effective_permissions` to raise `RuntimeError` after visiting 32 ancestor roles
- **So that** a pathological or adversarially crafted role chain cannot cause a stack overflow or runaway DB query
- **Given:** 33 roles chained linearly (role-1 → role-2 → ... → role-33), each with one unique permission
- **When:** `compute_effective_permissions` is invoked for a user bound to role-1
- **Then:**
  - a `RuntimeError` (or mapped HTTP `500`) is raised after the 32nd level
  - the partial permission set is not cached or returned (INV-RB-07, T-10, T-25)

**US-09: Action-level wildcard `*:read` grants read on every resource**
- **As a** backend developer building a read-only audit role
- **I want** `*:read` to satisfy any `require_permission("X:read")` check regardless of the resource name X
- **So that** I can create a cross-domain read-only role with a single permission row
- **Given:** a role `auditor` has `RolePermission` with `code="*:read"`, and a user is bound to `auditor`
- **When:** `require_permission("invoices:read")`, `require_permission("users:read")`, and `require_permission("telemetry:read")` are evaluated
- **Then:**
  - all three checks return `True`
  - `require_permission("invoices:write")` still returns `403` (INV-RB-01, CC-15, T-05)

**US-10: Parent role not found returns HTTP 404**
- **As a** backend developer automating role setup via the admin API
- **I want** `POST /rbac/roles` with a non-existent `parent_id` UUID to return `404 Not Found` immediately
- **So that** misconfigured scripts get a clear error rather than a silent dangling FK violation
- **Given:** `parent_id` is a valid UUID format but no `roles` row exists with that ID
- **When:** a superadmin sends `POST /rbac/roles {"name": "ops", "parent_id": "<ghost-uuid>"}`
- **Then:**
  - the API returns `404 Not Found` with `{"detail": "Parent role not found"}`
  - no new role row is inserted
  - the CRUD function checks existence before attempting the INSERT (CC-13)

---

### 9.3 Route enforcement (US-11 .. US-15)

**US-11: `require_permission` dependency blocks unauthorized user at the FastAPI layer**
- **As a** backend developer
- **I want** `Depends(require_permission("invoices:delete"))` on `DELETE /invoices/{id}` to short-circuit before the handler body executes
- **So that** no business logic runs for callers who lack the required permission
- **Given:** the route is declared as `@router.delete("/invoices/{id}", dependencies=[Depends(require_permission("invoices:delete"))])`; the requesting user's effective permissions are `{"invoices:read"}`
- **When:** the user sends `DELETE /invoices/abc123`
- **Then:**
  - FastAPI raises `HTTPException(status_code=403)` before the handler function is entered
  - the invoice row is not touched in the database
  - the permission evaluator runs against the in-process cache (p99 < 0.5 ms, CC-25, T-27)

**US-12: Superadmin with `*:*` bypasses every `require_permission` check**
- **As a** platform operator
- **I want** a user bound to a role that carries `*:*` to pass every `require_permission(...)` call without per-endpoint configuration
- **So that** I can designate a break-glass account that can act on any resource in an emergency
- **Given:** user `svc-ops` is bound to the `admin` role, and `admin` has the `*:*` permission
- **When:** `svc-ops` calls any of `POST /items/`, `DELETE /invoices/123`, `PATCH /users/456/roles`, and `GET /telemetry/traces`
- **Then:**
  - all four routes return their normal `2xx` responses
  - no 403 is raised for any route (INV-RB-02, CC-15, T-03, T-04)

**US-13: Viewer role can read but cannot write**
- **As a** product manager setting up a read-only stakeholder account
- **I want** the seeded `viewer` role (which has `items:read`) to allow `GET /items/` and block `POST /items/`
- **So that** stakeholders can browse data without accidentally mutating production records
- **Given:** user `stakeholder@example.com` is bound only to the `viewer` role; `viewer` has `items:read` and nothing else
- **When:** the user calls `GET /items/` and then `POST /items/ {"name": "new"}`
- **Then:**
  - `GET /items/` returns `200 OK` with the item list
  - `POST /items/` returns `403 Forbidden`
  - no new item row is created (INV-RB-01, CC-30, T-17)

**US-14: System role `admin` cannot be deleted via admin API**
- **As a** platform engineer
- **I want** `DELETE /rbac/roles/{admin_id}` to return `409 Conflict` when the target role has `is_system=True`
- **So that** the default role hierarchy (`viewer → editor → admin`) can never be accidentally destroyed by an API call
- **Given:** the `admin` role was seeded by the migration with `is_system=True`
- **When:** a superadmin sends `DELETE /rbac/roles/{admin.id}`
- **Then:**
  - the API returns `409 Conflict` with `{"detail": "System role cannot be deleted"}`
  - the `admin` row remains in the `roles` table (INV-RB-04, CC-28, T-15)

**US-15: Custom non-system role can be deleted, removing all its bindings**
- **As a** platform engineer decommissioning a deprecated `legacy-reporter` role
- **I want** `DELETE /rbac/roles/{role_id}` for a non-system role to cascade-delete all `role_permissions` and `user_roles` bindings
- **So that** no orphaned bindings exist that could grant unexpected permissions after the role is removed
- **Given:** role `legacy-reporter` has `is_system=False`, 3 `role_permissions` rows, and 7 `user_roles` rows
- **When:** a superadmin sends `DELETE /rbac/roles/{legacy-reporter.id}`
- **Then:**
  - the API returns `204 No Content`
  - the `roles`, `role_permissions`, and `user_roles` rows for `legacy-reporter` are all absent from the DB
  - a subsequent `require_permission("reports:read")` check for an affected user returns `403` (CC-28, INV-RB-05, T-16)

---

### 9.4 Cache & invalidation (US-16 .. US-21)

**US-16: Cold-path permission check fetches from DB and populates in-process cache**
- **As a** backend developer instrumenting a freshly deployed worker
- **I want** the first `require_permission` call for a given `user_id` to query PostgreSQL and then store the result in `PermCache`
- **So that** subsequent calls within the TTL window avoid database round-trips entirely
- **Given:** the in-process `PermCache` contains no entry for `user_id="u-001"`; the DB has the user's role bindings
- **When:** the user calls any RBAC-protected endpoint twice in quick succession
- **Then:**
  - the first call incurs one `SELECT` against the `user_roles` + `role_permissions` join; latency is < 5 ms
  - the second call is served from cache; latency is < 0.5 ms p99 (CC-16, CC-25, T-20)
  - `PermCache._store` contains an entry keyed to `"u-001"` with a TTL timestamp

**US-17: Cache entry expires after configured TTL and triggers a DB reload**
- **As a** platform engineer tuning freshness vs. load
- **I want** the `PermCache` to reload permissions from PostgreSQL once the per-entry TTL elapses
- **So that** permission changes made outside the pubsub path (e.g., direct DB writes in migrations) eventually propagate to all workers
- **Given:** `RBAC_CACHE_TTL=1` second; user `u-002`'s permissions are cached at `t0`
- **When:** `require_permission("items:read")` is evaluated for `u-002` at `t0 + 2 seconds`
- **Then:**
  - the cache entry for `u-002` is treated as stale and evicted
  - a fresh `SELECT` is issued to PostgreSQL
  - the new permission set replaces the old entry in the cache (CC-16, T-22)

**US-18: LRU eviction keeps the cache bounded to 10,000 users**
- **As a** site-reliability engineer managing a high-traffic deployment
- **I want** `PermCache` to evict the least-recently-used entry when its size exceeds 10,000 user slots
- **So that** memory overhead stays below 5 MB per worker regardless of the user base size
- **Given:** `PermCache` already holds 10,000 entries (users `u-1` through `u-10000`), and `u-1` is the least recently accessed
- **When:** a permission check for the 10,001st distinct user `u-10001` is processed
- **Then:**
  - the cache size remains at 10,000
  - `u-1` is no longer present in `PermCache._store`
  - `u-10001` is present with a fresh TTL (CC-16, T-23)

**US-19: Granting a new role to a user invalidates that user's cache on all workers via Redis pubsub**
- **As a** platform engineer promoting a user from `viewer` to `editor`
- **I want** the `POST /rbac/users/{user_id}/roles` endpoint to publish `{"user_id": "u-042"}` to the `rbac:invalidate` Redis channel immediately after the DB write
- **So that** every worker that has `u-042`'s old permission set cached drops it and re-fetches on the next request — within 1 second
- **Given:** 2 FastAPI workers are running; both have `u-042`'s old permission set `{"items:read"}` in their `PermCache`
- **When:** Worker 1 processes `POST /rbac/users/u-042/roles {"role_id": "<editor-id>"}`
- **Then:**
  - Worker 1 commits the `user_roles` row and publishes the invalidation message
  - Worker 2 receives the pubsub message within 1 second and evicts `u-042` from its `PermCache`
  - the next check on Worker 2 for `u-042` fetches the updated set `{"items:read", "items:write"}` from DB (INV-RB-05, CC-17, CC-18, T-21, T-24)

**US-20: Publishing `user_id="*"` clears the entire in-process cache**
- **As a** platform operator performing an emergency permission reset
- **I want** a targeted Redis publish of `{"user_id": "*"}` to clear all entries from every worker's `PermCache`
- **So that** a compromised role grant is fully invalidated cluster-wide without restarting workers
- **Given:** `PermCache` on the target worker contains entries for 500 users
- **When:** `redis-cli PUBLISH rbac:invalidate '{"user_id":"*"}'` is executed
- **Then:**
  - the `start_invalidation_listener` callback clears `PermCache._store` completely
  - the next permission check for any user triggers a cold DB fetch (CC-17, CC-18, T-20)

**US-21: Concurrent cache population by multiple coroutines does not produce stale duplicates**
- **As a** backend developer deploying a high-concurrency async FastAPI app
- **I want** the `asyncio.Lock` inside `PermCache.get_or_load` to ensure only one coroutine queries the DB when multiple coroutines miss on the same `user_id` simultaneously
- **So that** a cache stampede does not produce multiple conflicting permission sets or unnecessary DB load
- **Given:** `PermCache` has no entry for `u-007`; 50 async tasks simultaneously call `require_permission("orders:read")` for `u-007`
- **When:** all 50 tasks execute concurrently under the same event loop
- **Then:**
  - exactly 1 `SELECT` is issued to PostgreSQL for `u-007`
  - all 50 tasks receive the same permission set
  - `PermCache._store` has exactly 1 entry for `u-007` after all tasks complete (CC-16, INV-RB-01, T-20)

---

### 9.5 Multi-tenant & audit (US-22 .. US-25)

**US-22: Tenant-scoped role binding applies only within the bound tenant**
- **As a** SaaS platform architect
- **I want** a `user_roles` row with `tenant_id="tenant-A"` to grant its permissions only when the request context carries `tenant-A`
- **So that** a user who is `admin` in `tenant-A` cannot act as admin when accessing `tenant-B`'s data
- **Given:** user `u-100` has a `user_roles` row `(role=admin, tenant_id="tenant-A")`; the `admin` role has `items:delete`
- **When:** `u-100` sends `DELETE /items/99` with the `tenant-A` subdomain header, and then with the `tenant-B` subdomain header
- **Then:**
  - the `tenant-A` request returns `200 OK`
  - the `tenant-B` request returns `403 Forbidden`
  - the evaluator filters bindings by `tenant_id = "tenant-A" OR NULL` (INV-RB-06, CC-29, T-11, T-12)

**US-23: Global binding (tenant_id=NULL) applies across every tenant**
- **As a** platform operator managing a cross-tenant service account
- **I want** a `user_roles` row with `tenant_id=NULL` to grant its role regardless of which tenant context the request carries
- **So that** infra service accounts can operate platform-wide without per-tenant binding rows
- **Given:** user `svc-platform` has `user_roles (role=admin, tenant_id=NULL)`
- **When:** `svc-platform` calls `DELETE /items/1` against `tenant-A`, `tenant-B`, and `tenant-C` in three separate requests
- **Then:**
  - all three requests return `200 OK`
  - the evaluator includes the NULL-tenant binding when building the effective permission set for every tenant context (CC-29, T-13)

**US-24: RBAC installed without multi-tenancy stores all bindings as tenant_id=NULL**
- **As a** backend developer on a single-tenant application
- **I want** `add_rbac(project_dir)` (without TOOL-008 multi-tenancy installed) to omit the FK constraint on `UserRole.tenant_id` so the column stays `NULL` for all rows
- **So that** the RBAC system is usable on single-tenant apps without requiring tenancy infrastructure
- **Given:** the project has no `tenants` table and no `X-Tenant-ID` middleware
- **When:** `add_rbac(project_dir)` completes and a user is assigned the `editor` role
- **Then:**
  - the `user_roles` row is inserted with `tenant_id=NULL`
  - all permission evaluations proceed as if bindings are global
  - no FK error is raised on the `tenant_id` column (CC-12, T-14)

**US-25: Every role assignment and revocation produces an audit trail entry via TOOL-005**
- **As a** compliance officer requiring a SOC 2 audit trail
- **I want** every call to `POST /rbac/users/{user_id}/roles` and `DELETE /rbac/users/{user_id}/roles/{role_id}` to write an `AuditLog` row via `add_audit_log`'s `create_audit_entry` function
- **So that** I can answer "who granted the `admin` role to user X and when?" without relying on DB transaction logs
- **Given:** TOOL-005 `add_audit_log` is installed; user `admin@example.com` (the actor) assigns role `editor` to user `u-200`
- **When:** `POST /rbac/users/u-200/roles {"role_id": "<editor-id>"}` is processed
- **Then:**
  - one `AuditLog` row is created with `action="role_assigned"`, `actor_id=admin@example.com`, `target_id="u-200"`, `metadata={"role": "editor"}`, and a UTC `created_at` timestamp
  - the role assignment DB write and the audit write occur in the same transaction
  - a subsequent `DELETE` of the same binding writes `action="role_revoked"` with equivalent fields (CC-23, INV-RB-05, T-28)

## 10. Test Plan

### 10.1 Permission check semantics

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Empty perms denies | perms=set() | has_permission(set(),"x:y") | False |
| T-02 | Exact match passes | perms={"x:y"} | check "x:y" | True |
| T-03 | Resource wildcard | perms={"items:*"} | check "items:read" | True |
| T-04 | Universal wildcard | perms={"*:*"} | check "anything:anything" | True |
| T-05 | Action wildcard | perms={"*:read"} | check "items:read" | True |
| T-06 | No match denies | perms={"x:y"} | check "a:b" | False |

### 10.2 Role inheritance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Single role → its perms | role with [items:read] | compute_effective | {items:read} |
| T-08 | Inherited role → combined perms | admin → editor → [items:write] | compute admin | includes items:write |
| T-09 | Cycle rejected | A→B, set B→A | CRUD | 400 |
| T-10 | Depth limit | 33 nested roles | compute | RuntimeError |

### 10.3 Tenant scoping

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | Tenant binding applies | role in tenant A | request as A | granted |
| T-12 | Tenant binding does not leak | role in A | request as B | denied |
| T-13 | Global binding applies | tenant_id=NULL | any tenant | granted |
| T-14 | Multi-tenancy off → all bindings global | no tenant context | check | as if global |

### 10.4 Lifecycle & system roles

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | Cannot delete system role | DELETE /rbac/roles/admin | request | 409 |
| T-16 | Can delete custom role | role analyst (is_system=false) | DELETE | 204 |
| T-17 | Assign role | POST /rbac/users/{id}/roles | request | 200, binding exists |
| T-18 | Revoke role | DELETE /rbac/users/{id}/roles/{rid} | request | 200, binding gone |
| T-19 | Default seeds correct | fresh DB | inspect | viewer/editor/admin exist; admin has *:* |

### 10.5 Cache, idempotency, performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-20 | Cache miss → DB | cold | check | DB queried |
| T-21 | Granting invalidates cache | warm cache | grant + check | new perms reflected immediately |
| T-22 | TTL expiry reloads | TTL=1s | check at t+2s | reloaded |
| T-23 | LRU evicts | fill > 10k | check oldest | evicted |
| T-24 | Pubsub propagates < 1s | 2 workers | grant on A | B sees within 1s |
| T-25 | Recursion depth limit | 33 nested | compute | error |
| T-26 | Tool re-run no-op | installed | run | no changes |
| T-27 | require_permission decorator works | route with dep | unauthorized user | 403 |
| T-28 | Audit entry written | add_audit_log installed | assign | audit row exists |
| T-29 | Cached check p99 < 0.5 ms | benchmark | measure | < 0.5 ms |
| T-30 | Compute < 20 ms 10 roles | benchmark | measure | < 20 ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Tenancy first** | ✅ Compatible | UserRole.tenant_id FK to tenants; bindings scoped per tenant. |
| `add_audit_log` | **Audit first** | ✅ Compatible | Role/permission/binding mutations produce audit entries. |
| `add_api_key_auth` | No | ⚠️ Caveat | API key scopes are independent from RBAC permissions; document the difference. |
| `add_oauth2_provider` | No | ✅ Compatible | OAuth users get default role on signup (`viewer` by default). |
| `add_mfa` | No | ✅ Compatible | MFA gates session creation; permissions still apply post-MFA. |
| `add_feature_flags` | No | ✅ Compatible | Flags can target by role. |
| `add_cache_layer` | No | ✅ Compatible | Separate caches; no conflict. |
| `add_outbox_pattern` | No | ✅ Compatible | RBAC mutations can emit outbox events. |
| `add_soft_delete` | No | ⚠️ Caveat | Soft-deleting a User does not revoke their bindings; cache invalidation must happen. |
| `add_search` | No | ✅ Compatible | RBAC tables not searched by default. |
| `add_rate_limit` | No | ✅ Compatible | Rate-limit RBAC admin endpoints to prevent brute force on user_id enumeration. |
| TOOL-034 performance_baseline | downstream | `POST /rbac/roles`, `POST /rbac/users/{user_id}/roles`, and `DELETE /rbac/users/{user_id}/roles/{role_id}` are captured in the baseline (target p99 < 50 ms); a change to `compute_effective_permissions` in `app/core/rbac/evaluator.py` that adds a recursive DB traversal for deep role hierarchies will be caught before merge |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_rbac` is installed but no `add_audit_log` is present and recommends TOOL-007 `add_audit_log` so that role assignment and revocation events produce audit rows — flagged as HIGH since privilege-escalation incidents require an immutable trail |
| TOOL-029 security_scan | downstream | `app/core/rbac/evaluator.py` and `app/core/rbac/deps.py` are scanned by semgrep for `assert` statements used as access-control guards (bandit B101) and for RBAC bypass patterns (missing `require_permission` on admin routes); any CRITICAL finding blocks merge |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/rbac.py app/core/rbac \
  app/crud/rbac.py app/api/routes/rbac.py app/schemas/rbac.py \
  app/main.py app/api/main.py app/core/config.py
rm alembic/versions/*_add_rbac.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `user_roles`, `role_permissions`, `roles`, `permissions` in reverse order. **Warning**: any code path using `require_permission` will fail until that code is also rolled back. Roll back code first, then DB.

### Data preservation rollback
```sql
CREATE TABLE _rbac_archive_user_roles AS SELECT * FROM user_roles;
CREATE TABLE _rbac_archive_role_permissions AS SELECT * FROM role_permissions;
CREATE TABLE _rbac_archive_roles AS SELECT * FROM roles;
CREATE TABLE _rbac_archive_permissions AS SELECT * FROM permissions;
-- Then alembic downgrade -1
```

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_rbac.py`
- Drop partially-created tables
- Re-run

### Emergency: privilege escalation detected
1. Audit `user_roles` for recent grants: `SELECT * FROM user_roles WHERE granted_at > ... ORDER BY granted_at DESC`
2. Revoke suspect bindings: `DELETE FROM user_roles WHERE id = ...`
3. Publish global cache invalidation: `redis-cli PUBLISH rbac:invalidate '{"user_id":"*"}'`
4. Notify the user account owners

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no User model | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | Project has no Alembic | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-3 | Project has multi-tenancy but RBAC installed without it | UserRole.tenant_id is nullable; works in mono-tenant mode |
| EC-4 | Default role seeds collide with existing roles | Migration uses `INSERT ... ON CONFLICT DO NOTHING` |
| EC-5 | A user is assigned the same role twice | UNIQUE constraint blocks; returns 409 |
| EC-6 | A role is granted a permission it already has | UNIQUE constraint blocks; returns 409 |
| EC-7 | Two superadmins assign different roles to same user concurrently | Both succeed (different role_id); cache invalidated twice |
| EC-8 | A user has 100 roles | Compute walks all; result is union; cache populates with all perms |
| EC-9 | Cache bloat from many unique users | LRU bounded at 10k; oldest evicted |
| EC-10 | Pubsub message dropped | TTL eventually expires entry; consistency restored within 5 min |
| EC-11 | Recursive role chain reaches DB at every step (slow) | Profiler flags it; future optimization to bulk-load roles |
| EC-12 | Permission code violates regex | DB check rejects insert; the operation returns a structured error response and no side effects persist |
| EC-13 | Permission code with reserved chars `:` in resource | Regex blocks; the operation returns a structured error response and no side effects persist |
| EC-14 | Multiple workers race to populate cache | OK; both succeed; identical value |
| EC-15 | Migration fails on `gen_random_uuid()` (extension not installed) | Tool documents `CREATE EXTENSION IF NOT EXISTS pgcrypto` in next_steps |

---

## 14. Acceptance Criteria

1. ✅ All 30 CC verified
2. ✅ All 25 user stories pass
3. ✅ All 30 tests pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified
7. ✅ Rollback procedure tested
8. ✅ Performance SLOs met
9. ✅ Re-audit by Opus: ≥ 9.5/10
10. ✅ One human dev creates 3 roles, assigns them, and protects 5 routes without confusion

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Alembic initialized
- [ ] Detect existing `roles` table → idempotent skip if found
- [ ] Validate `pgcrypto` extension available (for `gen_random_uuid()`)
- [ ] Assert pre-flight raises `ValueError` when `roles` table already exists via `test_preflight.py::test_idempotent_skip_when_roles_table_exists`
- [ ] Assert pre-flight raises `MissingExtensionError` when `pgcrypto` absent via `test_preflight.py::test_missing_pgcrypto_raises`

### 15.2 Settings
- [ ] Add `RBAC_CACHE_TTL: int = 300` to settings
- [ ] Confirm `RBAC_CACHE_TTL` is read from `.env` and exposed as `settings.rbac_cache_ttl` via `test_settings.py::test_rbac_cache_ttl_env_override`
- [ ] Verify `mypy --strict app/core/config.py` reports zero new errors after adding the field
- [ ] Document `RBAC_CACHE_TTL` in `docs/configuration.md` with default value and valid range
- [ ] Add `RBAC_CACHE_TTL=300` to `.env.example`
- [ ] Add structured log entry `{"event": "rbac_cache_ttl_loaded", "value": ...}` at app startup

### 15.3 Models
- [ ] Create `app/models/rbac.py` with 4 classes
- [ ] CheckConstraints + UniqueConstraints
- [ ] Verify file parses
- [ ] Assert `UniqueConstraint` on `(role_id, permission_id)` prevents duplicate bindings via `test_models.py::test_duplicate_role_permission_raises_integrity_error`
- [ ] Assert `CheckConstraint` on `code` column rejects empty string via `test_models.py::test_empty_code_check_constraint`
- [ ] Run `ruff check app/models/rbac.py` and `mypy app/models/rbac.py` — zero findings before merging

### 15.4 Evaluator module
- [ ] Create `app/core/rbac/evaluator.py`
- [ ] Implement `compute_effective_permissions` with depth limit 32
- [ ] Implement `has_permission` with wildcard support
- [ ] Verify file parses
- [ ] Test DAG cycle detection via `test_inheritance.py::test_cycle_raises_CyclicRoleError`
- [ ] Assert depth > 32 is truncated via `test_inheritance.py::test_depth_limit_truncates_at_32`
- [ ] Assert wildcard `*:*` grants any permission via `test_evaluator.py::test_wildcard_permission_matches_any_resource`
- [ ] Run `mypy --strict app/core/rbac/evaluator.py` — zero errors

### 15.5 Cache module
- [ ] Create `app/core/rbac/cache.py`
- [ ] Implement `PermCache` (LRU + TTL + asyncio.Lock)
- [ ] Implement `start_invalidation_listener` and `publish_user_invalidation`
- [ ] Verify file parses
- [ ] Assert stale entry is evicted after TTL via `test_cache.py::test_entry_expires_after_ttl`
- [ ] Assert Redis pub/sub invalidation clears the in-process LRU entry via `test_cache.py::test_redis_invalidation_clears_local_cache`
- [ ] Assert concurrent access under `asyncio.Lock` does not produce duplicate DB reads via `test_cache.py::test_no_cache_stampede_under_concurrent_access`

### 15.6 Dependency module
- [ ] Create `app/core/rbac/deps.py`
- [ ] Implement `get_effective_permissions`
- [ ] Implement `require_permission`
- [ ] Verify file parses
- [ ] Assert `require_permission("posts:write")` raises HTTP 403 for a user with only `posts:read` via `test_deps.py::test_require_permission_raises_403_when_missing`
- [ ] Assert `require_permission` returns without error for superuser with `*:*` via `test_deps.py::test_superuser_wildcard_bypasses_check`
- [ ] Run `mypy --strict app/core/rbac/deps.py` — zero errors

### 15.7 CRUD
- [ ] Create `app/crud/rbac.py` with create_role, create_permission, assign_user_role, revoke_user_role, assign_role_parent (with cycle check)
- [ ] Verify file parses
- [ ] Assert `assign_role_parent` rejects a parent that would form a cycle via `test_crud_rbac.py::test_assign_role_parent_cycle_check`
- [ ] Assert `revoke_user_role` emits Redis invalidation message via `test_crud_rbac.py::test_revoke_publishes_invalidation`
- [ ] Assert `create_role` emits structured log `{"event": "role_created", "role_id": ..., "code": ...}`
- [ ] Run `ruff check app/crud/rbac.py` — zero findings

### 15.8 Schemas
- [ ] Create `app/schemas/rbac.py` with PermissionCreate/Public, RoleCreate/Public, RoleAssignment
- [ ] Pydantic validators on `code` and `name`
- [ ] Verify file parses
- [ ] Assert `code` validator rejects whitespace and uppercase via `test_schemas_rbac.py::test_code_validator_rejects_uppercase_and_whitespace`
- [ ] Assert `PermissionCreate` serialises to camelCase for API consumers via `test_schemas_rbac.py::test_permission_create_alias_generator`
- [ ] Run `mypy --strict app/schemas/rbac.py` — zero errors

### 15.9 Routes (when `with_admin_ui=True`)
- [ ] Create `app/api/routes/rbac.py`
- [ ] All endpoints require `CurrentSuperuser`
- [ ] Publish cache invalidation after every binding mutation
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Assert `POST /rbac/roles` returns 403 for a non-superuser JWT via `test_routes_rbac.py::test_create_role_requires_superuser`
- [ ] Assert `DELETE /rbac/roles/{id}/permissions/{pid}` publishes an invalidation event via `test_routes_rbac.py::test_unbind_permission_publishes_invalidation`

### 15.10 App startup wiring
- [ ] Modify `app/main.py` lifespan to call `get_perm_cache().listen(redis)` on startup
- [ ] Assert the lifespan coroutine calls `get_perm_cache().listen(redis)` exactly once via `test_startup.py::test_perm_cache_listener_registered_on_startup`
- [ ] Assert app shuts down cleanly when Redis is unavailable (fallback to DB-only mode) via `test_startup.py::test_startup_tolerates_redis_unavailable`
- [ ] Run `ruff check app/main.py` and `mypy app/main.py` — zero new findings
- [ ] Add trace span `rbac.cache.listen_started` with tag `ttl=RBAC_CACHE_TTL` in the lifespan startup block
- [ ] Document `RBAC_CACHE_TTL` and Redis pub/sub channel name in README under "Configuration"

### 15.11 Migration
- [ ] Generate `0NNN_add_rbac.py`
- [ ] `upgrade()` creates 4 tables + indexes + check constraints
- [ ] Seed default roles + admin's `*:*` permission
- [ ] Use `INSERT ... ON CONFLICT DO NOTHING` for idempotency
- [ ] `downgrade()` drops in reverse
- [ ] Verify migration parses
- [ ] Assert `alembic upgrade head` then `alembic downgrade -1` completes on a blank schema without errors via `test_migrations.py::test_rbac_migration_upgrade_downgrade_roundtrip`

### 15.12 Test generation
- [ ] Create `tests/test_rbac.py` with all 30 tests
- [ ] Use existing fixtures + new `role_factory`, `user_with_roles` fixtures
- [ ] Verify file parses
- [ ] Assert overall line coverage for `app/core/rbac/` is ≥ 90% via `pytest --cov=app.core.rbac --cov-fail-under=90`
- [ ] Assert `role_factory` fixture correctly creates roles with nested inheritance via `test_rbac.py::test_role_factory_nested_inheritance`
- [ ] Run `ruff check tests/test_rbac.py` — zero findings

### 15.13 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created tables on failure
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Assert that injecting a write failure mid-way leaves no partial files on disk via `test_atomicity.py::test_rollback_removes_partial_files`
- [ ] Assert returned dict contains non-empty `files_rolled_back` after a simulated failure via `test_atomicity.py::test_error_response_includes_rolled_back_list`
- [ ] Run `mypy app/core/rbac/` — zero errors after rollback path changes

### 15.14 Documentation
- [ ] Append RBAC section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Assert `manifest.yaml` entry for `add_rbac` contains `inputs`, `outputs`, and `idempotent: true` fields via `test_manifest.py::test_rbac_tool_manifest_schema`
- [ ] Assert `SKILL.md` tools table row for TOOL-012 links to this spec file via `test_skill_md.py::test_tool_012_row_exists_with_spec_link`
- [ ] Run `ruff check mcp_server.py` — zero new findings after the update

### 15.15 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure cache p99 latency
- [ ] Measure compute time

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/rbac.py",
    "app/core/rbac/__init__.py",
    "app/core/rbac/evaluator.py",
    "app/core/rbac/cache.py",
    "app/core/rbac/deps.py",
    "app/crud/rbac.py",
    "app/schemas/rbac.py",
    "app/api/routes/rbac.py",
    "alembic/versions/0012_add_rbac.py",
    "tests/test_rbac.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/api/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 4198,
    "files_changed": 13,
    "lines_added": 982,
    "lines_removed": 5,
    "default_roles": ["viewer", "editor", "admin"],
    "cache_ttl_seconds": 300
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_rbac.py -v",
    "Create custom roles: POST /rbac/roles {name:'analyst', description:'...'}",
    "Assign role to user: POST /rbac/users/{user_id}/roles {role_id:'...'}",
    "Protect a route: `@router.post('/items/', dependencies=[Depends(require_permission('items:write'))])`"
  ],
  "warnings": [
    "Default admin role has *:* permission (full access). Restrict assignment carefully.",
    "Cache invalidation requires Redis pubsub. Without Redis, workers stay stale up to RBAC_CACHE_TTL (300s default).",
    "If multi-tenancy is installed, all bindings are tenant-scoped unless tenant_id is explicitly NULL (global)."
  ],
  "notes": [
    "RBAC installed with default roles: viewer, editor, admin (admin → editor inheritance).",
    "Four tables created: permissions, roles, role_permissions, user_roles.",
    "Wildcards supported: *:*, resource:*, *:action.",
    "Existing tests still pass: 58/58."
  ]
}
```
