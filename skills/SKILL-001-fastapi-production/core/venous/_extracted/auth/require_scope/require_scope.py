from __future__ import annotations
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status


def require_scope(scope: str):
    """Return a FastAPI dependency that enforces a required scope.

    The dependency passes if the API key holds the exact scope, a wildcard
    scope that covers it (e.g. ``orders:*`` covers ``orders:read``), or ``*:*``.

    Args:
        scope: Required ``resource:action`` scope string.

    Returns:
        A FastAPI-compatible async dependency callable.

    Example::

        @router.post("/orders/", dependencies=[Depends(require_scope("orders:write"))])
        async def create_order(...): ...
    """
    from app.auth.api_key_scopes import evaluate_scope

    async def _dep(api_key: Annotated[APIKey, Depends(get_current_api_key)]) -> None:
        result = evaluate_scope(api_key.scopes or [], scope)
        if not result.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'API key missing required scope: {scope}')
    return _dep
