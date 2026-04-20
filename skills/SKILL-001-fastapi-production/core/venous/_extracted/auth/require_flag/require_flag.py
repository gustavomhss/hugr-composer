from __future__ import annotations
from fastapi import HTTPException
from fastapi import status


def require_flag(key: str, default: bool=False):
    """Return a FastAPI dependency that 404s the route if the flag is disabled.

    Returns 404 (not 403) to avoid leaking whether the flag exists.

    Args:
        key: Feature flag key string.
        default: Value assumed when flag is missing (default False = blocked).

    Returns:
        FastAPI dependency callable.
    """

    async def _dep(current_user: CurrentUser, session: SessionDep) -> None:
        """Block the route if the flag is off for the current user.

        Args:
            current_user: Authenticated user from JWT.
            session: Injected async DB session.

        Raises:
            HTTPException: 404 if the flag evaluation returns False.
        """
        ctx = FlagContext(user_id=current_user.id, tenant_id=getattr(current_user, 'tenant_id', None))
        if not await is_enabled(session, key, ctx, default=default):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Feature not available')
    return _dep
