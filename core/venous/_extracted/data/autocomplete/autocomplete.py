from __future__ import annotations


async def autocomplete(session: _SearchSession, *, q: str, owner_id: '_search_uuid.UUID | None'=None, language: str='english') -> list[str]:
    """Prefix-match autocomplete with dialect-aware implementation.

    On PostgreSQL: uses to_tsquery('term:*') for sub-20ms p99 latency.
    On other databases: falls back to case-insensitive LIKE prefix match.

    Returns up to 5 suggestions.

    Args:
        session: Async SQLAlchemy session.
        q: Partial query (min 1 char).
        owner_id: Filter by owner if model has owner_id.
        language: PostgreSQL text search dictionary.

    Returns:
        List of up to 5 matching title/name strings.
    """
    if not q or not q.strip():
        return []
    if _get_dialect_name(session) != 'postgresql':
        return await _autocomplete_like(session, q, owner_id)
    first_token = q.strip().split()[0]
    prefix_query = _func.to_tsquery(_text("'" + language + "'"), _text("'" + first_token + ":*'"))
    tv = _build_search_tsvector(language)
    stmt = _select(MODEL_NAME_CLS.FIRST_FIELD).where(tv.op('@@')(prefix_query)).order_by(MODEL_NAME_CLS.id.desc()).limit(5)
    if hasattr(MODEL_NAME_CLS, 'is_deleted'):
        stmt = stmt.where(MODEL_NAME_CLS.is_deleted == False)
    if owner_id is not None and hasattr(MODEL_NAME_CLS, 'owner_id'):
        stmt = stmt.where(MODEL_NAME_CLS.owner_id == owner_id)
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0]]
