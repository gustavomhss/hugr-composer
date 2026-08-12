from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProcessingStrategy(str, Enum):
    """How the batch iterates its items."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class IsolationMode(str, Enum):
    """Failure-isolation policy for a batch run."""

    ALL_OR_NOTHING = "all_or_nothing"
    BEST_EFFORT = "best_effort"


@dataclass
class BatchItemResult:
    """Outcome of one batch item, positionally aligned to the input list."""

    index: int
    status_code: int
    data: Any = None
    error: str | None = None
    idempotency_key: str | None = None


class BatchCore:
    """Async batch executor with per-item timeout and isolation support.

    Args:
        handler: Async callable accepting one item and returning a result.
        timeout_per_item_s: Per-item timeout in seconds.
        max_parallel: Semaphore concurrency limit for parallel mode.
    """

    def __init__(self, handler: Callable[[Any], Awaitable[Any]], *, timeout_per_item_s: float=5.0, max_parallel: int=10) -> None:
        self._handler = handler
        self._timeout = timeout_per_item_s
        self._sem = asyncio.Semaphore(max_parallel)

    async def run(self, items: list[Any], *, mode: IsolationMode, strategy: ProcessingStrategy, idempotency_keys: list[str] | None=None) -> list[BatchItemResult]:
        """Execute all items and return per-item results.

        Args:
            items: Validated request items.
            mode: Isolation strategy (all_or_nothing or best_effort).
            strategy: Sequential or parallel execution.
            idempotency_keys: Optional per-item idempotency keys.

        Returns:
            List of BatchItemResult aligned to *items*.
        """
        keys = idempotency_keys or [None] * len(items)
        if strategy == ProcessingStrategy.SEQUENTIAL:
            results: list[BatchItemResult] = []
            for idx, (item, key) in enumerate(zip(items, keys)):
                result = await self._run_one(idx, item, key)
                results.append(result)
                if mode == IsolationMode.ALL_OR_NOTHING and result.status_code >= 400:
                    for remaining in range(idx + 1, len(items)):
                        results.append(BatchItemResult(index=remaining, status_code=409, error='Rolled back due to all_or_nothing failure.', idempotency_key=keys[remaining]))
                    return results
            return results
        tasks = [self._run_one(idx, item, key) for idx, (item, key) in enumerate(zip(items, keys))]
        return list(await asyncio.gather(*tasks))

    async def _run_one(self, idx: int, item: Any, idempotency_key: str | None) -> BatchItemResult:
        """Execute a single item with timeout guard.

        Args:
            idx: Zero-based item index.
            item: Item payload.
            idempotency_key: Optional idempotency key for this item.

        Returns:
            BatchItemResult for this item.
        """
        async with self._sem:
            try:
                data = await asyncio.wait_for(self._handler(item), timeout=self._timeout)
                return BatchItemResult(index=idx, status_code=201, data=data, idempotency_key=idempotency_key)
            except TimeoutError:
                return BatchItemResult(index=idx, status_code=504, error='Per-item timeout exceeded.', idempotency_key=idempotency_key)
            except Exception as exc:
                code = getattr(exc, 'status_code', 500)
                return BatchItemResult(index=idx, status_code=int(code), error=f'{type(exc).__name__}: {exc}', idempotency_key=idempotency_key)
