from __future__ import annotations


async def restore(session: _AsyncSession, item_id: _uuid.UUID) -> '{model_name} | None':
    """Restore a soft-deleted row. Atomically clears all three deletion columns.

    Args:
        session: Async SQLAlchemy session.
        item_id: Primary key of the row to restore.

    Returns:
        The restored ORM instance, or ``None`` if not found in deleted records.
    """
    stmt = _select({model_name}).where({model_name}.id == item_id, {model_name}.is_deleted == True).execution_options(include_deleted=True)
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by = None
    await session.flush()
    return obj
