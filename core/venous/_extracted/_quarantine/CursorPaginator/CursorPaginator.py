from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from typing import Literal
from uuid import UUID


class CursorPaginator(Generic[M]):
    """Generic cursor paginator for SQLAlchemy 2.0 async models.

    Attributes:
        model: The SQLAlchemy model class to paginate.
        cursor_field: Name of the column used as the sort key.
        direction: Sort direction — ``"desc"`` (newest-first) or ``"asc"``.
    """

    def __init__(self, model: type[M], cursor_field: str, direction: Literal['desc', 'asc']='desc') -> None:
        self.model = model
        self.cursor_field = cursor_field
        self.direction = direction
        self._col = getattr(model, cursor_field)
        self._id_col = getattr(model, 'id', None)

    async def paginate(self, session: AsyncSession, base_stmt: Any, *, cursor: str | None, page_size: int) -> dict[str, Any]:
        """Execute a cursor-paginated query.

        The ``base_stmt`` must NOT include ORDER BY or LIMIT — this method
        adds them.  Fetches ``page_size + 1`` rows to detect ``has_more``.

        Args:
            session: Async SQLAlchemy session.
            base_stmt: Base SELECT statement without ORDER BY / LIMIT.
            cursor: Opaque cursor from the previous page, or ``None`` for
                the first page.
            page_size: Number of records to return.

        Returns:
            Dict with keys: ``data``, ``count``, ``next_cursor``, ``has_more``.

        Raises:
            ValueError: If cursor is malformed or encodes the wrong field.
        """
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total: int = (await session.execute(count_stmt)).scalar_one()
        data_stmt = self._apply_cursor_filter(base_stmt, cursor)
        rows, has_more = await self._fetch_page(session, data_stmt, page_size)
        next_cursor = self._build_next_cursor(rows, has_more)
        return {'data': rows, 'count': total, 'next_cursor': next_cursor, 'has_more': has_more}

    def _apply_cursor_filter(self, base_stmt: Any, cursor: str | None) -> Any:
        """Apply cursor-based WHERE clause and ORDER BY to the statement.

        Args:
            base_stmt: Base SELECT without ORDER BY or LIMIT.
            cursor: Encoded cursor string, or ``None`` for first page.

        Returns:
            Statement with cursor filter and ordering applied.

        Raises:
            ValueError: If the cursor encodes a different field than expected.
        """
        data_stmt = base_stmt
        if cursor is not None:
            decoded = decode_cursor(cursor)
            if decoded['field'] != self.cursor_field:
                raise ValueError(f"Cursor field mismatch: cursor encodes '{decoded['field']}', expected '{self.cursor_field}'")
            cursor_val = self._coerce_value(decoded['value'])
            if self.direction == 'desc':
                data_stmt = data_stmt.where(self._col < cursor_val)
            else:
                data_stmt = data_stmt.where(self._col > cursor_val)
        col_ordered = self._col.desc() if self.direction == 'desc' else self._col.asc()
        return data_stmt.order_by(col_ordered)

    async def _fetch_page(self, session: AsyncSession, data_stmt: Any, page_size: int) -> tuple[list[Any], bool]:
        """Fetch one page of rows and detect whether more pages exist.

        Args:
            session: Async SQLAlchemy session.
            data_stmt: Ordered statement without LIMIT.
            page_size: Maximum rows to return.

        Returns:
            Tuple of (rows trimmed to page_size, has_more flag).
        """
        rows: list[Any] = list((await session.execute(data_stmt.limit(page_size + 1))).scalars().all())
        has_more = len(rows) > page_size
        if has_more:
            rows = rows[:page_size]
        return (rows, has_more)

    def _build_next_cursor(self, rows: list[Any], has_more: bool) -> str | None:
        """Build the next-page cursor from the last row in the current page.

        Args:
            rows: Rows returned for the current page (already trimmed).
            has_more: Whether a subsequent page exists.

        Returns:
            Encoded cursor string, or ``None`` if this is the last page.
        """
        if not has_more or not rows:
            return None
        last = rows[-1]
        val = getattr(last, self.cursor_field)
        id_val = str(getattr(last, 'id')) if self._id_col is not None else None
        return encode_cursor(self.cursor_field, val, id_val)

    def _coerce_value(self, raw: Any) -> Any:
        """Coerce a decoded cursor value to the correct Python type for the column.

        Args:
            raw: JSON-decoded value from the cursor payload.

        Returns:
            Value coerced to datetime, UUID, or the original type.
        """
        col_type = str(self._col.property.columns[0].type)
        if 'DATETIME' in col_type.upper() or 'TIMESTAMP' in col_type.upper():
            return datetime.fromisoformat(raw)
        if 'UUID' in col_type.upper():
            return UUID(raw)
        return raw
