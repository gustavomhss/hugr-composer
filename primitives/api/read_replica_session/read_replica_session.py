"""Read replica session helper."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

class ReadReplicaSession:
    """Helper to route read queries to a replica."""

    def __init__(self, replica_engine):
        self.session_factory = sessionmaker(replica_engine, class_=AsyncSession, expire_on_commit=False)

    async def __aenter__(self) -> AsyncSession:
        self.session = self.session_factory()
        return self.session

    async def __aexit__(self, *args):
        await self.session.close()
