from __future__ import annotations
import asyncio


class LatencyInjector:
    """Inject artificial latency into requests.

    Args:
        latency_ms: Milliseconds of extra delay to add.
    """

    def __init__(self, latency_ms: int=200) -> None:
        """Initialise with a fixed latency value.

        Args:
            latency_ms: Delay in milliseconds.
        """
        self.latency_ms = latency_ms

    async def inject(self) -> None:
        """Sleep for the configured latency duration."""
        if self.latency_ms > 0:
            logger.debug('Chaos: injecting %dms latency', self.latency_ms)
            await asyncio.sleep(self.latency_ms / 1000.0)
