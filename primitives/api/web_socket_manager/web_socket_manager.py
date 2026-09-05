"""Pure Python primitive: WebSocketManager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class WebSocketManager:
    """Redis-backed WebSocket fan-out manager for chat rooms.

    Attributes are held per-process; the Redis counter at
    ``ws:chat:conn:<user_id>`` enforces the per-user cap across workers.
    """

    def __init__(self) -> None:
        self._local: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, *, room_id: str, user_id: str) -> bool:
        """Register a newly-accepted socket against *room_id*.

        Enforces the per-user cap via a Redis counter.  Returns
        ``False`` when the cap is exceeded so the caller can close
        the socket with a policy-violation code.

        Args:
            ws: The accepted ``WebSocket`` instance.
            room_id: UUID string of the target room.
            user_id: UUID string of the authenticated user.

        Returns:
            ``True`` if the connection was registered.
        """
        redis = await get_redis()
        key = CONNECTION_COUNT_KEY.format(user_id=user_id)
        count = await redis.incr(key)
        await redis.expire(key, 86400)
        if count > _MAX_CONN_PER_USER:
            await redis.decr(key)
            return False
        async with self._lock:
            self._local.setdefault(room_id, set()).add(ws)
        return True

    async def disconnect(self, ws: WebSocket, *, room_id: str, user_id: str) -> None:
        """Release a socket's slot on disconnect.

        Args:
            ws: The closing ``WebSocket``.
            room_id: UUID string of the room.
            user_id: UUID string of the authenticated user.
        """
        redis = await get_redis()
        key = CONNECTION_COUNT_KEY.format(user_id=user_id)
        try:
            await redis.decr(key)
        except Exception:
            logger.warning('Failed to decrement ws conn counter for user=%s', user_id)
        async with self._lock:
            peers = self._local.get(room_id)
            if peers is not None:
                peers.discard(ws)
                if not peers:
                    self._local.pop(room_id, None)

    async def broadcast(self, *, room_id: str, payload: dict[str, Any]) -> None:
        """Publish *payload* to every subscriber of *room_id*.

        Fan-out is through Redis pub/sub so every worker sees the
        message and forwards it to its local sockets.

        Args:
            room_id: UUID string of the target room.
            payload: JSON-serializable dict.
        """
        redis = await get_redis()
        await redis.publish(CHANNEL_TEMPLATE.format(room_id=room_id), json.dumps(payload, separators=(',', ':'), ensure_ascii=False))

    async def subscribe_loop(self, *, ws: WebSocket, room_id: str) -> None:
        """Forward Redis messages for *room_id* to *ws* until cancel.

        Runs as a background task for the lifetime of the socket.
        Exits cleanly on ``asyncio.CancelledError`` (the endpoint
        cancels it from its ``finally`` block).

        Args:
            ws: The target ``WebSocket``.
            room_id: UUID string of the room.
        """
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(CHANNEL_TEMPLATE.format(room_id=room_id))
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    continue
                if msg.get('type') != 'message':
                    continue
                raw = msg.get('data', '')
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8')
                try:
                    await ws.send_text(raw)
                except Exception:
                    return
        except asyncio.CancelledError:
            return
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL_TEMPLATE.format(room_id=room_id))
                await pubsub.aclose()
            except Exception:
                logger.debug('pubsub cleanup failed', exc_info=True)
