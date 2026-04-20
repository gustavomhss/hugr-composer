from __future__ import annotations
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession


async def export_xlsx(session: AsyncSession, stmt: Select, columns: list[str]) -> AsyncIterator[bytes]:
    """Stream XLSX using xlsxwriter constant_memory mode (write-once, low RAM).

    Args:
        session: Async SQLAlchemy session.
        stmt: SELECT statement for the rows to export.
        columns: Ordered list of column names to include.

    Yields:
        Single bytes chunk containing the complete XLSX workbook.
    """
    import xlsxwriter
    buf = io.BytesIO()
    workbook = xlsxwriter.Workbook(buf, {'constant_memory': True, 'in_memory': True})
    worksheet = workbook.add_worksheet('Export')
    bold = workbook.add_format({'bold': True})
    for col_idx, col_name in enumerate(columns):
        worksheet.write(0, col_idx, col_name, bold)
    row_idx = 1
    async for batch in _stream_batches(session, stmt):
        for row in batch:
            for col_idx, col_name in enumerate(columns):
                worksheet.write(row_idx, col_idx, _safe_str(getattr(row, col_name, '')))
            row_idx += 1
    workbook.close()
    yield buf.getvalue()
