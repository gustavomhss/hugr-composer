from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid


async def assign_user_role(session: AsyncSession, *, user_id: UUID | str, role_id: UUID | str, tenant_id: UUID | str | None=None, granted_by: UUID | str | None=None) -> UserRole:
    """Create a UserRole binding, ignoring duplicate (idempotent).

    Args:
        session: Async SQLAlchemy session.
        user_id: UUID of the user to assign the role to.
        role_id: UUID of the role.
        tenant_id: Optional tenant scope (NULL = global).
        granted_by: UUID of the granting user.

    Returns:
        Existing or newly created UserRole instance.
    """
    uid = UUID(str(user_id))
    rid = UUID(str(role_id))
    tid = UUID(str(tenant_id)) if tenant_id else None
    existing = (await session.execute(select(UserRole).where(UserRole.user_id == uid, UserRole.role_id == rid, UserRole.tenant_id == tid))).scalar_one_or_none()
    if existing:
        return existing
    binding = UserRole(id=uuid.uuid4(), user_id=uid, role_id=rid, tenant_id=tid, granted_by=UUID(str(granted_by)) if granted_by else None)
    session.add(binding)
    await session.flush()
    return binding
