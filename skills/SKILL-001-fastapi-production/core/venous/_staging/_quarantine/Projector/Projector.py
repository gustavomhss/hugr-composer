from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


class Projector:
    """Base class for event-sourced read model projectors.

    Subclass and implement ``handle_event`` and optionally ``save_snapshot``.

    Attributes:
        snapshot_interval: Number of events between snapshot checkpoints.
        _state: Mutable read model state dict (subclasses may customise).
    """

    def __init__(self, snapshot_interval: int=100) -> None:
        """Initialise the projector.

        Args:
            snapshot_interval: Events between automatic snapshot calls.
        """
        self.snapshot_interval = snapshot_interval
        self._state: dict[str, Any] = {}

    def project(self, event: DomainEvent) -> None:
        """Apply a single event to the projector state.

        Calls ``handle_event`` then triggers a snapshot if the interval
        has been reached.

        Args:
            event: The domain event to apply.
        """
        self.handle_event(event)
        if self.snapshot_interval > 0 and event.version % self.snapshot_interval == 0:
            self.save_snapshot(event.stream_id, event.version, self._state)

    def handle_event(self, event: DomainEvent) -> None:
        """Apply a domain event to the read model state.

        Override in subclasses to implement domain-specific projection logic.

        Args:
            event: The domain event to apply.
        """
        logger.debug('handle_event stream=%s type=%s version=%d (base no-op)', event.stream_id, event.event_type, event.version)

    def save_snapshot(self, stream_id: str, version: int, state: dict[str, Any]) -> None:
        """Persist a projection snapshot for fast catch-up on next load.

        Base implementation is a no-op.  Override to save to Redis/DB.

        Args:
            stream_id: Stream identifier.
            version: Event version at snapshot time.
            state: Current projection state to persist.
        """

    async def rebuild(self, session: AsyncSession, store: EventStore, stream_id: str) -> dict[str, Any]:
        """Rebuild the read model by replaying all events in a stream.

        Resets internal state, fetches all events for the stream, and
        applies them in order via ``project``.

        Args:
            session: Async SQLAlchemy session.
            store: EventStore to fetch events from.
            stream_id: Stream to replay.

        Returns:
            Final projection state dict after full replay.
        """
        self._state = {}
        events = await store.get_stream(session, stream_id)
        for event in events:
            self.project(event)
        logger.info('rebuild complete stream=%s events=%d', stream_id, len(events))
        return dict(self._state)
