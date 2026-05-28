from __future__ import annotations
from datetime import datetime
import uuid


class FeatureFlag(Base):
    """Feature flag configuration row.

    Attributes:
        id: UUID primary key.
        key: URL/code-safe unique flag identifier.
        description: Optional human-readable description.
        flag_type: One of 'boolean', 'variant', 'json'.
        enabled: Master on/off switch.
        default_value: Fallback value when flag is off.
        rollout_percentage: 0-100 percentage rollout.
        targeting_rules: JSON array of attribute-based rules.
        variants: JSON array of variant objects with 'name' and 'weight'.
        kill_switch: If true, evaluation always returns False/default.
        created_at: UTC creation timestamp.
        updated_at: UTC last-updated timestamp.
        updated_by: UUID of last actor.
    """
    __tablename__ = 'feature_flags'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    flag_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default='boolean')
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    default_value: Mapped[dict] = mapped_column(JSON, nullable=False, server_default='{}')
    rollout_percentage: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    targeting_rules: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    variants: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    audit_log: Mapped[list['FeatureFlagAudit']] = relationship(back_populates='flag', cascade='all, delete-orphan')
    __table_args__ = (CheckConstraint("flag_type IN ('boolean','variant','json')", name='ck_feature_flags_type'), CheckConstraint('rollout_percentage BETWEEN 0 AND 100', name='ck_feature_flags_rollout_range'), CheckConstraint('length(key) >= 1 AND length(key) <= 127', name='ck_feature_flags_key_format'))
