from __future__ import annotations


async def hard_delete(session: _AsyncSession, item_id: _uuid.UUID) -> '{model_name} | None':
    """Permanently remove a row. Superuser-only path.

    Args:
        session: Async SQLAlchemy session.
        item_id: Primary key of the row to destroy.

    Returns:
        The deleted ORM instance, or ``None`` if not found.
    """
    stmt = _select({model_name}).where({model_name}.id == item_id).execution_options(include_deleted=True)
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        return None
    await session.delete(obj)
    await session.flush()
    return obj
