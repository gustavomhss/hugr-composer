"""FastAPI adapter over the `FeatureToggle` primitive.

Installs a process-wide `FeatureToggleRegistry` on `app.state.toggles`
and exposes `get_registry`/`is_active(key)` dependencies for routes.

Usage::

    from fastapi import Depends, FastAPI
    from core.venous._adapters.fastapi.FeatureToggleAdapter import install, is_active

    app = FastAPI()
    install(app)

    @app.get("/beta", dependencies=[Depends(is_active("beta_ui"))])
    async def _beta(): ...
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from core.venous.flags.FeatureToggle.FeatureToggle import (
    FeatureToggleRegistry,
    ToggleContext,
)


def install(app: FastAPI) -> FeatureToggleRegistry:
    """Attach a fresh registry to *app*.state.toggles and return it."""
    registry = FeatureToggleRegistry()
    app.state.toggles = registry
    return registry


def get_registry(request: Request) -> FeatureToggleRegistry:
    """FastAPI dependency: resolve the app-wide registry."""
    return request.app.state.toggles  # type: ignore[no-any-return]


def is_active(key: str, *, environment: str = "prod") -> Callable[..., None]:
    """Return a dependency that 404s when the toggle `key` is off."""

    def _dep(request: Request, reg: FeatureToggleRegistry = Depends(get_registry)) -> None:
        ctx = ToggleContext(principal_id=None, tenant_id=None, environment=environment)
        if not reg.is_active(key, ctx):
            raise HTTPException(status_code=404, detail=f"feature '{key}' disabled")

    return _dep
