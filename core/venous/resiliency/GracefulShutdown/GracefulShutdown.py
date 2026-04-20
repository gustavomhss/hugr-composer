from __future__ import annotations
import asyncio
import time


class GracefulShutdown:
    """Coordinates a clean process shutdown across three phases.

    Args:
        drain_seconds: Seconds to wait in drain phase before completing.
        timeout_seconds: Max seconds to wait for in-flight requests.
    """

    def __init__(self, drain_seconds: float=5.0, timeout_seconds: float=30.0) -> None:
        """Initialise with drain and timeout durations.

        Args:
            drain_seconds: Duration of drain phase in seconds.
            timeout_seconds: Maximum time to wait for in-flight requests.
        """
        self.drain_seconds = drain_seconds
        self.timeout_seconds = timeout_seconds
        self._draining = False
        self._shutting_down = False
        self._in_flight = 0
        self._lock = asyncio.Lock()
        self._drain_started_at: float | None = None
        self._cleanup_callbacks: list = []

    def register(self) -> None:
        """Install SIGTERM and SIGINT handlers on the event loop."""
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGTERM, self._on_signal)
            loop.add_signal_handler(signal.SIGINT, self._on_signal)
            logger.info('GracefulShutdown registered (drain=%ds, timeout=%ds)', self.drain_seconds, self.timeout_seconds)
        except NotImplementedError:
            signal.signal(signal.SIGTERM, lambda *_: self._on_signal())
            signal.signal(signal.SIGINT, lambda *_: self._on_signal())

    def _on_signal(self) -> None:
        """Called by the OS signal — begin drain phase."""
        if self._draining:
            return
        self._draining = True
        self._drain_started_at = time.monotonic()
        logger.info('Shutdown signal received — drain phase started (drain=%ds)', self.drain_seconds)

    def is_draining(self) -> bool:
        """Return True if we are in the drain or complete phase.

        Returns:
            ``True`` once a shutdown signal has been received.
        """
        return self._draining

    def increment_in_flight(self) -> None:
        """Increment the count of in-flight requests."""
        self._in_flight += 1

    def decrement_in_flight(self) -> None:
        """Decrement the count of in-flight requests."""
        self._in_flight = max(0, self._in_flight - 1)

    def add_cleanup(self, callback) -> None:
        """Register an async cleanup callback for the cleanup phase.

        Args:
            callback: Async callable with no arguments.
        """
        self._cleanup_callbacks.append(callback)

    async def wait_complete(self) -> None:
        """Wait for drain + in-flight completion + run cleanup callbacks."""
        if not self._draining:
            return
        await asyncio.sleep(self.drain_seconds)
        logger.info('Drain complete — waiting for %d in-flight requests', self._in_flight)
        deadline = time.monotonic() + self.timeout_seconds
        while self._in_flight > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        if self._in_flight > 0:
            logger.warning('Shutdown timeout reached — %d in-flight requests abandoned', self._in_flight)
        else:
            logger.info('All in-flight requests completed.')
        for cb in self._cleanup_callbacks:
            try:
                await cb()
            except Exception:
                logger.warning('Cleanup callback raised', exc_info=True)
        self._shutting_down = True
        logger.info('Graceful shutdown complete.')
