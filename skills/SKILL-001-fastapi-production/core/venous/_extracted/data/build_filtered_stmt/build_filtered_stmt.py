from __future__ import annotations
from sqlalchemy import select
from typing import Any
from typing import Type


def build_filtered_stmt(model_cls: Type[DeclarativeBase], filters: dict[str, Any]) -> Select:
    """Build a SELECT statement applying all supported filters.

    Supported filter keys: owner_id, tenant_id.
    ``is_deleted`` is always forced to ``False`` when the column exists.

    Args:
        model_cls: SQLAlchemy mapped class to query.
        filters: Dict of column name -> value to filter on.

    Returns:
        Configured SELECT statement.
    """
    stmt = select(model_cls)
    for col_name, col_value in filters.items():
        col = getattr(model_cls, col_name, None)
        if col is None:
            continue
        stmt = stmt.where(col == col_value)
    if hasattr(model_cls, 'is_deleted'):
        stmt = stmt.where(model_cls.is_deleted.is_(False))
    return stmt
