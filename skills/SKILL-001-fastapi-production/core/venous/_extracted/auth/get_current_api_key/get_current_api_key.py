from __future__ import annotations
from datetime import datetime
from datetime import timezone
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status


async def get_current_api_key(request: Request, session: SessionDep, header_value: Annotated[str | None, Depends(_api_key_header)]) -> APIKey:
    """Validate the API key from the Authorization header.

    Delegates to ``_fetch_api_key`` (DB + secret check) and
    ``_check_api_key_validity`` (status, expiry, rate-limit), then updates
    audit fields before returning the authenticated key.

    Args:
        request: Incoming FastAPI request (for IP and user-agent capture).
        session: Injected async database session.
        header_value: Raw Authorization header value.

    Returns:
        The authenticated ``APIKey`` ORM instance.

    Raises:
        HTTPException 401: Missing, malformed, invalid, revoked, or expired key.
        HTTPException 429: Per-key rate limit exceeded.
    """
    parsed = _parse_header(header_value)
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or missing API key', headers={'WWW-Authenticate': 'Bearer'})
    key_id, secret = parsed
    api_key = await _fetch_api_key(session, key_id, secret)
    await _check_api_key_validity(api_key, session)
    api_key.last_used_at = datetime.now(timezone.utc)
    api_key.last_used_ip = request.client.host if request.client else None
    api_key.last_used_ua = (request.headers.get('user-agent', '') or '')[:500]
    await session.flush()
    return api_key
