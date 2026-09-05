"""Pure Python primitive: ChaosEngine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class ChaosEngine:
    """Central registry for chaos injectors.

    Args:
        latency_ms: Extra latency to inject (milliseconds).
        error_rate: Fraction of requests to fail with 500 (0.0–1.0).
        timeout_rate: Fraction of requests to hang until timeout (0.0–1.0).
    """

    def __init__(self, latency_ms: int=0, error_rate: float=0.0, timeout_rate: float=0.0) -> None:
        """Initialise chaos engine with given injection parameters.

        Args:
            latency_ms: Milliseconds of extra latency per request.
            error_rate: Fraction of requests that receive a 500 error.
            timeout_rate: Fraction of requests that are timed out.
        """
        self.latency_ms = latency_ms
        self.error_rate = error_rate
        self.timeout_rate = timeout_rate
        self._enabled = False

    def enable(self) -> None:
        """Enable fault injection (blocked in production)."""
        env = os.getenv('ENVIRONMENT', 'local')
        if env == 'production':
            logger.error('CHAOS BLOCKED: cannot enable chaos in production environment.')
            return
        self._enabled = True
        logger.warning('Chaos enabled: latency=%dms, error_rate=%.2f, timeout_rate=%.2f', self.latency_ms, self.error_rate, self.timeout_rate)

    def disable(self) -> None:
        """Disable all fault injection."""
        self._enabled = False
        logger.info('Chaos disabled.')

    def is_enabled(self) -> bool:
        """Return True if chaos is active (and not in production).

        Returns:
            ``True`` when chaos is enabled and environment is not production.
        """
        if os.getenv('ENVIRONMENT', 'local') == 'production':
            return False
        return self._enabled

    def status(self) -> dict:
        """Return the current chaos configuration as a dict.

        Returns:
            Dict with keys: enabled, environment, latency_ms,
            error_rate, timeout_rate.
        """
        return {'enabled': self.is_enabled(), 'environment': os.getenv('ENVIRONMENT', 'local'), 'latency_ms': self.latency_ms, 'error_rate': self.error_rate, 'timeout_rate': self.timeout_rate}
