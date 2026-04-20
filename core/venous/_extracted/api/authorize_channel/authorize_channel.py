from __future__ import annotations
from fastapi import HTTPException
from fastapi import status


def authorize_channel(user: User, channel: str) -> None:
    """Validate that *user* is allowed to subscribe to *channel*.

    Args:
        user: The authenticated requesting user.
        channel: The logical SSE channel string.

    Raises:
        HTTPException: 403 if the user is not allowed.
        HTTPException: 400 if the channel format is invalid.
    """
    if channel.startswith('user:'):
        target = channel[len('user:'):]
        if str(user.id) != target:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot subscribe to another user's channel")
        return
    if channel.startswith('tenant:'):
        parts = channel.split(':', 2)
        if len(parts) < 3:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid channel format')
        tenant_id = parts[1]
        user_tenant = getattr(user, 'tenant_id', None)
        if user_tenant is None or str(user_tenant) != tenant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot subscribe to another tenant's channel")
        return
    if channel.startswith('public:'):
        return
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Unknown channel namespace: {channel!r}')
