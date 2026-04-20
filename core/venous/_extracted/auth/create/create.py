from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def create(session: AsyncSession, *, flag_in: FeatureFlagCreate, actor_id: uuid.UUID | None=None) -> FeatureFlag:
    """Create a new FeatureFlag and write a 'create' audit row.

    Args:
        session: Async SQLAlchemy session.
        flag_in: Validated create schema.
        actor_id: UUID of the acting user (for audit trail).

    Returns:
        Newly created FeatureFlag ORM instance.
    """
    flag = FeatureFlag(**flag_in.model_dump(), updated_by=actor_id)
    session.add(flag)
    await session.flush()
    await session.refresh(flag)
    _write_audit(session, flag, action='create', before=None, actor_id=actor_id)
    await session.flush()
    return flag
