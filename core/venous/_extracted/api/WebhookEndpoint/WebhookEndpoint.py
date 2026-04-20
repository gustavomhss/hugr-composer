from __future__ import annotations
from datetime import datetime
import uuid


class WebhookEndpoint(Base):
    """A subscriber's registered webhook endpoint.

    Attributes:
        id: UUID primary key.
        url: Delivery URL (must be http or https).
        description: Optional human-readable description.
        events: JSON list of subscribed event type strings.
        secret: HMAC signing secret (never returned after creation).
        status: One of active / disabled / suspended.
        consecutive_failures: Counter reset to 0 on any 2xx response.
        last_success_at: UTC timestamp of last successful delivery.
        last_failure_at: UTC timestamp of last failed delivery attempt.
        user_id: Owner's user UUID (CASCADE delete).
        created_at: Creation timestamp.
    """
    __tablename__ = 'webhook_endpoints'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    events: Mapped[list] = mapped_column(JSON, nullable=False, server_default='[]')
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='active')
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deliveries: Mapped[list['WebhookDelivery']] = relationship(back_populates='endpoint', cascade='all, delete-orphan')
    __table_args__ = (CheckConstraint("status IN ('active','disabled','suspended')", name='ck_webhook_endpoints_status'), CheckConstraint("url LIKE 'http://%' OR url LIKE 'https://%'", name='ck_webhook_endpoints_url_format'))
