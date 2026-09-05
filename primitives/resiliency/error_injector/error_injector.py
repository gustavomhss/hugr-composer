"""Pure Python primitive: ErrorInjector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class ErrorInjector:
    """Randomly inject HTTP 500 errors.

    Args:
        error_rate: Probability (0.0–1.0) of injecting an error.
    """

    def __init__(self, error_rate: float=0.1) -> None:
        """Initialise with an error probability.

        Args:
            error_rate: Fraction of calls that result in a 500.
        """
        self.error_rate = error_rate

    def inject(self) -> None:
        """Raise HTTPException(500) at the configured rate.

        Raises:
            HTTPException: With status 500 when randomly triggered.
        """
        if random.random() < self.error_rate:
            logger.debug('Chaos: injecting 500 error (rate=%.2f)', self.error_rate)
            raise HTTPException(status_code=500, detail='Chaos fault injection — simulated server error')
