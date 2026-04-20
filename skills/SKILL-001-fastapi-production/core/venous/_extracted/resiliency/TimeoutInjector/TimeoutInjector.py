from __future__ import annotations
import asyncio


class TimeoutInjector:
    """Simulate a hung request to trigger upstream timeouts.

    Args:
        timeout_rate: Probability (0.0–1.0) of injecting a hang.
        hang_seconds: How long to hang (default 35s — exceeds common 30s timeouts).
    """

    def __init__(self, timeout_rate: float=0.05, hang_seconds: float=35.0) -> None:
        """Initialise with a hang probability and duration.

        Args:
            timeout_rate: Fraction of calls that get a hang injected.
            hang_seconds: Duration in seconds for the simulated hang.
        """
        self.timeout_rate = timeout_rate
        self.hang_seconds = hang_seconds

    async def inject(self) -> None:
        """Sleep for hang_seconds at the configured rate."""
        if random.random() < self.timeout_rate:
            logger.debug('Chaos: injecting timeout hang (%.1fs)', self.hang_seconds)
            await asyncio.sleep(self.hang_seconds)
