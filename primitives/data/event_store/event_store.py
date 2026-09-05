"""Pure Python primitive: EventStore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class EventStore:
    """Append-only store for domain events, keyed by stream_id.

    Each append is transactional and uses optimistic concurrency control.
    """

    async def append(self, session: AsyncSession, stream_id: str, event_type: str, data: dict[str, Any], expected_version: int | None=None) -> DomainEvent:
        """Append one event to a stream with optional concurrency guard.

        Args:
            session: Async SQLAlchemy session.
            stream_id: Opaque stream identifier (e.g. aggregate UUID).
            event_type: Discriminator string for the event kind.
            data: JSON-serialisable event payload.
            expected_version: If provided, the next version must equal this
                value; raises ValueError on conflict.

        Returns:
            The persisted DomainEvent with auto-assigned version and created_at.

        Raises:
            ValueError: On optimistic concurrency conflict.
        """
        next_version = await self._next_version(session, stream_id)
        if expected_version is not None and next_version != expected_version:
            raise ValueError(f'Concurrency conflict on stream {stream_id}: expected version {expected_version}, got {next_version}')
        row = await self._insert_event(session, stream_id, event_type, data, next_version)
        return _row_to_domain(row)

    async def _insert_event(self, session: AsyncSession, stream_id: str, event_type: str, data: dict[str, Any], version: int) -> 'Event':
        """Insert an Event row and commit, rolling back on IntegrityError.

        Args:
            session: Async SQLAlchemy session.
            stream_id: Target stream identifier.
            event_type: Event discriminator string.
            data: JSON-serialisable event payload.
            version: Pre-computed version number for this event.

        Returns:
            The committed Event ORM instance.

        Raises:
            ValueError: If a unique-constraint violation indicates a conflict.
        """
        row = Event(id=uuid.uuid4(), stream_id=stream_id, event_type=event_type, data_json=data, version=version)
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError(f'Concurrency conflict appending to stream {stream_id}: {exc}') from exc
        return row

    async def get_stream(self, session: AsyncSession, stream_id: str, from_version: int=1) -> list[DomainEvent]:
        """Return all events in a stream from a given version onward.

        Args:
            session: Async SQLAlchemy session.
            stream_id: Stream to query.
            from_version: Minimum version to include (default 1 = full stream).

        Returns:
            Ordered list of DomainEvent instances (oldest first).
        """
        stmt = select(Event).where(Event.stream_id == stream_id, Event.version >= from_version).order_by(Event.version)
        rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_domain(r) for r in rows]

    async def get_all_since(self, session: AsyncSession, since: datetime, limit: int=1000) -> list[DomainEvent]:
        """Return all events created after a given UTC timestamp.

        Args:
            session: Async SQLAlchemy session.
            since: UTC datetime (exclusive lower bound).
            limit: Maximum events to return.

        Returns:
            Events ordered by created_at ascending.
        """
        stmt = select(Event).where(Event.created_at > since).order_by(Event.created_at).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_domain(r) for r in rows]

    async def _next_version(self, session: AsyncSession, stream_id: str) -> int:
        """Compute the next version number for a stream.

        Args:
            session: Async SQLAlchemy session.
            stream_id: Stream identifier.

        Returns:
            Current max version + 1, or 1 if the stream is empty.
        """
        stmt = select(Event.version).where(Event.stream_id == stream_id).order_by(Event.version.desc()).limit(1)
        result = await session.execute(stmt)
        current = result.scalar_one_or_none()
        return (current or 0) + 1
