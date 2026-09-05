"""Pure Python primitive: TaskManager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class TaskManager:
    """Create, update, query, and cancel tasks via Redis.

    All methods are async and accept an optional ``redis`` client.
    When ``redis`` is None the manager attempts to use a module-level
    singleton obtained from ``app.core.redis.get_redis()``.

    Args:
        redis: Optional pre-connected Redis async client.
    """

    def __init__(self, redis: Any | None=None) -> None:
        self._redis = redis

    async def _get_redis(self) -> Any:
        """Return a connected Redis client.

        Returns:
            An async Redis client instance.
        """
        if self._redis is not None:
            return self._redis
        from app.core.redis import get_redis as _get
        return await _get()

    async def create(self, owner_id: str, task_type: str, params: dict | None=None) -> str:
        """Create a new task, store initial state in Redis.

        Args:
            owner_id: UUID string of the task owner.
            task_type: Registered task type identifier.
            params: Optional input parameters for the worker.

        Returns:
            Encrypted task ID token to return to the client.
        """
        raw_id = str(uuid.uuid4())
        redis = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        mapping = {'raw_id': raw_id, 'owner_id': str(owner_id), 'task_type': task_type, 'status': TaskStatus.PENDING.value, 'progress': '0', 'message': '', 'result': '', 'error': '', 'created_at': now, 'updated_at': now, 'params': json.dumps(params or {})}
        await redis.hset(_task_key(raw_id), mapping=mapping)
        await redis.expire(_task_key(raw_id), _DEFAULT_TTL)
        return encrypt_task_id(raw_id)

    async def get(self, token: str, owner_id: str) -> dict:
        """Fetch task state for the given encrypted token.

        Args:
            token: Encrypted task ID token from the client.
            owner_id: UUID string of the requesting user.

        Returns:
            Dict with task state fields.

        Raises:
            KeyError: If task not found.
            PermissionError: If owner_id does not match.
            ValueError: If token is invalid.
        """
        raw_id = decrypt_task_id(token)
        redis = await self._get_redis()
        data = await redis.hgetall(_task_key(raw_id))
        if not data:
            raise KeyError(f'Task not found: {token}')
        stored_owner = data.get(b'owner_id', data.get('owner_id', ''))
        if isinstance(stored_owner, bytes):
            stored_owner = stored_owner.decode()
        if stored_owner != str(owner_id):
            raise PermissionError('Task belongs to a different user.')
        return {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}

    async def set_status(self, raw_id: str, status: str) -> None:
        """Update the task status field in Redis.

        Args:
            raw_id: Raw UUID string (not the encrypted token).
            status: New status value from TaskStatus.
        """
        redis = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(_task_key(raw_id), mapping={'status': status, 'updated_at': now})

    async def report_progress(self, raw_id: str, pct: int, message: str='') -> None:
        """Update progress percentage and optional message.

        Args:
            raw_id: Raw UUID string.
            pct: Progress percentage 0-100.
            message: Human-readable progress description.
        """
        redis = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(_task_key(raw_id), mapping={'progress': str(max(0, min(100, pct))), 'message': message, 'updated_at': now})

    async def set_result(self, raw_id: str, result: Any) -> None:
        """Store the final result and mark task as completed.

        Args:
            raw_id: Raw UUID string.
            result: JSON-serialisable result payload.
        """
        redis = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(_task_key(raw_id), mapping={'status': TaskStatus.COMPLETED.value, 'progress': '100', 'result': json.dumps(result), 'updated_at': now})

    async def set_error(self, raw_id: str, error: str) -> None:
        """Mark task as failed with an error message.

        Args:
            raw_id: Raw UUID string.
            error: Human-readable error string.
        """
        redis = await self._get_redis()
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(_task_key(raw_id), mapping={'status': TaskStatus.FAILED.value, 'error': error, 'updated_at': now})

    async def request_cancel(self, token: str, owner_id: str) -> None:
        """Set a Redis cancellation flag that the worker polls.

        Args:
            token: Encrypted task ID token.
            owner_id: UUID string of the requesting user.

        Raises:
            KeyError: If task not found.
            PermissionError: If caller is not the task owner.
        """
        await self.get(token, owner_id)
        raw_id = decrypt_task_id(token)
        redis = await self._get_redis()
        await redis.setex(_cancel_key(raw_id), _DEFAULT_TTL, '1')

    async def is_cancel_requested(self, raw_id: str) -> bool:
        """Check whether cancellation was requested for this task.

        Args:
            raw_id: Raw UUID string.

        Returns:
            True if a cancellation flag is set.
        """
        redis = await self._get_redis()
        return bool(await redis.exists(_cancel_key(raw_id)))
