from __future__ import annotations


async def get_multi_cursor(session: _AsyncSession, *, cursor: str | None=None, page_size: int=20, owner_id: _uuid.UUID | None=None) -> dict:
    """Cursor-paginated list.  Stable under concurrent inserts/deletes.

    Returns a dict with ``data``, ``count``, ``next_cursor``, ``has_more``.
    Raises ``ValueError`` if cursor is malformed or encodes a mismatched field.

    Args:
        session: Async SQLAlchemy session.
        cursor: Opaque cursor from a previous response, or ``None`` for first page.
        page_size: Number of records to return per page (1-100).
        owner_id: Optional owner filter applied to both data and count queries.
    """
    stmt = _select({model_name})
    if owner_id is not None:
        stmt = stmt.where({model_name}.owner_id == owner_id)
    if hasattr({model_name}, 'is_deleted'):
        stmt = stmt.where({model_name}.is_deleted == False)
    return await _paginator.paginate(session, stmt, cursor=cursor, page_size=page_size)
