from __future__ import annotations
from fastapi import Request
from typing import Any


def require_dpop(request: Request, dpop: Annotated[str | None, Header(alias='DPoP')]=None) -> Any:
    """FastAPI dependency: verify DPoP proof when DPOP_ENABLED is True.

    Use as ``Depends(require_dpop)`` on routes that require proof-of-
    possession.  Returns an empty dict when DPoP is disabled, allowing
    gradual rollout.

    Args:
        request: Current HTTP request.
        dpop: Raw value of the ``DPoP`` header.

    Returns:
        Verified claims dict or empty dict when disabled.
    """
    if not settings.DPOP_ENABLED:
        return {}
    import asyncio
    return asyncio.get_event_loop().run_until_complete(_verify_dpop_proof(request, dpop))
