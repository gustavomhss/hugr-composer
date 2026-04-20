"""DataLoader primitive — per-request batch + dedupe loader.

Coalesces N resolver-level ``load(key)`` calls within one event-loop "tick"
into a single bulk fetch. Identity-preserving cache within the tick so
callers see the SAME result instance for identical keys.

Framework-agnostic: depends only on stdlib + asyncio + typing. No FastAPI,
no SQLAlchemy, no aiodataloader import. The OSS reference is cited in
``DataLoader.md`` provenance — the implementation here is a thin, auditable
reimagination of Facebook's dataloader pattern (syrusakbary/aiodataloader,
MIT).

Invariant IDs (full text in ``DataLoader.md``):

- DATALOADER_INV_01: Identical keys within one tick resolve to the SAME
  instance (identity-preserving cache).
- DATALOADER_INV_02: Batch fn receives keys in caller-insertion order;
  returned values correspond positionally.
- DATALOADER_INV_03: If batch fn raises, ALL waiting loaders for that tick
  receive that exception.
- DATALOADER_INV_04: ``clear(k)`` removes cache entry and does NOT cancel
  any in-flight batch that already contains ``k``.
- DATALOADER_INV_05: Max-batch-size cap is honored; overflow splits into
  the next batch.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, Hashable, Protocol, TypeVar, runtime_checkable

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class DataLoaderError(RuntimeError):
    """Raised when the batch contract is violated (length mismatch, etc.)."""


@runtime_checkable
class DataLoader(Protocol[K, V]):
    async def load(self, key: K) -> V: ...
    async def load_many(self, keys: list[K]) -> list[V]: ...
    def prime(self, key: K, value: V) -> None: ...
    def clear(self, key: K) -> None: ...


class InMemoryDataLoader(Generic[K, V]):
    """Reference DataLoader. One instance per request lifecycle."""

    def __init__(
        self,
        batch_fn: Callable[[list[K]], Awaitable[list[V]]],
        *,
        max_batch_size: int = 100,
    ) -> None:
        if max_batch_size < 1:
            raise DataLoaderError("max_batch_size MUST be >= 1.")
        self._batch_fn = batch_fn
        self._max_batch_size = max_batch_size
        self._cache: dict[K, asyncio.Future[V]] = {}
        self._queue: list[tuple[K, asyncio.Future[V]]] = []
        self._scheduled = False

    # ------------------------------------------------------------------
    # Public Protocol surface
    # ------------------------------------------------------------------
    async def load(self, key: K) -> V:
        """Return the value for ``key`` after the next batch dispatch."""
        if key in self._cache:
            # DATALOADER_INV_01: same tick, same key → same Future → same instance.
            return await self._cache[key]
        fut: asyncio.Future[V] = asyncio.get_event_loop().create_future()
        self._cache[key] = fut
        # DATALOADER_INV_02: preserve insertion order.
        self._queue.append((key, fut))
        self._schedule_dispatch()
        return await fut

    async def load_many(self, keys: list[K]) -> list[V]:
        return await asyncio.gather(*(self.load(k) for k in keys))

    def prime(self, key: K, value: V) -> None:
        """Seed the cache; subsequent ``load(key)`` skips the batch."""
        if key in self._cache:
            return  # idempotent — prime never clobbers an existing entry
        fut: asyncio.Future[V] = asyncio.get_event_loop().create_future()
        fut.set_result(value)
        self._cache[key] = fut

    def clear(self, key: K) -> None:
        """DATALOADER_INV_04: remove cache entry; do NOT cancel the batch."""
        self._cache.pop(key, None)

    # ------------------------------------------------------------------
    # Batch dispatch
    # ------------------------------------------------------------------
    def _schedule_dispatch(self) -> None:
        if self._scheduled:
            return
        self._scheduled = True
        asyncio.get_event_loop().call_soon(self._dispatch_sync)

    def _dispatch_sync(self) -> None:
        # Re-enters via ensure_future so the async dispatch runs on the loop.
        queue = self._queue
        self._queue = []
        self._scheduled = False
        if not queue:
            return
        asyncio.ensure_future(self._dispatch(queue))

    async def _dispatch(self, queue: list[tuple[K, asyncio.Future[V]]]) -> None:
        # DATALOADER_INV_05: split queue into chunks of max_batch_size.
        for start in range(0, len(queue), self._max_batch_size):
            chunk = queue[start : start + self._max_batch_size]
            keys = [k for k, _ in chunk]
            try:
                values = await self._batch_fn(keys)
            except BaseException as exc:  # DATALOADER_INV_03
                for _, fut in chunk:
                    if not fut.done():
                        fut.set_exception(exc)
                continue
            if len(values) != len(keys):
                err = DataLoaderError(
                    f"batch_fn returned {len(values)} values for {len(keys)} keys"
                )
                for _, fut in chunk:
                    if not fut.done():
                        fut.set_exception(err)
                continue
            # DATALOADER_INV_02: positional correspondence.
            for (_, fut), val in zip(chunk, values):
                if not fut.done():
                    fut.set_result(val)


__all__ = [
    "DataLoader",
    "DataLoaderError",
    "InMemoryDataLoader",
]
