from __future__ import annotations
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status


def require_permission(code: str):
    """Return a FastAPI dependency that 403s when the user lacks *code*.

    Args:
        code: Required permission in ``resource:action`` format,
            e.g. ``"items:write"`` or ``"*:*"``.

    Returns:
        An async dependency callable suitable for ``Depends()``.
    """

    async def _dep(perms: set[str]=Depends(get_effective_permissions)) -> None:
        """Raise 403 if *code* is not in the user's effective permissions.

        Args:
            perms: Injected effective permissions from ``get_effective_permissions``.

        Raises:
            HTTPException: 403 if the required permission is missing.
        """
        if not has_permission(perms, code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'Missing required permission: {code}')
    return _dep
