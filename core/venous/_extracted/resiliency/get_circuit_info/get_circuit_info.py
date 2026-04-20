from __future__ import annotations


async def get_circuit_info(name: str) -> dict:
    """Return a dict describing the current circuit state.

    Args:
        name: Service name.

    Returns:
        Dict with keys: name, state, failure_count, opened_at, recovery_at.
    """
    r = get_circuit_redis()
    if r is None:
        return {'name': name, 'state': CircuitState.CLOSED, 'error': 'no redis'}
    try:
        data = await r.hgetall(f'circuit:{name}')
        decoded = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
        return {'name': name, **decoded} if decoded else {'name': name, 'state': CircuitState.CLOSED}
    except Exception as exc:
        return {'name': name, 'state': CircuitState.CLOSED, 'error': str(exc)}
