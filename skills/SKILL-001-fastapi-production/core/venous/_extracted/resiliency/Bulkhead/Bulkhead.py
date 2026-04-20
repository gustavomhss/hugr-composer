from __future__ import annotations
import os


class Bulkhead:
    """Manages separate semaphore pools per endpoint group.

    Args:
        config: BulkheadConfig specifying max_concurrent per group.
    """

    def __init__(self, config: BulkheadConfig | None=None) -> None:
        """Initialise Bulkhead with per-group pools from config."""
        cfg = config or get_default_config()
        self._pools: dict[str, _PoolState] = {name: _PoolState(limit) for name, limit in cfg.limits.items()}

    def acquire(self, group: str) -> _PoolState:
        """Return the pool context manager for *group*.

        Usage::

            async with bulkhead.acquire("payments"):
                result = await call_payment_service()

        Args:
            group: Endpoint group name.

        Returns:
            Async context manager that acquires/releases a semaphore slot.

        Raises:
            BulkheadFullError: When the pool is at maximum concurrency.
        """
        pool = self._pools.get(group)
        if pool is None:
            default_limit = int(os.getenv('BULKHEAD_DEFAULT_MAX', '50'))
            self._pools[group] = _PoolState(default_limit)
            logger.info("Created bulkhead pool '%s' with limit %d", group, default_limit)
            pool = self._pools[group]
        return pool

    def status(self) -> dict[str, dict[str, int]]:
        """Return current pool utilization for all groups.

        Returns:
            Dict mapping group name → dict with 'active', 'max', 'available'.
        """
        return {name: {'active': pool.active, 'max': pool.max, 'available': pool.available} for name, pool in self._pools.items()}
