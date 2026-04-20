from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid


class SagaInstance(Base):
    """Durable state record for one saga execution.

    Attributes:
        id: UUID primary key.
        saga_type: Subclass name (e.g. ``BookTripSaga``).
        state: ``pending`` | ``running`` | ``completed`` | ``compensating`` | ``failed``.
        current_step: Zero-based index of the step in progress.
        input_data: Original input passed to the saga.
        output_data: Final output after successful completion.
        error: Error message if saga failed.
        created_at: Row creation timestamp.
        updated_at: Last state-change timestamp.
        completed_at: Timestamp of final terminal state.
    """
    __tablename__ = 'saga_instances'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    saga_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), default='pending', nullable=False, index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    steps: Mapped[list['SagaStepExecution']] = relationship('SagaStepExecution', back_populates='saga', cascade='all, delete-orphan', order_by='SagaStepExecution.step_number')
