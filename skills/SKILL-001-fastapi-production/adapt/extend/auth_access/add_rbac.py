"""TOOL-012: add_rbac — add production-grade RBAC to a FastAPI/SQLAlchemy project.

Writes Permission, Role, RolePermission and UserRole models, an effective-
permissions evaluator with cycle-safe DAG inheritance, a per-user permission
cache with TTL and Redis pub/sub invalidation, a ``require_permission()``
FastAPI dependency, admin CRUD endpoints under ``/rbac/``, Pydantic schemas,
and an Alembic migration with seeded default roles.

The tool is idempotent: a second run detects the ``Permission`` model
fingerprint in ``app/models/rbac.py`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_rbac import add_rbac

    result = add_rbac(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/models/rbac.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_rbac(inp: ToolInput) -> ToolResult:
    """Add RBAC to a FastAPI project.

    Writes all RBAC-related files (models, evaluator, cache, deps, schemas,
    routes, migration) and patches ``app/api/main.py`` to include the new
    router.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Pre-flight: idempotency guard -----------------------------------
    rbac_model_file = app_dir / "models" / "rbac.py"
    if rbac_model_file.exists() and "class Permission" in rbac_model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RBAC models already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install RBAC models, evaluator, cache, deps, routes, migration."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Detect whether add_multi_tenancy was applied so UserRole.tenant_id
    # only emits a FK when the tenants table actually exists.
    has_tenants = (app_dir / "models" / "tenant.py").exists()

    # Step 1: Models
    _write_rbac_models(rbac_model_file, has_tenants=has_tenants)
    files_created.append(str(rbac_model_file))

    # Register RBAC models in app/models/__init__.py for metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [
            ("rbac", "Permission"),
            ("rbac", "Role"),
            ("rbac", "RolePermission"),
            ("rbac", "UserRole"),
        ],
    )

    # Step 2: Inheritance resolver (pure Python, no DB)
    inheritance_file = app_dir / "core" / "rbac" / "inheritance.py"
    _write_inheritance(inheritance_file)
    files_created.append(str(inheritance_file))

    # Step 3: Evaluator (async, DB-backed)
    evaluator_file = app_dir / "core" / "rbac" / "evaluator.py"
    _write_evaluator(evaluator_file)
    files_created.append(str(evaluator_file))

    # Step 4: Permission cache (in-process LRU + Redis pubsub)
    cache_file = app_dir / "core" / "rbac" / "cache.py"
    _write_cache(cache_file)
    files_created.append(str(cache_file))

    # Step 5: FastAPI dependency
    deps_file = app_dir / "core" / "rbac" / "deps.py"
    _write_deps(deps_file)
    files_created.append(str(deps_file))

    # Step 6: Schemas
    schemas_file = app_dir / "schemas" / "rbac.py"
    _write_schemas(schemas_file)
    files_created.append(str(schemas_file))

    # Step 7: CRUD helpers
    crud_file = app_dir / "crud" / "rbac.py"
    _write_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 8: Routes
    routes_file = app_dir / "api" / "routes" / "rbac.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 9: Patch app/routes/__init__.py to include router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    # Step 10: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "RBAC installed: Permission, Role, RolePermission, UserRole models.",
            "Use Depends(require_permission('resource:action')) in any route.",
            "Effective permissions are cached per (user, tenant) with TTL + Redis invalidation.",
            "Default roles seeded: viewer, editor (parent=viewer), admin (parent=editor).",
            "Admin assigned *:* permission via migration seed.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Add RBAC_CACHE_TTL=300 to your .env / settings.",
            "Restart the application to register the /rbac/ router.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Ensures new model modules are loaded at package import time so their
    Table definitions attach to ``Base.metadata`` for ``create_all()`` and
    Alembic autogenerate.
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _write_rbac_models(dest: Path, has_tenants: bool = False) -> None:
    """Write app/models/rbac.py with Permission, Role, RolePermission, UserRole.

    Args:
        dest: Absolute destination path.
        has_tenants: When True, emit UserRole.tenant_id with a FK to tenants.id.
            When False, emit a plain Uuid column with no FK (add_multi_tenancy
            was not applied, so the tenants table does not exist).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"RBAC SQLAlchemy models: Permission, Role, RolePermission, UserRole.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            Boolean,
            CheckConstraint,
            DateTime,
            ForeignKey,
            String,
            UniqueConstraint,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.models.base import Base


        class Permission(Base):
            \"\"\"A single resource:action permission token (e.g. 'items:write').

            Attributes:
                id: UUID primary key.
                code: Canonical permission code in resource:action format.
                description: Optional human-readable description.
                created_at: UTC creation timestamp.
            \"\"\"

            __tablename__ = "permissions"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            code: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
            description: Mapped[str | None] = mapped_column(String(500), nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            __table_args__ = (
                CheckConstraint(
                    "code LIKE '%:%'",
                    name="ck_permissions_code_format",
                ),
            )


        class Role(Base):
            \"\"\"A named role with optional parent (forms a DAG for inheritance).

            Attributes:
                id: UUID primary key.
                name: Unique role name (lowercase, e.g. 'admin').
                description: Optional human-readable description.
                parent_id: FK to another Role for inheritance (nullable).
                is_system: True for built-in roles that cannot be deleted.
                created_at: UTC creation timestamp.
                parent: ORM relationship to parent Role.
                permissions: Related RolePermission bindings.
            \"\"\"

            __tablename__ = "roles"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
            description: Mapped[str | None] = mapped_column(String(500), nullable=True)
            parent_id: Mapped[uuid.UUID | None] = mapped_column(
                Uuid, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
            )
            is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            parent: Mapped["Role | None"] = relationship(remote_side="Role.id")
            permissions: Mapped[list["RolePermission"]] = relationship(
                back_populates="role", cascade="all, delete-orphan"
            )

            __table_args__ = (
                CheckConstraint(
                    "length(name) >= 1 AND length(name) <= 63",
                    name="ck_roles_name_format",
                ),
            )


        class RolePermission(Base):
            \"\"\"Many-to-many binding between Role and Permission.

            Attributes:
                id: UUID primary key.
                role_id: FK to roles.
                permission_id: FK to permissions.
                role: ORM relationship to Role.
            \"\"\"

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
            \"\"\"Binding of a User to a Role, optionally scoped to a Tenant.

            Attributes:
                id: UUID primary key.
                user_id: FK to users.
                role_id: FK to roles.
                tenant_id: Optional FK to tenants (NULL = global binding).
                granted_by: FK to the user who granted this binding (nullable).
                granted_at: UTC timestamp when the binding was created.
            \"\"\"

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
    """))
    # Strip the tenants FK when add_multi_tenancy was NOT applied — the
    # tenants table does not exist and SQLAlchemy would raise
    # NoReferencedTableError at metadata resolution time.
    if not has_tenants:
        src = dest.read_text()
        src = src.replace(
            'Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True',
            "Uuid, nullable=True  # no FK — add_multi_tenancy not applied",
        )
        dest.write_text(src)


def _write_inheritance(dest: Path) -> None:
    """Write app/core/rbac/inheritance.py — pure-Python DAG resolver with cycle detection.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pure-Python role DAG resolver with cycle detection.

        This module is intentionally dependency-free (no SQLAlchemy) so it can
        be unit-tested without a database.  The DB-backed evaluator in
        ``app.core.rbac.evaluator`` calls these helpers after loading data.
        \"\"\"

        from __future__ import annotations

        from dataclasses import dataclass, field


        @dataclass(frozen=True)
        class RoleNode:
            \"\"\"Lightweight role representation for in-memory DAG traversal.

            Attributes:
                name: Unique role name.
                direct_permissions: Permission codes directly assigned to this role.
                parent_role_names: Names of parent roles (for inheritance).
            \"\"\"

            name: str
            direct_permissions: frozenset[str]
            parent_role_names: frozenset[str] = field(default_factory=frozenset)


        class CyclicRoleError(Exception):
            \"\"\"Raised when a cycle is detected in the role inheritance graph.\"\"\"


        def effective_permissions(
            role_name: str,
            registry: dict[str, RoleNode],
            _visited: frozenset[str] | None = None,
        ) -> frozenset[str]:
            \"\"\"Return merged permission set for a role by walking the DAG recursively.

            Args:
                role_name: Name of the role to resolve.
                registry: Mapping of role name → RoleNode.
                _visited: Internal cycle-detection set (callers should omit).

            Returns:
                Frozen set of permission codes (e.g. ``frozenset({'items:read'})``)

            Raises:
                ValueError: If ``role_name`` is not in ``registry``.
                CyclicRoleError: If a cycle is detected in the inheritance chain.
            \"\"\"
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
            \"\"\"Check whether *granted* satisfies *required* with wildcard support.

            Wildcards are ``*`` on resource or action segment only.

            Args:
                granted: A code from the user's effective permission set.
                required: The required permission code (no wildcards expected).

            Returns:
                ``True`` if ``granted`` covers ``required``.
            \"\"\"
            g_r, _, g_a = granted.partition(":")
            r_r, _, r_a = required.partition(":")
            return (g_r in ("*", r_r)) and (g_a in ("*", r_a))


        def has_permission(effective: frozenset[str] | set[str], required: str) -> bool:
            \"\"\"Return True if any code in *effective* covers *required*.

            Args:
                effective: The user's full effective permission set.
                required: The required permission code (``resource:action``).

            Returns:
                ``True`` when at least one granted code covers the required code.
            \"\"\"
            return any(permission_allows(g, required) for g in effective)
    """))


def _write_evaluator(dest: Path) -> None:
    """Write app/core/rbac/evaluator.py — async DB-backed permission resolver.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async DB-backed effective-permissions evaluator for RBAC.

        Queries the database to build the user's effective permission set by
        walking the role inheritance DAG and collecting all granted permission
        codes.  Results are cached by ``app.core.rbac.cache``.
        \"\"\"

        from __future__ import annotations

        from uuid import UUID

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import selectinload

        from app.models.rbac import Permission, Role, RolePermission, UserRole


        async def _collect_role_ids_via_bfs(
            session: AsyncSession, seed_role_ids: list
        ) -> set:
            \"\"\"Walk the role inheritance DAG via BFS to collect all ancestor role IDs.

            Args:
                session: Async SQLAlchemy session.
                seed_role_ids: Initial list of directly-assigned role IDs.

            Returns:
                Set of all role UUIDs reachable from the seeds (inclusive).
            \"\"\"
            role_ids: set = set()
            queue = list(seed_role_ids)
            while queue:
                rid = queue.pop()
                if rid in role_ids:
                    continue
                role_ids.add(rid)
                role = (await session.execute(select(Role).where(Role.id == rid))).scalar_one_or_none()
                if role and role.parent_id and role.parent_id not in role_ids:
                    queue.append(role.parent_id)
            return role_ids


        async def compute_effective_permissions(
            session: AsyncSession,
            user_id: UUID,
            tenant_id: UUID | None = None,
        ) -> set[str]:
            \"\"\"Return the effective permission codes for a user.

            Walks the role inheritance DAG via BFS, collecting every Role the
            user has (directly or through inheritance), then fetches all
            Permission codes associated with those roles.

            Args:
                session: Async SQLAlchemy session.
                user_id: User whose permissions to resolve.
                tenant_id: When provided, include bindings scoped to this
                    tenant AND global (NULL-tenant) bindings.

            Returns:
                Set of permission code strings (e.g. ``{'items:read', '*:*'}``).
            \"\"\"
            stmt = (
                select(UserRole)
                .where(UserRole.user_id == user_id)
                .options(selectinload(UserRole.role))
            )
            if tenant_id is not None:
                stmt = stmt.where(
                    (UserRole.tenant_id == tenant_id) | (UserRole.tenant_id.is_(None))
                )
            user_roles = (await session.execute(stmt)).scalars().all()
            if not user_roles:
                return set()
            role_ids = await _collect_role_ids_via_bfs(session, [ur.role_id for ur in user_roles])
            if not role_ids:
                return set()
            rows = (await session.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id.in_(role_ids))
            )).scalars().all()
            return set(rows)


        def has_permission(effective: set[str], required: str) -> bool:
            \"\"\"Wildcard-aware check: does *effective* contain *required*?

            Args:
                effective: Set of permission codes for the user.
                required: The required permission code (``resource:action``).

            Returns:
                ``True`` if any code in *effective* covers *required*.
            \"\"\"
            if required in effective:
                return True
            if "*:*" in effective:
                return True
            resource, _, action = required.partition(":")
            return f"{resource}:*" in effective or f"*:{action}" in effective
    """))


def _write_cache(dest: Path) -> None:
    """Write app/core/rbac/cache.py — LRU cache with Redis pubsub invalidation.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Per-user permission cache with TTL and Redis pub/sub invalidation.

        Stores the effective permission set per (user_id, tenant_id) in an
        in-process OrderedDict LRU cache.  Cache entries expire after
        ``RBAC_CACHE_TTL`` seconds and can also be invalidated instantly via
        a Redis pub/sub message, ensuring all workers stay consistent.
        \"\"\"

        from __future__ import annotations

        import asyncio
        import json
        import time
        from collections import OrderedDict
        from uuid import UUID

        try:
            from app.core.config import settings
            _TTL: float = float(getattr(settings, "RBAC_CACHE_TTL", 300))
        except Exception:  # pragma: no cover — test environments without settings
            _TTL = 300.0

        MAX_SIZE = 10_000
        INVALIDATION_CHANNEL = "rbac:invalidate"


        class PermissionCache:
            \"\"\"Thread-safe async LRU permission cache.

            Attributes:
                _ttl: Cache entry TTL in seconds.
                _store: OrderedDict mapping (user_id, tenant_id) → (timestamp, perms).
                _lock: Async lock protecting the store.
                _listener_task: Background asyncio task for Redis pub/sub.
            \"\"\"

            def __init__(self, ttl: float = _TTL) -> None:
                self._ttl = ttl
                self._store: OrderedDict[
                    tuple[UUID, UUID | None], tuple[float, set[str]]
                ] = OrderedDict()
                self._lock = asyncio.Lock()
                self._listener_task: asyncio.Task | None = None

            async def get(self, user_id: UUID, tenant_id: UUID | None) -> set[str] | None:
                \"\"\"Return cached permissions or None if missing/expired.

                Args:
                    user_id: The user's UUID.
                    tenant_id: Optional tenant scope.

                Returns:
                    Copy of the cached permission set, or ``None``.
                \"\"\"
                async with self._lock:
                    entry = self._store.get((user_id, tenant_id))
                    if entry is None:
                        return None
                    ts, perms = entry
                    if time.monotonic() - ts > self._ttl:
                        del self._store[(user_id, tenant_id)]
                        return None
                    self._store.move_to_end((user_id, tenant_id))
                    return set(perms)

            async def set(
                self, user_id: UUID, tenant_id: UUID | None, perms: set[str]
            ) -> None:
                \"\"\"Store permissions for (user_id, tenant_id), evicting LRU if full.

                Args:
                    user_id: The user's UUID.
                    tenant_id: Optional tenant scope.
                    perms: Permission code set to cache.
                \"\"\"
                async with self._lock:
                    key = (user_id, tenant_id)
                    self._store[key] = (time.monotonic(), set(perms))
                    self._store.move_to_end(key)
                    while len(self._store) > MAX_SIZE:
                        self._store.popitem(last=False)

            async def invalidate_user(self, user_id: UUID) -> None:
                \"\"\"Remove all cache entries for *user_id* across all tenants.

                Args:
                    user_id: User whose cache entries should be cleared.
                \"\"\"
                async with self._lock:
                    for k in list(self._store):
                        if k[0] == user_id:
                            del self._store[k]

            async def clear(self) -> None:
                \"\"\"Clear all cache entries (broadcast invalidation).\"\"\"
                async with self._lock:
                    self._store.clear()

            async def start_listener(self, redis) -> None:  # type: ignore[type-arg]
                \"\"\"Start a background task that listens for Redis invalidation messages.

                Args:
                    redis: An async Redis client (``redis.asyncio.Redis``).
                \"\"\"
                async def _run() -> None:
                    ps = redis.pubsub()
                    await ps.subscribe(INVALIDATION_CHANNEL)
                    async for msg in ps.listen():
                        if msg.get("type") != "message":
                            continue
                        try:
                            payload = json.loads(msg["data"])
                            uid = payload.get("user_id")
                            if uid == "*":
                                await self.clear()
                            else:
                                await self.invalidate_user(UUID(uid))
                        except Exception:  # noqa: BLE001
                            pass

                self._listener_task = asyncio.create_task(_run())


        _cache: PermissionCache | None = None


        def get_perm_cache() -> PermissionCache:
            \"\"\"Return the process-level singleton PermissionCache.

            Returns:
                The shared ``PermissionCache`` instance.
            \"\"\"
            global _cache
            if _cache is None:
                _cache = PermissionCache()
            return _cache


        async def publish_invalidation(redis, user_id: UUID | str) -> None:  # type: ignore[type-arg]
            \"\"\"Publish a cache-invalidation event for *user_id* on Redis.

            Args:
                redis: Async Redis client.
                user_id: User UUID or ``"*"`` for a full-cache clear.
            \"\"\"
            await redis.publish(
                INVALIDATION_CHANNEL, json.dumps({"user_id": str(user_id)})
            )
    """))


def _write_deps(dest: Path) -> None:
    """Write app/core/rbac/deps.py — require_permission FastAPI dependency.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"FastAPI dependencies for RBAC permission enforcement.

        Usage::

            from app.core.rbac.deps import require_permission

            @router.post("/items/", dependencies=[Depends(require_permission("items:write"))])
            async def create_item(...): ...
        \"\"\"

        from __future__ import annotations

        from fastapi import Depends, HTTPException, status

        from app.api.deps import CurrentUser, SessionDep
        from app.core.rbac.cache import get_perm_cache
        from app.core.rbac.evaluator import compute_effective_permissions, has_permission


        def _get_tenant_id():
            \"\"\"Return current tenant UUID or None (stub; replaced when multi-tenancy installed).\"\"\"
            try:
                from app.core.tenant_context import get_current_tenant
                return get_current_tenant()
            except ImportError:
                return None


        async def get_effective_permissions(
            current_user: CurrentUser,
            session: SessionDep,
        ) -> set[str]:
            \"\"\"Resolve the effective permissions for the current user.

            Checks the per-process cache first; on a miss, computes from the DB
            and populates the cache.

            Args:
                current_user: Injected authenticated user.
                session: Injected async DB session.

            Returns:
                Set of permission code strings.
            \"\"\"
            tenant_id = _get_tenant_id()
            cache = get_perm_cache()
            cached = await cache.get(current_user.id, tenant_id)
            if cached is not None:
                return cached
            perms = await compute_effective_permissions(session, current_user.id, tenant_id)
            await cache.set(current_user.id, tenant_id, perms)
            return perms


        def require_permission(code: str):
            \"\"\"Return a FastAPI dependency that 403s when the user lacks *code*.

            Args:
                code: Required permission in ``resource:action`` format,
                    e.g. ``"items:write"`` or ``"*:*"``.

            Returns:
                An async dependency callable suitable for ``Depends()``.
            \"\"\"

            async def _dep(perms: set[str] = Depends(get_effective_permissions)) -> None:
                \"\"\"Raise 403 if *code* is not in the user's effective permissions.

                Args:
                    perms: Injected effective permissions from ``get_effective_permissions``.

                Raises:
                    HTTPException: 403 if the required permission is missing.
                \"\"\"
                if not has_permission(perms, code):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Missing required permission: {code}",
                    )

            return _dep
    """))


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/rbac.py — Pydantic schemas for RBAC endpoints.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for RBAC admin endpoints.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class PermissionCreate(BaseModel):
            \"\"\"Input schema for creating a Permission.

            Attributes:
                code: Permission code in ``resource:action`` format.
                description: Optional human-readable description.
            \"\"\"

            code: str = Field(..., max_length=127)
            description: str | None = Field(default=None, max_length=500)


        class PermissionPublic(BaseModel):
            \"\"\"Read schema for a Permission.

            Attributes:
                id: UUID primary key.
                code: Permission code.
                description: Optional description.
                created_at: UTC creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            code: str
            description: str | None = None
            created_at: datetime


        class RoleCreate(BaseModel):
            \"\"\"Input schema for creating a Role.

            Attributes:
                name: Unique lowercase role name.
                description: Optional description.
                parent_id: Optional parent role UUID for inheritance.
            \"\"\"

            name: str = Field(..., max_length=63)
            description: str | None = Field(default=None, max_length=500)
            parent_id: uuid.UUID | None = None


        class RolePublic(BaseModel):
            \"\"\"Read schema for a Role.

            Attributes:
                id: UUID primary key.
                name: Unique role name.
                description: Optional description.
                parent_id: Parent role UUID, if any.
                is_system: True for built-in roles.
                created_at: UTC creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            name: str
            description: str | None = None
            parent_id: uuid.UUID | None = None
            is_system: bool
            created_at: datetime


        class RoleAssignment(BaseModel):
            \"\"\"Input schema for assigning a role to a user.

            Attributes:
                role_id: UUID of the role to assign.
                tenant_id: Optional tenant scope; NULL means global.
            \"\"\"

            role_id: uuid.UUID
            tenant_id: uuid.UUID | None = None
    """))


def _write_crud(dest: Path) -> None:
    """Write app/crud/rbac.py — async CRUD helpers for RBAC objects.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async CRUD helpers for RBAC: permissions, roles, and bindings.\"\"\"

        from __future__ import annotations

        import uuid
        from uuid import UUID

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.rbac import Permission, Role, RolePermission, UserRole
        from app.schemas.rbac import PermissionCreate, RoleCreate


        async def create_permission(
            session: AsyncSession, *, p_in: PermissionCreate
        ) -> Permission:
            \"\"\"Insert a new Permission and flush.

            Args:
                session: Async SQLAlchemy session.
                p_in: Permission creation payload.

            Returns:
                The newly created Permission ORM instance.
            \"\"\"
            perm = Permission(id=uuid.uuid4(), code=p_in.code, description=p_in.description)
            session.add(perm)
            await session.flush()
            return perm


        async def create_role(session: AsyncSession, *, r_in: RoleCreate) -> Role:
            \"\"\"Insert a new Role and flush.

            Args:
                session: Async SQLAlchemy session.
                r_in: Role creation payload.

            Returns:
                The newly created Role ORM instance.
            \"\"\"
            role = Role(
                id=uuid.uuid4(),
                name=r_in.name,
                description=r_in.description,
                parent_id=r_in.parent_id,
            )
            session.add(role)
            await session.flush()
            return role


        async def assign_user_role(
            session: AsyncSession,
            *,
            user_id: UUID | str,
            role_id: UUID | str,
            tenant_id: UUID | str | None = None,
            granted_by: UUID | str | None = None,
        ) -> UserRole:
            \"\"\"Create a UserRole binding, ignoring duplicate (idempotent).

            Args:
                session: Async SQLAlchemy session.
                user_id: UUID of the user to assign the role to.
                role_id: UUID of the role.
                tenant_id: Optional tenant scope (NULL = global).
                granted_by: UUID of the granting user.

            Returns:
                Existing or newly created UserRole instance.
            \"\"\"
            uid = UUID(str(user_id))
            rid = UUID(str(role_id))
            tid = UUID(str(tenant_id)) if tenant_id else None
            existing = (
                await session.execute(
                    select(UserRole).where(
                        UserRole.user_id == uid,
                        UserRole.role_id == rid,
                        UserRole.tenant_id == tid,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                return existing
            binding = UserRole(
                id=uuid.uuid4(),
                user_id=uid,
                role_id=rid,
                tenant_id=tid,
                granted_by=UUID(str(granted_by)) if granted_by else None,
            )
            session.add(binding)
            await session.flush()
            return binding


        async def revoke_user_role(
            session: AsyncSession, *, user_id: UUID | str, role_id: UUID | str
        ) -> bool:
            \"\"\"Delete all UserRole bindings matching (user_id, role_id).

            Args:
                session: Async SQLAlchemy session.
                user_id: UUID of the user.
                role_id: UUID of the role to revoke.

            Returns:
                ``True`` if at least one binding was deleted, ``False`` otherwise.
            \"\"\"
            uid = UUID(str(user_id))
            rid = UUID(str(role_id))
            rows = (
                await session.execute(
                    select(UserRole).where(
                        UserRole.user_id == uid, UserRole.role_id == rid
                    )
                )
            ).scalars().all()
            for row in rows:
                await session.delete(row)
            await session.flush()
            return bool(rows)
    """))


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/rbac.py — admin CRUD endpoints for RBAC.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Admin RBAC endpoints: /rbac/permissions, /rbac/roles, /rbac/users/{id}/roles.\"\"\"

        from __future__ import annotations

        import uuid as _uuid

        from fastapi import APIRouter, HTTPException, status

        from app.api.deps import CurrentSuperuser, SessionDep
        from app.core.rbac.cache import get_perm_cache, publish_invalidation
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
        async def create_permission(
            p_in: PermissionCreate, session: SessionDep, current_user: CurrentSuperuser
        ) -> PermissionPublic:
            \"\"\"Create a new permission code. Superuser only.

            Args:
                p_in: Permission creation payload.
                session: Injected async DB session.
                current_user: CurrentSuperuser guard — ensures caller is a superuser.

            Returns:
                The created Permission.
            \"\"\"
            return await crud_rbac.create_permission(session, p_in=p_in)


        @router.post("/roles", response_model=RolePublic, status_code=201)
        async def create_role(
            r_in: RoleCreate, session: SessionDep, current_user: CurrentSuperuser
        ) -> RolePublic:
            \"\"\"Create a new role. Superuser only.

            Args:
                r_in: Role creation payload.
                session: Injected async DB session.
                current_user: CurrentSuperuser guard — ensures caller is a superuser.

            Returns:
                The created Role.
            \"\"\"
            return await crud_rbac.create_role(session, r_in=r_in)


        @router.post("/users/{user_id}/roles", response_model=dict, status_code=201)
        async def assign_role(
            user_id: str,
            binding: RoleAssignment,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> dict:
            \"\"\"Assign a role to a user (optionally scoped to a tenant). Superuser only.

            Args:
                user_id: UUID string of the target user.
                binding: Role assignment payload.
                session: Injected async DB session.
                current_user: Authenticated superuser (used as granted_by).

            Returns:
                JSON ``{"status": "ok"}``.
            \"\"\"
            await crud_rbac.assign_user_role(
                session,
                user_id=user_id,
                role_id=binding.role_id,
                tenant_id=binding.tenant_id,
                granted_by=current_user.id,
            )
            cache = get_perm_cache()
            try:
                await cache.invalidate_user(_uuid.UUID(user_id))
            except Exception:  # noqa: BLE001
                pass
            return {"status": "ok"}


        @router.delete("/users/{user_id}/roles/{role_id}", response_model=dict, status_code=200)
        async def revoke_role(
            user_id: str,
            role_id: str,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> dict:
            \"\"\"Revoke a role from a user. Superuser only.

            Args:
                user_id: UUID string of the target user.
                role_id: UUID string of the role to revoke.
                session: Injected async DB session.
                current_user: CurrentSuperuser guard — ensures caller is a superuser.

            Returns:
                JSON ``{"status": "ok"}``.
            \"\"\"
            await crud_rbac.revoke_user_role(session, user_id=user_id, role_id=role_id)
            cache = get_perm_cache()
            try:
                await cache.invalidate_user(_uuid.UUID(user_id))
            except Exception:  # noqa: BLE001
                pass
            return {"status": "ok"}
    """))


def _patch_api_main(routes_init: Path) -> None:
    """Register the RBAC router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.rbac import router as rbac_router",
        include_line="api_router.include_router(rbac_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)

    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _write_migration(versions_dir: Path) -> Path:
    """Generate alembic/versions/0012_add_rbac.py with table creation + seed data.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path to the created migration file.
    """
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add RBAC tables: permissions, roles, role_permissions, user_roles.

        Revision ID: 0012_add_rbac
        Revises: {down_rev}
        Create Date: auto-generated by add_rbac tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0012_add_rbac"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create permissions, roles, role_permissions, user_roles tables with seeds.\"\"\"
            op.create_table(
                "permissions",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("code", sa.String(127), nullable=False),
                sa.Column("description", sa.String(500), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "code LIKE '%:%'",
                    name="ck_permissions_code_format",
                ),
                sa.UniqueConstraint("code"),
            )
            op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

            op.create_table(
                "roles",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("name", sa.String(63), nullable=False),
                sa.Column("description", sa.String(500), nullable=True),
                sa.Column(
                    "parent_id",
                    sa.Uuid(),
                    sa.ForeignKey("roles.id", ondelete="SET NULL"),
                    nullable=True,
                ),
                sa.Column(
                    "is_system",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "length(name) >= 1 AND length(name) <= 63", name="ck_roles_name_format"
                ),
                sa.UniqueConstraint("name"),
            )
            op.create_index("ix_roles_name", "roles", ["name"], unique=True)

            op.create_table(
                "role_permissions",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "role_id",
                    sa.Uuid(),
                    sa.ForeignKey("roles.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "permission_id",
                    sa.Uuid(),
                    sa.ForeignKey("permissions.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
            )

            op.create_table(
                "user_roles",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "role_id",
                    sa.Uuid(),
                    sa.ForeignKey("roles.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "tenant_id",
                    sa.Uuid(),
                    sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                    nullable=True,
                ),
                sa.Column(
                    "granted_by",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True,
                ),
                sa.Column(
                    "granted_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_roles"),
            )
            op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

            # Seed default roles
            op.execute(
                "INSERT INTO roles (id, name, description, is_system) VALUES "
                "(gen_random_uuid(), 'viewer', 'Read-only access', true),"
                "(gen_random_uuid(), 'editor', 'Read and write access', true),"
                "(gen_random_uuid(), 'admin', 'Full access', true);"
            )
            op.execute(
                "UPDATE roles SET parent_id = "
                "(SELECT id FROM roles WHERE name='viewer') WHERE name='editor';"
            )
            op.execute(
                "UPDATE roles SET parent_id = "
                "(SELECT id FROM roles WHERE name='editor') WHERE name='admin';"
            )
            op.execute(
                "INSERT INTO permissions (id, code, description) VALUES "
                "(gen_random_uuid(), '*:*', 'All permissions on all resources');"
            )
            op.execute(
                "INSERT INTO role_permissions (id, role_id, permission_id) VALUES "
                "(gen_random_uuid(), "
                "(SELECT id FROM roles WHERE name='admin'), "
                "(SELECT id FROM permissions WHERE code='*:*'));"
            )


        def downgrade() -> None:
            \"\"\"Drop RBAC tables in reverse dependency order.\"\"\"
            op.drop_index("ix_user_roles_user_id", table_name="user_roles")
            op.drop_table("user_roles")
            op.drop_table("role_permissions")
            op.drop_index("ix_roles_name", table_name="roles")
            op.drop_table("roles")
            op.drop_index("ix_permissions_code", table_name="permissions")
            op.drop_table("permissions")
        """).replace("{down_rev}", down_rev)

    dest = versions_dir / "0012_add_rbac.py"
    dest.write_text(content)
    return dest


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
