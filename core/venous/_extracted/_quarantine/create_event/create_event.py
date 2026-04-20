from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def create_event(session: AsyncSession, event_type: str, actor_id: str | None=None, subject_id: str | None=None, table_name: str | None=None, details: str | None=None) -> ComplianceEvent:
    """Append a new compliance event record.

    Args:
        session: Async database session.
        event_type: Short event classifier (e.g. 'pii_access', 'erasure').
        actor_id: ID of the user or service that triggered the event.
        subject_id: ID of the data subject the event concerns.
        table_name: Database table involved.
        details: Free-form JSON string with event context.

    Returns:
        The persisted ComplianceEvent instance.
    """
    event = ComplianceEvent(id=str(uuid.uuid4()), event_type=event_type, actor_id=actor_id, subject_id=subject_id, table_name=table_name, details=details)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event
