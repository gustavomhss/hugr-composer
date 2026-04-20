from __future__ import annotations
from datetime import datetime
import uuid


class FeatureToggle(Base):
    """Persistent feature toggle with per-user and per-environment rules.

    Attributes:
        id: UUID primary key.
        name: Unique, URL-safe toggle name.
        enabled: Master on/off switch.
        rollout_percentage: 0-100; deterministic hash-based rollout.
        allowed_users: JSON list of user-id strings always granted access.
        environments: JSON list of allowed environment strings.
        created_at: UTC creation timestamp.
        updated_at: UTC last-updated timestamp.
    """
    __tablename__ = 'feature_toggles'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    rollout_percentage: Mapped[int] = mapped_column(Integer, nullable=False, server_default='100')
    allowed_users: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    environments: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
