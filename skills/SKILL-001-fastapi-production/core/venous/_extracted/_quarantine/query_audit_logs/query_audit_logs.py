from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def query_audit_logs(session: AsyncSession, filters: AuditLogFilter, offset: int=0, limit: int=50) -> AuditLogPage:
    """Return paginated audit entries matching the given filters.

    Args:
        session: Async SQLAlchemy session.
        filters: AuditLogFilter with optional predicates.
        offset: Pagination offset.
        limit: Page size (max 500).

    Returns:
        AuditLogPage with items, total, offset, and limit.
    """
    stmt = select(AuditLog)
    if filters.entity_type:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(filters.entity_id))
    if filters.actor_id:
        stmt = stmt.where(AuditLog.user_id == filters.actor_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.from_dt:
        stmt = stmt.where(AuditLog.created_at >= filters.from_dt)
    if filters.to_dt:
        stmt = stmt.where(AuditLog.created_at <= filters.to_dt)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [AuditLogEntry.model_validate(r) for r in rows]
    return AuditLogPage(items=items, total=total, offset=offset, limit=limit)
