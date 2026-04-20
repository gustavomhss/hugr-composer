"""FastAPI adapter over the `RequestGuard` + `CurrentPrincipal` primitives.

Exposes `require(*guards)` — a FastAPI dependency factory that composes
the framework-agnostic `CompositeGuard` against a per-request
`CurrentPrincipal`. The composite is short-circuit + payload-immutable;
denials become `HTTPException(403)`, errors become 500.

Usage::

    from fastapi import Depends
    from core.venous._adapters.fastapi.RequestGuardAdapter import require
    from core.venous.auth.RequestGuard.RequestGuard import RoleGuard

    @app.get("/admin", dependencies=[Depends(require(RoleGuard("admin")))])
    async def _admin(): ...
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request

from core.venous.auth.CurrentPrincipal.CurrentPrincipal import CurrentPrincipal, anonymous
from core.venous.auth.RequestGuard.RequestGuard import (
    CompositeGuard,
    GuardOutcome,
    RequestGuardInvariantError,
)

PrincipalResolver = Callable[[Request], Awaitable[CurrentPrincipal] | CurrentPrincipal]


class _Ctx:
    """Minimal request-context adapter exposing the primitive's required shape."""

    def __init__(self, request: Request) -> None:
        self.request_id = request.headers.get("x-request-id", "-")
        self.headers = dict(request.headers)
        self.assigns: dict[str, Any] = {}


def require(*guards: Any, principal: PrincipalResolver | None = None) -> Callable[..., Awaitable[CurrentPrincipal]]:
    """Return a FastAPI dependency that evaluates *guards* and returns the principal."""
    resolver: PrincipalResolver = principal or (lambda _r: anonymous())

    async def _dep(request: Request) -> CurrentPrincipal:
        p = resolver(request)
        if hasattr(p, "__await__"):
            p = await p  # type: ignore[assignment]
        composite = CompositeGuard(list(guards))
        try:
            outcome = await composite.evaluate(_Ctx(request), p)
        except RequestGuardInvariantError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if outcome is GuardOutcome.DENY_UNAUTHENTICATED:
            raise HTTPException(status_code=401, detail="unauthenticated")
        if outcome is GuardOutcome.DENY_FORBIDDEN:
            raise HTTPException(status_code=403, detail="forbidden")
        if outcome is not GuardOutcome.ALLOW:
            raise HTTPException(status_code=500, detail="guard error")
        return p

    return _dep
