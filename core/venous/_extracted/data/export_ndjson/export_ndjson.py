from __future__ import annotations
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
import json


async def export_ndjson(session: AsyncSession, stmt: Select, columns: list[str]) -> AsyncIterator[bytes]:
    """Stream NDJSON (newline-delimited JSON). One object per line.

    Args:
        session: Async SQLAlchemy session.
        stmt: SELECT statement for the rows to export.
        columns: Ordered list of column names to include.

    Yields:
        UTF-8 encoded NDJSON bytes chunks (one JSON object per line).
    """
    async for batch in _stream_batches(session, stmt):
        lines = ''.join((json.dumps({col: _serialize(getattr(row, col, None)) for col in columns}) + '\n' for row in batch))
        yield lines.encode('utf-8')
