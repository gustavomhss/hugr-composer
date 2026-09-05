"""Pure Python primitive: FingerprintStore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class FingerprintStore:
    """Persistent fingerprint store backed by Redis with memory fallback.

    Args:
        redis: Optional async Redis client.  When ``None``, falls back to
            an in-process ``_MemoryStore`` (single-process only).
        ttl_s: Key expiry in seconds.
    """

    def __init__(self, redis: Any | None=None, ttl_s: int=60) -> None:
        self._redis = redis
        self._ttl_s = ttl_s
        self._memory = _MemoryStore()

    async def is_duplicate(self, fingerprint: str) -> bool:
        """Return True if this fingerprint was seen within TTL.

        Also stores the fingerprint on first sight.

        Args:
            fingerprint: 64-char hex fingerprint from RequestFingerprinter.
        """
        key = _REDIS_KEY_PREFIX + fingerprint
        if self._redis is not None:
            try:
                was_set = await self._redis.set(key, '1', nx=True, ex=self._ttl_s)
                return was_set is None or was_set is False
            except Exception:
                logger.warning('FingerprintStore Redis error — falling back to memory', exc_info=True)
        already_seen = await self._memory.exists(fingerprint)
        if not already_seen:
            await self._memory.set(fingerprint, self._ttl_s)
        return already_seen
