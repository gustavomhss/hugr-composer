"""Pure Python primitive: RequestRecorder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class RequestRecorder:
    """Redis ring-buffer recorder for HTTP requests and responses.

    Stores each record as JSON in a Redis list, capped at ``max_entries``
    via ``LTRIM``.  Each entry has a SHA-256 ``id`` for stable replay
    references.

    Args:
        redis: Connected async Redis client.
        ttl_s: TTL for the list key (seconds).
        max_entries: Maximum entries to retain in the ring buffer.
        exclude_paths: Paths to skip (e.g. ["/healthz", "/metrics"]).
    """

    def __init__(self, redis: Any, ttl_s: int=3600, max_entries: int=10000, exclude_paths: list[str] | None=None) -> None:
        self.redis = redis
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.exclude_paths = exclude_paths or []

    def _make_id(self, method: str, path: str, ts: float) -> str:
        """Generate a stable SHA-256 id for a request.

        Args:
            method: HTTP method string.
            path: Request path.
            ts: Unix timestamp float.
        """
        raw = f'{method}:{path}:{ts}'
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def record(self, method: str, path: str, request_headers: dict, request_body: str, status_code: int, response_headers: dict, response_body: str, duration_ms: float) -> str | None:
        """Record a request/response pair to Redis.

        Args:
            method: HTTP method (e.g. "GET").
            path: Request path with query string.
            request_headers: Dict of request headers.
            request_body: Decoded request body string.
            status_code: HTTP response status code.
            response_headers: Dict of response headers.
            response_body: Decoded response body string.
            duration_ms: Total request duration in milliseconds.

        Returns:
            The record id, or None on error.
        """
        if any((path.startswith(p) for p in self.exclude_paths)):
            return None
        try:
            ts = time.time()
            rec_id = self._make_id(method, path, ts)
            entry = json.dumps({'id': rec_id, 'ts': ts, 'method': method, 'path': path, 'request_headers': request_headers, 'request_body': request_body, 'status_code': status_code, 'response_headers': response_headers, 'response_body': response_body, 'duration_ms': duration_ms})
            await self.redis.lpush(_LIST_KEY, entry)
            await self.redis.ltrim(_LIST_KEY, 0, self.max_entries - 1)
            await self.redis.expire(_LIST_KEY, self.ttl_s)
            return rec_id
        except Exception:
            logger.warning('RequestRecorder.record failed', exc_info=True)
            return None

    async def list_records(self, limit: int=50) -> list[dict]:
        """Return the most recent *limit* recorded requests.

        Args:
            limit: Maximum number of records to return.
        """
        try:
            raw_list = await self.redis.lrange(_LIST_KEY, 0, limit - 1)
            return [json.loads(r) for r in raw_list]
        except Exception:
            logger.warning('RequestRecorder.list_records failed', exc_info=True)
            return []

    async def get_record(self, rec_id: str) -> dict | None:
        """Return a single record by id, or None if not found.

        Args:
            rec_id: 16-character hex id from ``record()``.
        """
        try:
            raw_list = await self.redis.lrange(_LIST_KEY, 0, -1)
            for raw in raw_list:
                entry = json.loads(raw)
                if entry.get('id') == rec_id:
                    return entry
            return None
        except Exception:
            logger.warning('RequestRecorder.get_record failed', exc_info=True)
            return None

    async def flush(self) -> int:
        """Delete all recorded requests.  Returns number of keys deleted."""
        try:
            return await self.redis.delete(_LIST_KEY)
        except Exception:
            logger.warning('RequestRecorder.flush failed', exc_info=True)
            return 0
