from __future__ import annotations


async def invalidate_resource(resource: str, resource_id: str | None=None) -> int:
    """Delete all cached entries for a resource, then fan-out via pub/sub.

    Args:
        resource: Resource type (e.g. ``"items"``).
        resource_id: Specific ID to invalidate; None invalidates all.

    Returns:
        Number of Redis keys deleted.
    """
    cache = get_cache()
    if cache is None:
        return 0
    tenant = get_tenant()
    if resource_id is not None:
        pattern = f'cache:{tenant}:{resource}:{resource_id}'
        deleted = await cache.delete(pattern)
    else:
        deleted = await cache.delete_pattern(resource_pattern(tenant, resource))
    await _publish_invalidation(cache, resource, resource_id)
    return deleted
