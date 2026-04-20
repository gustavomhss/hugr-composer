from __future__ import annotations
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


async def export_parquet(session: AsyncSession, stmt: Select, columns: list[str]) -> AsyncIterator[bytes]:
    """Stream Parquet via pyarrow. Collects all rows (pyarrow lacks native streaming write).

    Args:
        session: Async SQLAlchemy session.
        stmt: SELECT statement for the rows to export.
        columns: Ordered list of column names to include.

    Yields:
        Single bytes chunk containing the complete Parquet file (snappy compressed).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows: list[dict[str, Any]] = []
    async for batch in _stream_batches(session, stmt):
        for row in batch:
            rows.append({col: _serialize(getattr(row, col, None)) for col in columns})
    table = pa.Table.from_pylist(rows)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression='snappy')
    yield buf.getvalue()
