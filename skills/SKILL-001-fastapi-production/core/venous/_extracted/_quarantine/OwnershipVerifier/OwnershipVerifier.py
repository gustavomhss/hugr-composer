from __future__ import annotations
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


class OwnershipVerifier:
    """FastAPI dependency that verifies object-level ownership.

    Raises HTTP 403 when the authenticated user does not own the
    requested resource (or strict mode is on and no ownership found).
    """

    def __init__(self, model: type, owner_field: str) -> None:
        """Initialise verifier for a specific model and owner field.

        Args:
            model: SQLAlchemy model class (e.g. Order).
            owner_field: Column name that holds the owner's user_id.
        """
        self._model = model
        self._owner_field = owner_field

    async def __call__(self, request: Request, session: AsyncSession=Depends(lambda: None)) -> None:
        """Verify ownership; raises 403/401 on violation.

        Args:
            request: The current HTTP request.
            session: Optional async DB session for ownership query.
        """
        if not _bola_enabled():
            return
        resource_id = _extract_resource_id(request, self._model.__name__.lower())
        if resource_id is None:
            if _strict_mode():
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={'detail': 'Resource ID not found in path'})
            return
        current_user_id = _get_current_user_id(request)
        if current_user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={'detail': 'Authentication required'})
        await self._enforce(session, resource_id, current_user_id)

    async def _enforce(self, session: Any, resource_id: int, current_user_id: int) -> None:
        """Enforce ownership; raises 403 on violation or no session.

        Args:
            session: Async DB session (or None if unavailable).
            resource_id: The resource primary key to check.
            current_user_id: The ID of the requesting user.
        """
        if session is None:
            logger.warning('BOLA: no session for %s/%s', self._model.__name__, resource_id)
            return
        owned = await _check_ownership(session, self._model, self._owner_field, resource_id, current_user_id)
        if not owned:
            logger.warning('BOLA_VIOLATION: user=%s tried to access %s id=%s', current_user_id, self._model.__name__, resource_id)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={'detail': 'Access denied - you do not own this resource'})
