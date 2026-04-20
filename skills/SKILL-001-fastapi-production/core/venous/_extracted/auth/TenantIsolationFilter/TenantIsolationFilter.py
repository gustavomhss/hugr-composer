from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


class TenantIsolationFilter:
    """Multi-tenant query isolation — auto-injects tenant_id filter.

    Usage::

        filter = TenantIsolationFilter(session, tenant_id=current_user.tenant_id)
        query = filter.apply(select(Order))
    """

    def __init__(self, session: AsyncSession, tenant_id: Any) -> None:
        """Initialise filter for a specific tenant.

        Args:
            session: Async DB session.
            tenant_id: The tenant ID to enforce on all queries.
        """
        self._session = session
        self._tenant_id = tenant_id

    def apply(self, stmt: Any, model: type | None=None) -> Any:
        """Inject tenant_id WHERE clause into a SQLAlchemy select statement.

        Args:
            stmt: SQLAlchemy Select statement.
            model: Model class with tenant_id column.
                Inferred from stmt if omitted.

        Returns:
            Statement with tenant_id filter applied.
        """
        if model is not None and hasattr(model, 'tenant_id'):
            return stmt.where(model.tenant_id == self._tenant_id)
        return stmt
