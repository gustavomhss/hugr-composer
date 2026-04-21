"""Redis adapter for the ``events.PubSub`` primitive.

Implements the same ``PubSub`` Protocol surface as
``core.venous.events.PubSub.InMemoryPubSub`` but routes every publish /
subscribe through a shared Redis ``PUBSUB`` channel so multi-worker
FastAPI deployments see a single fanout space.

Design:

- ``redis.asyncio`` is imported LAZILY inside the first call that needs a
  live client. A FastAPI app can boot (and import this module) without the
  ``redis`` package installed; the missing-dep error is raised only when
  a publish / subscribe actually runs. Matches the Bulkhead / RateLimiter
  adapter convention.
- Payloads cross the wire as JSON (``json.dumps`` / ``json.loads``). The
  adapter exposes the codec so callers passing non-JSON-serialisable
  payloads get a ``TypeError`` inside ``publish`` rather than a silent
  Redis-side rejection.
- The reference in-process backend (``InMemoryPubSub``) remains the
  correctness oracle. This adapter is expected to preserve the same
  observable semantics in a single-broker configuration.

All domain invariants (PS_INV_01..05) are enforced by the motor contract
— this module adds no invariants of its own.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from core.venous.events.PubSub import PubSubClosed, PubSubInvariantError


__all__ = [
    "PubSubRedisNotInstalled",
    "RedisPubSubBackend",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class PubSubRedisNotInstalled(ImportError):
    """Raised when a Redis-dependent call runs without the SDK installed.

    The adapter deliberately defers this error to call time so module
    import stays side-effect-free — a FastAPI app that chooses the
    in-process backend at boot NEVER triggers this error.
    """


# ---------------------------------------------------------------------------
# Redis-backed PubSub
# ---------------------------------------------------------------------------
class RedisPubSubBackend:
    """PubSub backend that fans publishes through Redis ``PUBSUB``.

    Args:
        redis_url: Explicit connection URL. When ``None`` the adapter reads
            ``REDIS_URL`` from the environment and falls back to
            ``redis://localhost:6379/0``. Keep the URL out of logs — it may
            contain credentials.

    Satisfies the ``core.venous.events.PubSub`` Protocol. Closable via
    ``close()`` — after close every subsequent ``publish`` / ``subscribe``
    raises ``PubSubClosed`` (symmetric with the motor's closed semantics).
    """

    __slots__ = ("_url", "_client", "_closed")

    def __init__(self, redis_url: str | None = None) -> None:
        self._url: str = (
            redis_url
            if redis_url is not None
            else os.getenv("REDIS_URL", "redis://localhost:6379/0")
        )
        self._client: Any = None
        self._closed: bool = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def url(self) -> str:
        """The configured Redis URL (credentials included — never log)."""
        return self._url

    # ---- lifecycle --------------------------------------------------------
    def _get_client(self) -> Any:
        """Return a lazy-initialised ``redis.asyncio.Redis`` client.

        Raises:
            PubSubRedisNotInstalled: the ``redis`` package is not available.
        """
        if self._client is None:
            try:
                import redis.asyncio as aioredis  # noqa: PLC0415
            except ImportError as exc:
                raise PubSubRedisNotInstalled(
                    "RedisPubSubBackend requires the `redis` package. "
                    "Install via `pip install redis>=5`, OR switch the "
                    "PubSub factory to the in-memory backend.",
                ) from exc
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def close(self) -> None:
        """Soft-close: mark the backend closed and best-effort close the
        Redis client. Idempotent.
        """
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            close = getattr(self._client, "aclose", None) or getattr(
                self._client, "close", None,
            )
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self._client = None

    # ---- publish ----------------------------------------------------------
    async def publish(self, topic: str, payload: Any) -> None:
        """Encode ``payload`` as JSON and publish to Redis channel ``topic``.

        Raises:
            PubSubClosed: ``close()`` has been called.
            PubSubInvariantError: ``topic`` is not a non-empty str (PS_INV_03).
            PubSubRedisNotInstalled: the ``redis`` package is missing.
            TypeError: ``payload`` is not JSON-serialisable.
        """
        if self._closed:
            raise PubSubClosed(
                "PS_INV_01: RedisPubSubBackend is closed; publish rejected "
                "to avoid silently dropping payloads.",
            )
        if not isinstance(topic, str) or topic == "":
            raise PubSubInvariantError(
                "PS_INV_03: topic MUST be a non-empty str to preserve "
                f"isolation; got {topic!r}.",
            )
        encoded = json.dumps(payload)
        client = self._get_client()
        await client.publish(topic, encoded)

    # ---- subscribe --------------------------------------------------------
    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Subscribe to Redis channel ``topic`` and yield decoded payloads.

        Redis ``PUBSUB`` is a live stream — payloads published before the
        ``SUBSCRIBE`` reaches the server are NOT delivered (PS_INV_05 holds
        by construction).

        Raises:
            PubSubClosed: ``close()`` has been called.
            PubSubInvariantError: ``topic`` is not a non-empty str.
            PubSubRedisNotInstalled: the ``redis`` package is missing.
        """
        if self._closed:
            raise PubSubClosed(
                "PS_INV_01: RedisPubSubBackend is closed; subscribe rejected.",
            )
        if not isinstance(topic, str) or topic == "":
            raise PubSubInvariantError(
                "PS_INV_03: topic MUST be a non-empty str to preserve "
                f"isolation; got {topic!r}.",
            )
        client = self._get_client()
        async with client.pubsub() as pubsub:
            await pubsub.subscribe(topic)
            try:
                async for message in pubsub.listen():
                    if not isinstance(message, dict):
                        continue
                    if message.get("type") != "message":
                        # Skip handshake frames (subscribe/unsubscribe).
                        continue
                    data = message.get("data")
                    if data is None:
                        continue
                    yield json.loads(data)
            finally:
                # PS_INV_04: explicit unsubscribe on generator finally so
                # Redis releases the channel reference synchronously.
                try:
                    await pubsub.unsubscribe(topic)
                except Exception:  # noqa: BLE001 — best-effort teardown.
                    pass
