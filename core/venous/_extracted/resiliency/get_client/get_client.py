from __future__ import annotations
from typing import Any


async def get_client() -> Any:
    """Return the process-wide Temporal client, creating it lazily.

    On first call, creates and caches the client using settings from
    ``app.core.config.settings``.  Subsequent calls return the cached
    instance without reconnecting.

    Returns:
        A connected ``temporalio.client.Client`` instance.
    """
    global _client
    if _client is None:
        factory = TemporalClientFactory(host=settings.TEMPORAL_HOST, namespace=settings.TEMPORAL_NAMESPACE)
        _client = await factory.connect()
    return _client
