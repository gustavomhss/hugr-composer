from __future__ import annotations
from fastapi import status


async def chat_endpoint(ws: WebSocket, room_id: str) -> None:
    """Open a WebSocket chat session on *room_id*.

    Auth: JWT via ``?token=`` or ``Authorization: Bearer``.
    Rejection uses close code ``1008 Policy Violation``.
    """
    result = await _validate_ws_connection(ws, room_id)
    if result is None:
        return
    user_id, user_name = result
    await ws.accept()
    manager = get_ws_manager()
    registered = await manager.connect(ws, room_id=room_id, user_id=user_id)
    if not registered:
        await _send_error(ws, 'connection_limit', 'Per-user connection cap reached')
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        await _run_chat_session(ws, user_id=user_id, user_name=user_name, room_id=room_id, manager=manager)
    finally:
        await manager.disconnect(ws, room_id=room_id, user_id=user_id)
