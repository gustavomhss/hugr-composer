from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid


class AuditLog(Base):
    """Immutable audit log entry.

    Attributes:
        id: UUID primary key.
        entity_type: Lowercase model class name (e.g. 'item').
        entity_id: String representation of the entity primary key.
        action: One of create/update/delete/soft_delete/restore/read.
        user_id: UUID of the acting user, nullable.
        auth_method: Authentication method used (password/api_key/oauth2/mfa), nullable.
        before_values: JSONB diff of changed fields before the operation.
        after_values: JSONB diff of changed fields after the operation.
        ip_address: Client IP from the request (INET type).
        user_agent: HTTP User-Agent header (max 512 chars).
        entry_hash: SHA-256 hex of this row chained to prev_hash.
        prev_hash: entry_hash of the preceding audit entry.
        created_at: UTC timestamp with server default (tamper-proof).
    """
    __tablename__ = 'audit_logs'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True, comment='Authentication method: password, api_key, oauth2, mfa')
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='SHA-256 hex of this row chained to prev')
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='entry_hash of the preceding audit entry')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, primary_key=True)
    __table_args__ = (Index('ix_audit_entity', 'entity_type', 'entity_id', 'created_at'), Index('ix_audit_user', 'user_id', 'created_at'), Index('ix_audit_action', 'action', 'created_at'), CheckConstraint("action IN ('create','update','delete','soft_delete','restore','read')", name='ck_audit_action'), {'postgresql_partition_by': 'RANGE (created_at)'})
