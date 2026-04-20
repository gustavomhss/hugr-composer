from __future__ import annotations
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession


async def export_csv(session: AsyncSession, stmt: Select, columns: list[str]) -> AsyncIterator[bytes]:
    """Stream CSV bytes. Yields UTF-8 header row first, then data chunks.

    Args:
        session: Async SQLAlchemy session.
        stmt: SELECT statement for the rows to export.
        columns: Ordered list of column names to include.

    Yields:
        UTF-8 encoded CSV bytes chunks.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    yield buf.getvalue().encode('utf-8')
    buf.seek(0)
    buf.truncate()
    async for batch in _stream_batches(session, stmt):
        for row in batch:
            writer.writerow([_safe_str(getattr(row, col, '')) for col in columns])
        yield buf.getvalue().encode('utf-8')
        buf.seek(0)
        buf.truncate()
