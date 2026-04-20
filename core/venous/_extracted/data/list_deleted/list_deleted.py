from __future__ import annotations


async def list_deleted(session: _AsyncSession, *, skip: int=0, limit: int=20) -> dict:
    """Return paginated soft-deleted rows. Admin use only.

    Args:
        session: Async SQLAlchemy session.
        skip: Offset for pagination.
        limit: Page size (max 100).

    Returns:
        Dict with ``data`` list and ``count`` total.
    """
    stmt = _select({model_name}).where({model_name}.is_deleted == True).execution_options(include_deleted=True).order_by({model_name}.deleted_at.desc()).offset(skip).limit(limit)
    count_stmt = _select(_func.count()).select_from(_select({model_name}).where({model_name}.is_deleted == True).execution_options(include_deleted=True).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(stmt)
    return {'data': list(result.scalars().all()), 'count': total}
