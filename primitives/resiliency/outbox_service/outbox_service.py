"""Pure Python primitive: OutboxService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class OutboxService:
    """Writes outbox events inside the caller's active transaction.

    Args:
        session: Async SQLAlchemy session (must be inside a transaction).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def emit(self, event_type: str, payload: dict[str, Any], *, aggregate_type: str | None=None, aggregate_id: str | None=None, idempotency_key: str | None=None) -> uuid.UUID:
        """Write an outbox event row atomically with the business write.

        Args:
            event_type: Domain event name (e.g. ``OrderCreated``).
            payload: Event payload (must be JSON-serialisable).
            aggregate_type: Entity type for correlation (optional).
            aggregate_id: Entity ID for correlation (optional).
            idempotency_key: Optional dedup key; duplicate inserts are skipped.

        Returns:
            UUID of the created event row.

        Raises:
            ValueError: If payload exceeds 64 KB.
            RuntimeError: If called outside an active transaction.
        """
        if not self.session.in_transaction():
            raise RuntimeError('OutboxService.emit() must be called inside an active transaction.')
        payload_json = json.dumps(payload)
        if len(payload_json.encode()) > _MAX_PAYLOAD_BYTES:
            raise ValueError(f'Outbox payload exceeds {_MAX_PAYLOAD_BYTES} bytes limit.')
        event = OutboxEvent(event_type=event_type, payload=payload, aggregate_type=aggregate_type, aggregate_id=aggregate_id, status='pending', idempotency_key=idempotency_key)
        self.session.add(event)
        await self.session.flush([event])
        return event.id
