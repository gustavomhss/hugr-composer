from __future__ import annotations
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession


async def ReadReplicaSession() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a read-replica database session.

    Falls back to the primary engine when ``DATABASE_READ_URL`` is not
    configured, so query handlers work on projects without a replica.

    Yields:
        An ``AsyncSession`` connected to the read replica (or primary).
    """
    factory = _get_replica_factory()
    if factory is not None:
        async with factory() as session:
            yield session
        return
    try:
        from app.core.session import get_session
        async for session in get_session():
            yield session
    except ImportError:
        logger.warning('ReadReplicaSession: no replica URL and no app.core.session — yielding a placeholder (queries will fail at handler level).')
        raise
