from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class AdaptiveThrottleMiddleware(BaseHTTPMiddleware):
    """ASGI middleware enforcing adaptive throttle rules.

    Applies fingerprint-based penalty checks and cascading cooldowns.
    Skips throttle checks when ADAPTIVE_THROTTLE_ENABLED is False.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request through adaptive throttle gate.

        Args:
            request: Incoming ASGI request.
            call_next: Next handler in the middleware chain.

        Returns:
            Response from downstream or 429 if throttled.
        """
        cfg: AdaptiveThrottleConfig = build_config()
        if not cfg.enabled:
            return await call_next(request)
        fp = fingerprint_request(request)
        tier = _get_tier(fp)
        if tier > 0:
            wait = penalty_seconds_for_tier(tier)
            logger.warning('adaptive_throttle.blocked', extra={'fp': fp, 'tier': tier, 'retry_after': wait})
            return JSONResponse(status_code=429, content={'detail': 'Too many requests — adaptive throttle active', 'penalty_tier': tier, 'retry_after_seconds': wait}, headers={'Retry-After': str(wait)})
        response = await call_next(request)
        if response.status_code == 429:
            new_tier = _escalate_tier(fp)
            logger.info('adaptive_throttle.escalated', extra={'fp': fp, 'new_tier': new_tier})
        return response
