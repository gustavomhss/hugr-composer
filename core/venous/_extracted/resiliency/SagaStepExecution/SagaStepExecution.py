from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid


class SagaStepExecution(Base):
    """Durable state for one step within a saga.

    Attributes:
        id: UUID primary key.
        saga_id: FK to parent SagaInstance.
        step_number: Ordinal position of the step.
        step_name: Method name of the @saga_step-decorated function.
        state: ``pending`` | ``running`` | ``completed`` | ``compensated`` | ``failed``.
        input_data: Step-level input (copied from saga context).
        output_data: Step-level output stored for compensation use.
        error: Error string if the step failed.
        compensation_attempts: Number of compensation attempts.
        compensated_at: Timestamp of successful compensation.
    """
    __tablename__ = 'saga_step_executions'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    saga_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('saga_instances.id', ondelete='CASCADE'), nullable=False, index=True)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default='pending', nullable=False)
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compensated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    saga: Mapped['SagaInstance'] = relationship('SagaInstance', back_populates='steps')
