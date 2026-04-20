from __future__ import annotations


async def get_effective_permissions(current_user: CurrentUser, session: SessionDep) -> set[str]:
    """Resolve the effective permissions for the current user.

    Checks the per-process cache first; on a miss, computes from the DB
    and populates the cache.

    Args:
        current_user: Injected authenticated user.
        session: Injected async DB session.

    Returns:
        Set of permission code strings.
    """
    tenant_id = _get_tenant_id()
    cache = get_perm_cache()
    cached = await cache.get(current_user.id, tenant_id)
    if cached is not None:
        return cached
    perms = await compute_effective_permissions(session, current_user.id, tenant_id)
    await cache.set(current_user.id, tenant_id, perms)
    return perms
