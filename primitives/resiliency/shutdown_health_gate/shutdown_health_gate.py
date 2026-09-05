"""Pure Python primitive: ShutdownHealthGate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class ShutdownHealthGate:
    """Health check gate that returns 503 during shutdown drain phase."""

    def check(self) -> None:
        """Raise HTTPException(503) if shutdown is in progress.

        Raises:
            HTTPException: With status 503 and Retry-After header hint
                when the service is draining.
        """
        sd = get_graceful_shutdown()
        if sd.is_draining():
            logger.debug('Health gate blocking request — drain in progress')
            raise HTTPException(status_code=503, detail='Service is shutting down — retry after drain completes.', headers={'Retry-After': '10'})

    def is_healthy(self) -> bool:
        """Return False when shutdown drain phase is active.

        Returns:
            ``True`` when the service is healthy, ``False`` during drain.
        """
        return not get_graceful_shutdown().is_draining()
