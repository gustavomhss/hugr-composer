from __future__ import annotations
from datetime import datetime
import uuid


class APIKey(Base):
    """Per-user API key record.

    Stores only the hashed secret; the plaintext is shown once at creation.

    Attributes:
        id: Primary key UUID.
        key_id: Short public identifier used in token format api_<key_id>_<secret>.
        secret_hash: Argon2id or sha256-pepper hash of the raw secret.
        name: Human-readable label.
        description: Optional extended description.
        scopes: JSON array of resource:action scope strings.
        status: One of active, revoked, expired.
        user_id: FK to users.id (CASCADE DELETE).
        expires_at: Optional hard expiry timestamp (UTC).
        last_used_at: Updated on every authenticated request.
        revoked_at: Set when status transitions to revoked.
        created_at: Immutable creation timestamp.
    """
    __tablename__ = 'api_keys'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='active')
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('active','revoked','expired')", name='ck_api_keys_status'), CheckConstraint('length(key_id) >= 16 AND length(key_id) <= 32', name='ck_api_keys_key_id_format'), Index('ix_api_keys_user_status', 'user_id', 'status'))
