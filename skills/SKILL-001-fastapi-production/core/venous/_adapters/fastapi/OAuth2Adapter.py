"""FastAPI adapter over `TokenIntrospector` + `SessionStore` primitives.

Wires an OAuth2 Bearer scheme backed by a `CachingTokenIntrospector`
and a session store exposed on `app.state`. Provides:

- `install(app, introspector, session_store)` — attach both to app.state.
- `bearer_scheme` — FastAPI OAuth2PasswordBearer token extractor.
- `current_claims(audience)` — dependency factory that validates the
  token via the introspector and returns `TokenClaims`.

Usage::

    from core.venous._adapters.fastapi.OAuth2Adapter import install, current_claims

    install(app, introspector=..., session_store=...)

    @app.get("/me", dependencies=[Depends(current_claims("api"))])
    async def me(): ...
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from core.venous.auth.SessionStore.SessionStore import SessionStore
from core.venous.auth.TokenIntrospector.TokenIntrospector import (
    InvalidTokenError,
    TokenClaims,
    TokenIntrospector,
)

bearer_scheme = OAuth2PasswordBearer(tokenUrl="/oauth/token", auto_error=False)


def install(app: FastAPI, *, introspector: TokenIntrospector, session_store: SessionStore) -> None:
    """Attach both primitives to *app*.state for dependency access."""
    app.state.token_introspector = introspector
    app.state.session_store = session_store


def current_claims(audience: str) -> Callable[..., TokenClaims]:
    """Return a dependency that introspects the Bearer token for *audience*."""

    def _dep(request: Request, token: str | None = Depends(bearer_scheme)) -> TokenClaims:
        if not token:
            raise HTTPException(status_code=401, detail="missing bearer token")
        introspector: TokenIntrospector = request.app.state.token_introspector
        try:
            return introspector.introspect(token, audience)
        except InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return _dep
