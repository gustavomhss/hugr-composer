from __future__ import annotations
from datetime import datetime
import uuid


class ImportJob(Base):
    """Tracks the lifecycle of an async data import operation.

    Attributes:
        id: UUID primary key.
        status: Current state (pending, processing, done, failed).
        file_name: Original filename supplied by the client.
        total_rows: Total rows detected in the uploaded file.
        processed: Rows successfully committed so far.
        failed: Rows rejected by validation.
        error_report_url: URL/path to the NDJSON error report; None until done.
        error_detail: Top-level error string when status=failed.
        created_at: UTC creation timestamp (server default).
        updated_at: UTC last-updated timestamp (server default, auto-updated).
    """
    __tablename__ = 'import_jobs'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending', index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_report_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
