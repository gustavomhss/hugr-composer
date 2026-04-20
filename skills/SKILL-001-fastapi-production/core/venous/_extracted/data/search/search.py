from __future__ import annotations


async def search(session: _SearchSession, *, q: str, page_size: int=20, cursor_score: float | None=None, owner_id: '_search_uuid.UUID | None'=None, language: str='english') -> dict:
    """Full-text search with dialect-aware implementation.

    On PostgreSQL: tsvector + GIN index + websearch_to_tsquery + ts_rank_cd.
    On other databases: case-insensitive LIKE across all searchable columns.
    User input is ALWAYS parameterized — never interpolated into SQL.

    Args:
        session: Async SQLAlchemy session.
        q: Search query string (min 2 chars).
        page_size: Results per page (1-100).
        cursor_score: ts_rank cursor for next-page (PostgreSQL only).
        owner_id: Owner filter if model has owner_id column.
        language: PostgreSQL text search dictionary.

    Returns:
        Dict with ``data``, ``count``, ``has_more``, ``next_cursor``.

    Raises:
        ValueError: If query is shorter than 2 characters.
    """
    if not q or len(q.strip()) < 2:
        raise ValueError('Search query must be at least 2 characters.')
    if _get_dialect_name(session) != 'postgresql':
        return await _search_like_fallback(session, q=q, page_size=page_size, owner_id=owner_id)
    return await _search_postgres(session, q, page_size, cursor_score, owner_id, language)
