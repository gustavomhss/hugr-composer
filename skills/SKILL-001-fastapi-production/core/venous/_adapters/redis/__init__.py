"""Redis adapters — framework glue for the ``redis.asyncio`` client.

Exposes:

- ``PubSubAdapter`` — ``core.venous.events.PubSub`` backed by Redis
  ``PUBSUB`` for multi-worker fanout. Lazy-imports ``redis.asyncio`` so a
  FastAPI app boots without the SDK installed; raises ``PubSubRedisNotInstalled``
  only when a publish / subscribe call actually needs the client.

All domain invariants (PS_INV_01..05) are enforced by the motor; this
adapter is thin framework wiring + a JSON codec for wire payloads.
"""
from core.venous._adapters.redis.PubSubAdapter import (
    PubSubRedisNotInstalled,
    RedisPubSubBackend,
)

__all__ = [
    "PubSubRedisNotInstalled",
    "RedisPubSubBackend",
]
