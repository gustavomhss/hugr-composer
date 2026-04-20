from __future__ import annotations


async def soft_delete(session: _AsyncSession, item_id: _uuid.UUID, *, deleted_by: _uuid.UUID | None=None) -> '{model_name} | None':
    """Soft-delete: set is_deleted=True, deleted_at=now(UTC).

    Args:
        session: Async SQLAlchemy session.
        item_id: Primary key of the row to soft-delete.
        deleted_by: UUID of the acting user (for audit trail).

    Returns:
        The updated ORM instance, or ``None`` if not found.
    """
    stmt = _select({model_name}).where({model_name}.id == item_id, {model_name}.is_deleted == False)
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    obj.is_deleted = True
    obj.deleted_at = _dt.now(_tz.utc)
    if deleted_by is not None:
        obj.deleted_by = deleted_by
    await session.flush()
    return obj
