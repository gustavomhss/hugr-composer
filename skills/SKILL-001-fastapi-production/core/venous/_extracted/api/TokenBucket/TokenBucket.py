from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
import asyncio
import time


@dataclass
class TokenBucket:
    """Asyncio-safe token bucket.

    Attributes:
        capacity: Maximum tokens the bucket holds.
        refill_rate_per_second: Tokens added per second.
    """
    capacity: float
    refill_rate_per_second: float
    _tokens: float = field(default=0.0, init=False)
    _last_refill: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    async def try_acquire(self, tokens: float=1.0) -> bool:
        """Attempt to consume *tokens* from the bucket.

        Args:
            tokens: Number of tokens to consume (default 1.0).

        Returns:
            ``True`` if the tokens were available and consumed.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate_per_second)
            self._last_refill = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
