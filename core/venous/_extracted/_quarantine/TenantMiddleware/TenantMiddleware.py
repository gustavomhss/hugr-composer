from __future__ import annotations
from fastapi import Request
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware


class TenantMiddleware(BaseHTTPMiddleware):
    """Resolve tenant from request; set in ContextVar before view runs.

    Args:
        app: ASGI application.
        resolver: How to extract the tenant slug.
            'header' reads X-Tenant-ID (default).
            'subdomain' reads the first subdomain component from Host.
            'jwt' reads request.state.tenant_slug (set by auth dep).
    """

    def __init__(self, app, resolver: str='header') -> None:
        super().__init__(app)
        self.resolver = resolver

    async def dispatch(self, request: Request, call_next):
        """Resolve tenant and set context before forwarding request.

        Args:
            request: Incoming HTTP request.
            call_next: Next ASGI handler.

        Returns:
            HTTP response, or a 400/403/404 JSON error if tenant is invalid.
        """
        if request.url.path in TENANT_FREE_PATHS:
            set_current_tenant(None)
            return await call_next(request)
        slug = self._extract_slug(request)
        if not slug:
            return JSONResponse({'detail': 'Tenant not specified'}, status_code=400)
        async with async_session_maker() as session:
            stmt = select(Tenant).where(Tenant.slug == slug)
            tenant = (await session.execute(stmt)).scalar_one_or_none()
        if tenant is None:
            return JSONResponse({'detail': 'Unknown tenant'}, status_code=404)
        if tenant.status != 'active':
            return JSONResponse({'detail': 'Tenant is not active'}, status_code=403)
        set_current_tenant(tenant.id)
        try:
            return await call_next(request)
        finally:
            set_current_tenant(None)

    def _extract_slug(self, request: Request) -> str | None:
        """Extract tenant slug from request using the configured resolver.

        Args:
            request: Incoming HTTP request.

        Returns:
            Tenant slug string, or None if not found.
        """
        if self.resolver == 'header':
            return request.headers.get('X-Tenant-ID')
        if self.resolver == 'subdomain':
            host = request.headers.get('host', '')
            return host.split('.')[0] if '.' in host else None
        if self.resolver == 'jwt':
            return getattr(request.state, 'tenant_slug', None)
        return None
