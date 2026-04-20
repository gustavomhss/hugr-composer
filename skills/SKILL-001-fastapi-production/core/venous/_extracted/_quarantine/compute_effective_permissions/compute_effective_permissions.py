from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


async def compute_effective_permissions(session: AsyncSession, user_id: UUID, tenant_id: UUID | None=None) -> set[str]:
    """Return the effective permission codes for a user.

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
    """
    stmt = select(UserRole).where(UserRole.user_id == user_id).options(selectinload(UserRole.role))
    if tenant_id is not None:
        stmt = stmt.where((UserRole.tenant_id == tenant_id) | UserRole.tenant_id.is_(None))
    user_roles = (await session.execute(stmt)).scalars().all()
    if not user_roles:
        return set()
    role_ids = await _collect_role_ids_via_bfs(session, [ur.role_id for ur in user_roles])
    if not role_ids:
        return set()
    rows = (await session.execute(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id.in_(role_ids)))).scalars().all()
    return set(rows)
