from __future__ import annotations
from fastapi import Request
from typing import Any


async def get_graphql_context(request: Request) -> GraphQLContext:
    """Build a fresh ``GraphQLContext`` for the current request.

    Attempts to resolve the current user via ``Authorization`` header;
    silently sets ``user=None`` for unauthenticated requests so public
    queries remain accessible.

    Args:
        request: Incoming HTTP request.

    Returns:
        Populated ``GraphQLContext``.
    """
    user: Any | None = None
    try:
        from app.api.deps import get_current_user as _get_user
        user = await _get_user(request)
    except Exception:
        pass
    return GraphQLContext(request=request, user=user, loaders=DataLoaderRegistry())
